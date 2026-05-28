"""
============================================================
Celery 任务内部使用的数据库工具函数
—— 用于在 Celery Worker 中更新 Task 状态
注意：Celery Worker 和 FastAPI 进程分离，
因此 Worker 需要自己创建独立的数据库会话
============================================================
"""

from __future__ import annotations

import asyncio
import uuid
import logging
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy import select

from app.core.config import get_settings
from app.models.task import Task, TaskStatus, TaskType
from app.models.project import Project, ProjectStatus
from app.models.document import Document

logger = logging.getLogger(__name__)

# ─── 为 Celery Worker 创建独立的异步引擎 ──────────────────────
# 注意：Worker 与 FastAPI 是不同进程，不能共享 engine
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
    status: ProjectStatus,
    error_message: str | None = None,
    pdf_path: str | None = None,
    md_path: str | None = None,
) -> None:
    """更新项目整体状态"""
    pid = uuid.UUID(project_id)
    async with get_celery_db() as db:
        result = await db.execute(select(Project).where(Project.id == pid))
        project = result.scalar_one_or_none()
        if project is None:
            logger.warning("未找到项目: %s", project_id)
            return

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
# 同步包装器（供 Celery Task 直接调用）
# ================================================================

def update_task_status_sync(
    project_id: str, task_type: TaskType, status: TaskStatus, error: str | None = None
) -> None:
    """同步包装：更新任务状态"""
    asyncio.run(update_task_status(project_id, task_type, status, error))


def save_document_sync(
    project_id: str,
    section_title: str,
    content: str,
    raw_content: str | None = None,
    source_urls: list[str] | None = None,
    section_order: int = 0,
) -> None:
    """同步包装：保存章节文档"""
    asyncio.run(
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
    """同步包装：更新项目整体状态"""
    asyncio.run(
        update_project_status(
            project_id=project_id,
            status=status or ProjectStatus.PROCESSING,
            error_message=error_message,
            pdf_path=pdf_path,
            md_path=md_path,
        )
    )
