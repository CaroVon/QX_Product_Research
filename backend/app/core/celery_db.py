"""
============================================================
Celery 任务内部使用的数据库工具函数
—— 用于在 Celery Worker 中更新 Task 状态
注意：Celery Worker 和 FastAPI 进程分离，
因此 Worker 需要自己创建独立的数据库会话
============================================================
"""

from __future__ import annotations

import os
import sys
import asyncio
import uuid
import json
import logging
import tempfile
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy import create_engine, select, event
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.models.task import Task, TaskStatus, TaskType
from app.models.project import Project, ProjectStatus
from app.models.document import Document
from app.models.document_block import DocumentBlock

logger = logging.getLogger(__name__)

# ─── Windows asyncio 兼容性修复 ─────────────────────────────────
# 在 Windows 上，Python 3.8+ 默认使用 ProactorEventLoop，
# 该事件循环不支持 subprocess（Celery 子任务会用到），
# 因此显式设置为 SelectorEventLoop
if sys.platform == "win32":
    try:
        from asyncio import WindowsSelectorEventLoopPolicy
        asyncio.set_event_loop_policy(WindowsSelectorEventLoopPolicy())
    except ImportError:
        pass  # Python < 3.8 没有这个方法，忽略

# ─── 为 Celery Worker 创建独立的异步引擎 ──────────────────────
settings = get_settings()
celery_engine = create_async_engine(
    settings.DATABASE_URL_ASYNC,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
)
CeleryAsyncSession = async_sessionmaker(
    celery_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@event.listens_for(celery_engine.sync_engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    """SQLite 连接时自动启用 WAL 模式和 foreign key 约束"""
    if "sqlite" in str(settings.DATABASE_URL_ASYNC):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.close()


# ─── 为 Celery Worker 创建共享的同步引擎（避免每个 task 重复创建）─
# 注意：同步引擎用于简单的查询操作（获取 topic 等）
_sync_engine = None

def get_sync_engine():
    """获取共享的同步数据库引擎（延迟初始化，线程安全）"""
    global _sync_engine
    if _sync_engine is None:
        sync_url = settings.DATABASE_URL_SYNC
        if "sqlite" in sync_url:
            # SQLite 需要特殊配置以支持多线程访问
            _sync_engine = create_engine(
                sync_url,
                connect_args={"check_same_thread": False} if "sqlite" in sync_url else {},
                poolclass=NullPool,  # SQLite 不适合连接池
            )
        else:
            _sync_engine = create_engine(
                sync_url,
                pool_size=3,
                max_overflow=5,
                pool_pre_ping=True,
            )
    return _sync_engine


# ─── 平台感知的临时目录 ───────────────────────────────────
def _get_temp_dir() -> str:
    """获取平台感知的临时目录路径"""
    return settings.OUTPUT_DIR or tempfile.gettempdir()


def get_crawled_data_path(project_id: str) -> str:
    """获取项目爬取数据的暂存文件路径（跨平台兼容）"""
    temp_dir = _get_temp_dir()
    os.makedirs(temp_dir, exist_ok=True)
    return os.path.join(temp_dir, f"crawled_data_{project_id}.json")


@asynccontextmanager
async def get_celery_db() -> AsyncGenerator[AsyncSession, None]:
    """Celery Worker 中使用的数据库会话上下文管理器"""
    session = CeleryAsyncSession()
    try:
        yield session
        await session.commit()
    except Exception as e:
        await session.rollback()
        logger.error("Celery DB 操作回滚: %s", str(e))
        raise
    finally:
        await session.close()


# ================================================================
# 任务状态更新工具函数（在 Celery Worker 中调用）
# ================================================================

async def update_task_status(
    project_id: str,
    task_type: TaskType,
    status: TaskStatus,
    error_message: str | None = None,
    celery_task_id: str | None = None,
) -> None:
    """
    更新指定 project 中特定类型任务的执行状态。
    这是整个异步架构的"状态回写"核心函数——前端轮询时看到的就是这里写入的数据。

    参数:
        project_id: 项目 UUID 字符串
        task_type: 任务类型枚举
        status: 新状态
        error_message: 错误信息（可选）
        celery_task_id: Celery 任务 ID（可选）
    """
    pid = uuid.UUID(project_id)
    async with get_celery_db() as db:
        result = await db.execute(
            select(Task).where(
                Task.project_id == pid,
                Task.task_type == task_type,
            )
        )
        task = result.scalar_one_or_none()
        if task is None:
            logger.warning("未找到任务: project=%s, type=%s", project_id, task_type)
            return

        task.status = status
        if status == TaskStatus.PROCESSING:
            task.started_at = datetime.now(timezone.utc)
        elif status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
            task.completed_at = datetime.now(timezone.utc)
        if error_message:
            task.error_message = error_message[:500]  # 截断避免超长
        if celery_task_id:
            task.celery_task_id = celery_task_id

        logger.info(
            "[DB] 更新任务状态 | project=%s | type=%s | status=%s",
            project_id, task_type.value, status.value,
        )


async def update_project_status(
    project_id: str,
    status: ProjectStatus | None = None,
    error_message: str | None = None,
    pdf_path: str | None = None,
    md_path: str | None = None,
) -> None:
    """
    更新项目整体状态。

    参数:
        status: 新的项目状态（None 表示不更新状态字段）
        error_message: 错误信息
        pdf_path: PDF 文件路径
        md_path: Markdown 文件路径
    """
    pid = uuid.UUID(project_id)
    async with get_celery_db() as db:
        result = await db.execute(select(Project).where(Project.id == pid))
        project = result.scalar_one_or_none()
        if project is None:
            logger.warning("未找到项目: %s", project_id)
            return

        if status is not None:
            project.status = status
        if error_message:
            project.error_message = error_message[:1000]
        if pdf_path:
            project.pdf_path = pdf_path
        if md_path:
            project.md_path = md_path

        logger.info(
            "[DB] 更新项目状态 | project=%s | status=%s",
            project_id, status.value,
        )


async def create_section_tasks(
    project_id: str,
    section_titles: list[str],
) -> None:
    """
    根据大纲动态创建章节撰写任务。
    在 GENERATE_OUTLINE 步骤完成后调用。
    """
    pid = uuid.UUID(project_id)
    async with get_celery_db() as db:
        for idx, title in enumerate(section_titles):
            # 检查是否已存在（避免重复创建）
            existing = await db.execute(
                select(Task).where(
                    Task.project_id == pid,
                    Task.section_title == title,
                )
            )
            if existing.scalar_one_or_none():
                continue

            task = Task(
                project_id=pid,
                task_type=TaskType.WRITE_SECTION,
                status=TaskStatus.PENDING,
                sequence_order=10 + idx,  # 在 10 之后开始
                section_title=title,
            )
            db.add(task)

        logger.info(
            "[DB] 已创建 %d 个章节撰写任务 | project=%s",
            len(section_titles), project_id,
        )


async def save_document(
    project_id: str,
    section_title: str,
    content: str,
    raw_content: str | None = None,
    source_urls: list[str] | None = None,
    section_order: int = 0,
) -> None:
    """保存章节文档快照"""
    pid = uuid.UUID(project_id)
    import json
    async with get_celery_db() as db:
        doc = Document(
            project_id=pid,
            section_title=section_title,
            section_order=section_order,
            content=content,
            raw_content=raw_content,
            source_urls=json.dumps(source_urls, ensure_ascii=False) if source_urls else None,
        )
        db.add(doc)
        logger.info("[DB] 保存章节文档 | project=%s | section=%s", project_id, section_title)


# ================================================================
# DocumentBlock 工具函数
# ================================================================

async def save_document_block(
    project_id: str,
    section_title: str,
    content: str,
    citations: dict[str, str] | None = None,
    order_index: int = 0,
) -> None:
    """
    保存或更新文档块（DocumentBlock）。
    如果某章节标题+order_index 的组合已存在，则更新内容；
    否则新增一条 DocumentBlock 记录。

    这是 Tiptap 块级编辑器的核心数据写入函数——
    Celery Worker 每完成一个章节的一个逻辑块，就调用此函数保存。
    """
    pid = uuid.UUID(project_id)
    json_citations = json.dumps(citations, ensure_ascii=False) if citations else "{}"

    async with get_celery_db() as db:
        # 查找是否已存在相同 section_title + order_index 的块
        existing = await db.execute(
            select(DocumentBlock).where(
                DocumentBlock.project_id == pid,
                DocumentBlock.section_title == section_title,
                DocumentBlock.order_index == order_index,
            )
        )
        # 使用 .first() 而非 scalar_one_or_none()，避免存在重复行时抛出 MultipleResultsFound
        block = existing.first()

        if block:
            # 更新已有块的内容
            block.content = content
            block.citations = json_citations
            logger.info(
                "[DB] 更新文档块 | project=%s | section=%s | order=%d",
                project_id, section_title, order_index,
            )
        else:
            # 创建新的文档块
            block = DocumentBlock(
                project_id=pid,
                section_title=section_title,
                content=content,
                citations=json_citations,
                order_index=order_index,
            )
            db.add(block)
            logger.info(
                "[DB] 新增文档块 | project=%s | section=%s | order=%d",
                project_id, section_title, order_index,
            )


async def update_project_outline(
    project_id: str,
    outline_content: str,
) -> None:
    """在 Project 表中暂存大纲内容（等待用户确认）"""
    pid = uuid.UUID(project_id)
    async with get_celery_db() as db:
        result = await db.execute(select(Project).where(Project.id == pid))
        project = result.scalar_one_or_none()
        if project is None:
            logger.warning("未找到项目: %s", project_id)
            return
        project.outline_content = outline_content
        logger.info(
            "[DB] 保存大纲 | project=%s | len=%d",
            project_id, len(outline_content),
        )


# ================================================================
# 同步包装器（供 Celery Task 直接调用）
# ================================================================

def _run_async(coro):
    """
    在同步上下文中运行异步协程。

    此函数处理了 Windows 上的事件循环差异：
    - 使用 asyncio.run() 创建新的事件循环（每次调用独立）
    - 避免了嵌套事件循环和 'event loop is already running' 错误
    """
    try:
        return asyncio.run(coro)
    except RuntimeError as e:
        if "event loop is already running" in str(e).lower():
            # 已有运行中的事件循环（如 Jupyter/IPython 环境），
            # 使用 nest_asyncio 或直接 await
            logger.warning("检测到运行中的事件循环，尝试嵌套执行")
            import nest_asyncio
            nest_asyncio.apply()
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(coro)
        raise


def update_task_status_sync(
    project_id: str, task_type: TaskType, status: TaskStatus, error: str | None = None
) -> None:
    """同步包装：更新任务状态"""
    _run_async(update_task_status(project_id, task_type, status, error))


def save_document_sync(
    project_id: str,
    section_title: str,
    content: str,
    raw_content: str | None = None,
    source_urls: list[str] | None = None,
    section_order: int = 0,
) -> None:
    """同步包装：保存章节文档"""
    _run_async(
        save_document(
            project_id=project_id,
            section_title=section_title,
            content=content,
            raw_content=raw_content,
            source_urls=source_urls,
            section_order=section_order,
        )
    )


def update_project_status_sync(
    project_id: str,
    status: ProjectStatus | None = None,
    error_message: str | None = None,
    pdf_path: str | None = None,
    md_path: str | None = None,
) -> None:
    """
    同步包装：更新项目整体状态。
    注意：status 参数为 None 时不会更新状态字段，
    仅更新传入的 error_message / pdf_path / md_path。
    """
    _run_async(
        update_project_status(
            project_id=project_id,
            status=status,
            error_message=error_message,
            pdf_path=pdf_path,
            md_path=md_path,
        )
    )


def save_document_block_sync(
    project_id: str,
    section_title: str,
    content: str,
    citations: dict[str, str] | None = None,
    order_index: int = 0,
) -> None:
    """同步包装：保存/更新文档块"""
    _run_async(
        save_document_block(
            project_id=project_id,
            section_title=section_title,
            content=content,
            citations=citations,
            order_index=order_index,
        )
    )


def update_project_outline_sync(
    project_id: str,
    outline_content: str,
) -> None:
    """同步包装：保存大纲"""
    _run_async(
        update_project_outline(
            project_id=project_id,
            outline_content=outline_content,
        )
    )
