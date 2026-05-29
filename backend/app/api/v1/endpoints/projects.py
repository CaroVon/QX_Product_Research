"""
============================================================
项目相关 API 路由
—— POST/GET 等核心业务接口
    状态机关键交互节点：创建 → 准备 → 待大纲审批 → 撰写 → 完成
============================================================
"""

from __future__ import annotations

import json
import uuid
import os
import logging
import asyncio
from typing import Any
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.config import get_settings
from app.models.project import Project, ProjectStatus
from app.models.task import Task, TaskType, TaskStatus
from app.models.user import User
from app.models.document_block import DocumentBlock
from app.models.document import Document
from app.schemas import (
    ProjectCreateRequest,
    ProjectCreateResponse,
    ProjectResponse,
    ProjectStatusResponse,
    TaskResponse,
    DownloadResponse,
    MessageResponse,
    OutlineApproveRequest,
    OutlineApproveResponse,
    DocumentBlockResponse,
    DocumentBlockListResponse,
    SSEDraftEvent,
    ReportContentResponse,
    SectionContent,
)
from app.tasks.report_workflow import (
    run_full_report_workflow,       # 全自动流水线（旧版兼容）
    prepare_data_workflow,          # 节点1：资料准备（搜索+建库+大纲）
    run_draft_sections_workflow,    # 节点2：分章节异步撰写（审批后触发）
)
from app.models.base import orm_to_dict

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/projects", tags=["projects"])


# ================================================================
# 状态机日志打印（产品化关键标志）
# ================================================================

def log_state_transition(
    project_id: str,
    from_status: str | None,
    to_status: str,
    reason: str = "",
):
    """
    记录项目状态机流转日志。
    这是从"批处理工具"转向"交互式 Agent"的标志性函数——
    每一次状态变化都清晰可追溯。
    """
    logger.info("🔷 [STATE MACHINE] project=%s | %s → %s | reason=%s",
                project_id, from_status or "(初始)", to_status, reason)


# ================================================================
# POST /api/v1/projects —— 创建行研项目，触发「节点1：资料准备」
# ================================================================

@router.post("", response_model=ProjectCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    创建一个行业研究项目，自动触发「节点1：资料准备与大纲生成」。

    状态机详解：
    PREPARING_DATA (初始) →
      当资料准备+大纲生成完成后，自动变为 WAITING_OUTLINE_APPROVAL，
      等待用户通过 POST /approve-outline 确认。

    参数:
    - **topic**: 研报主题，例如 "AI眼镜行业"

    返回项目 ID，前端可用 GET /status 轮询进度。
    """
    # ─── 演示用户 ──────────────────────────────────────────────
    current_user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")

    # ─── 1. 创建 Project 记录（初始状态：PREPARING_DATA） ──────
    project = Project(
        owner_id=current_user_id,
        topic=body.topic,
        status=ProjectStatus.PREPARING_DATA,
    )
    db.add(project)
    await db.flush()

    log_state_transition(str(project.id), None, "preparing_data",
                         f"用户提交行研主题: {body.topic}")

    # ─── 2. 创建 Task 链记录（节点1：搜索 → 知识库 → 大纲） ──
    task_definitions = [
        (TaskType.SEARCH, 1, None),
        (TaskType.BUILD_KNOWLEDGE_BASE, 2, None),
        (TaskType.GENERATE_OUTLINE, 3, None),
    ]
    for task_type, seq, section in task_definitions:
        task = Task(
            project_id=project.id,
            task_type=task_type,
            status=TaskStatus.PENDING,
            sequence_order=seq,
            section_title=section,
        )
        db.add(task)
    await db.commit()
    await db.refresh(project)

    # ─── 3. 提交 Celery 「节点1：资料准备」异步任务 ────────────
    celery_task = prepare_data_workflow.delay(str(project.id))

    logger.info("项目已创建 | topic=%s | project_id=%s | celery_task=%s",
                body.topic, project.id, celery_task.id)

    return ProjectCreateResponse(
        project=ProjectResponse.model_validate(orm_to_dict(project)),
        celery_task_id=celery_task.id,
        message="项目已创建，正在搜索资料并生成大纲，请稍候通过 /status 查询进度",
    )


# ================================================================
# GET /api/v1/projects/{project_id}/status —— 查询进度（含大纲暂存）
# ================================================================

@router.get("/{project_id}/status", response_model=ProjectStatusResponse)
async def get_project_status(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    查询指定项目的完整进度状态。

    当项目处于 WAITING_OUTLINE_APPROVAL 状态时，
    返回的 outline_content 字段包含 LLM 生成的大纲 Markdown，
    前端可将其渲染到 Tiptap 编辑器中供用户审阅/修改。

    前端轮询建议间隔：2-5 秒。
    """
    result = await db.execute(
        select(Project).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"项目 {project_id} 不存在",
        )

    # ─── 查询所有任务步 ──────────────────────────────────────
    task_result = await db.execute(
        select(Task)
        .where(Task.project_id == project_id)
        .order_by(Task.sequence_order)
    )
    tasks = task_result.scalars().all()

    # ─── 统计进度 ──────────────────────────────────────────────
    total = len(tasks)
    completed = sum(1 for t in tasks if t.status == TaskStatus.COMPLETED)
    failed = sum(1 for t in tasks if t.status == TaskStatus.FAILED)
    percentage = round((completed / total * 100), 1) if total > 0 else 0.0

    progress = {
        "total_tasks": total,
        "completed_tasks": completed,
        "failed_tasks": failed,
        "percentage": percentage,
    }

    return ProjectStatusResponse(
        project_id=project.id,
        topic=project.topic,
        project_status=project.status,
        outline_content=project.outline_content,
        progress=progress,
        tasks=[TaskResponse.model_validate(orm_to_dict(t)) for t in tasks],
    )


# ================================================================
# POST /api/v1/projects/{project_id}/approve-outline —— 🎯 交互核心节点
# ================================================================

@router.post("/{project_id}/approve-outline", response_model=OutlineApproveResponse)
async def approve_outline(
    project_id: uuid.UUID,
    body: OutlineApproveRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    🎯 **产品交互核心节点**：用户确认/修改大纲后触发「节点2：分章节撰写」。

    状态机推进：
    WAITING_OUTLINE_APPROVAL ──(用户审批)──→ DRAFTING

    流程：
    1. 接收前端提交的最终大纲（用户可能已在 Tiptap 中修改了 LLM 生成的内容）
    2. 将最终大纲保存到 project.outline_content
    3. 从大纲的 Markdown 中解析出 ## 章节标题
    4. 将 Project.status 从 waiting_outline_approval → drafting
    5. 为每个章节创建 Task (WRITE_SECTION) + DocumentBlock 占位
    6. 异步触发 Celery 任务，逐章节生成草稿内容

    请求体：
    - **outline**: 最终确认的大纲 Markdown（用户修改后的版本）

    状态约束：
    - 仅当项目状态为 `waiting_outline_approval` 时可调用
    - 否则返回 409 Conflict
    """
    result = await db.execute(
        select(Project).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"项目 {project_id} 不存在",
        )

    # ─── 校验状态 ──────────────────────────────────────────────
    if project.status != ProjectStatus.WAITING_OUTLINE_APPROVAL:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"当前项目状态为 '{project.status.value}'，"
                "仅当状态为 'waiting_outline_approval' 时可以审批大纲。"
                "请先等待资料准备完成。"
            ),
        )

    # ─── 1. 保存最终确定的大纲 ─────────────────────────────────
    project.outline_content = body.outline

    # ─── 2. 解析章节标题 ──────────────────────────────────────
    sections = _extract_sections_from_outline(body.outline)

    if not sections:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="解析大纲失败：未找到任何 '## ' 开头的章节标题。"
                   "请确保大纲使用 Markdown 二级标题格式。",
        )

    # ─── 3. 状态机推进：WAITING_OUTLINE_APPROVAL → DRAFTING ────
    old_status = project.status
    project.status = ProjectStatus.DRAFTING
    log_state_transition(
        str(project.id),
        old_status,
        "drafting",
        f"用户确认大纲，共 {len(sections)} 个章节，即将开始异步撰写",
    )

    # ─── 4. 清理旧 DocumentBlock 占位 + 创建新的 Task & Block ──
    # 先删除该项目下所有旧的 DocumentBlock 占位记录（防止重复调用导致 MultipleResultsFound）
    await db.execute(
        delete(DocumentBlock).where(DocumentBlock.project_id == project.id)
    )

    for idx, section_title in enumerate(sections):
        # 创建 Task
        write_task = Task(
            project_id=project.id,
            task_type=TaskType.WRITE_SECTION,
            status=TaskStatus.PENDING,
            sequence_order=10 + idx,
            section_title=section_title,
        )
        db.add(write_task)

        # 创建 DocumentBlock 占位（内容为空，等待撰写完成后填充）
        block = DocumentBlock(
            project_id=project.id,
            section_title=section_title,
            order_index=(idx + 1) * 10,  # 10, 20, 30...
            content=f"## {section_title}\n\n_等待生成中..._\n",
            citations="{}",
        )
        db.add(block)

    # ─── 确保有 BUILD_REPORT + GENERATE_PDF 收尾任务 ──────────
    existing_types = await db.execute(
        select(Task.task_type).where(
            Task.project_id == project.id,
            Task.task_type.in_([TaskType.BUILD_REPORT, TaskType.GENERATE_PDF]),
        )
    )
    existing_type_set = {row[0] for row in existing_types.fetchall()}

    if TaskType.BUILD_REPORT not in existing_type_set:
        db.add(Task(
            project_id=project.id,
            task_type=TaskType.BUILD_REPORT,
            status=TaskStatus.PENDING,
            sequence_order=97,
        ))
    if TaskType.GENERATE_PDF not in existing_type_set:
        db.add(Task(
            project_id=project.id,
            task_type=TaskType.GENERATE_PDF,
            status=TaskStatus.PENDING,
            sequence_order=98,
        ))

    await db.commit()

    # ─── 5. 触发「节点2：分章节异步撰写」 ─────────────────────
    celery_task = run_draft_sections_workflow.delay(str(project.id))

    logger.info("大纲已确认 | project=%s | sections=%d | celery_task=%s",
                project.id, len(sections), celery_task.id)

    return OutlineApproveResponse(
        project_id=project.id,
        new_status=ProjectStatus.DRAFTING.value,
        message=f"大纲已确认，共 {len(sections)} 个章节，异步撰写任务已提交",
        sections_count=len(sections),
        celery_task_id=celery_task.id,
    )


def _extract_sections_from_outline(outline: str) -> list[str]:
    """
    从大纲 Markdown 中提取所有 ## 开头的二级标题作为章节名。
    示例输入：
        # AI眼镜行业
        ## 1. 行业概述
        ## 2. 市场规模
    返回：["1. 行业概述", "2. 市场规模"]
    """
    import re
    lines = outline.split("\n")
    sections = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## ") or stripped.startswith("##\t"):
            title = re.sub(r"^##\s+", "", stripped)
            if title:
                sections.append(title)
    return sections


# ================================================================
# 加分项：GET /api/v1/projects/{project_id}/stream-draft —— SSE 流式输出
# ================================================================

@router.get("/{project_id}/stream-draft")
async def stream_draft(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    🌊 **SSE (Server-Sent Events) 流式草稿输出**（加分项）

    前端可通过 EventSource 连接此接口，实时接收各章节撰写完成事件。
    每完成一个 DocumentBlock，后端通过 SSE 推送该块内容，
    前端 Tiptap 编辑器可即时插入，实现"逐块流式呈现"的效果。

    SSE 事件格式:
    - event: section_start   → 某章节开始撰写
    - event: section_chunk   → 章节的某个块已完成（含完整 DocumentBlock 数据）
    - event: section_complete → 某章节全部完成
    - event: draft_complete  → 所有章节撰写完毕
    - event: error           → 发生错误

    前端使用示例:
    ```typescript
    const es = new EventSource(`/api/v1/projects/${id}/stream-draft`);
    es.addEventListener('section_chunk', (e) => {
      const block = JSON.parse(e.data);
      // 插入到 Tiptap 编辑器
    });
    ```

    NOTE: 当前为伪代码实现。生产环境中，Celery 任务完成时应将事件
    写入 Redis Pub/Sub 或数据库轮询表，SSE 端点从中读取并推送。
    此处使用轮询方式模拟 SSE 流。
    """
    pid_str = str(project_id)

    async def event_generator():
        """
        伪代码：SSE 事件生成器。

        实际实现应改为：
        1. Celery Worker 在每完成一个 DocumentBlock 后，
           向 Redis Stream（key: draft_stream:{project_id}）写入事件
        2. 此 SSE 端点订阅 Redis Stream，实时推送
        3. 前端 EventSource 连接后即刻收到推送
        """
        # ─── 确认项目存在 ──────────────────────────────────────
        result = await db.execute(
            select(Project).where(Project.id == project_id)
        )
        project = result.scalar_one_or_none()
        if project is None:
            yield f"event: error\ndata: {json.dumps({'error': '项目不存在'})}\n\n"
            return

        if project.status != ProjectStatus.DRAFTING:
            yield f"event: error\ndata: {json.dumps({'error': f'项目状态为 {project.status}，无法流式输出'})}\n\n"
            return

        # ─── 模拟：轮询 DocumentBlock 表，有新块即推送 ─────────
        # 实际生产代码应改为 Redis Pub/Sub 或 WebSocket
        import asyncio as _asyncio

        last_block_count = 0
        max_wait_cycles = 120  # 最多等待 120 个轮询周期（约 10 分钟）
        wait_cycles = 0

        # 获取总章节数
        sections = _extract_sections_from_outline(project.outline_content or "")
        total_sections = len(sections) if sections else 0

        yield f"event: draft_start\ndata: {json.dumps({'project_id': pid_str, 'total_sections': total_sections})}\n\n"

        while wait_cycles < max_wait_cycles:
            # 查询最新的 DocumentBlock
            block_result = await db.execute(
                select(DocumentBlock)
                .where(DocumentBlock.project_id == project_id)
                .order_by(DocumentBlock.order_index)
            )
            all_blocks = block_result.scalars().all()

            if len(all_blocks) > last_block_count:
                # 有新块完成，逐条推送
                for block in all_blocks[last_block_count:]:
                    block_data = DocumentBlockResponse.model_validate(
                        orm_to_dict(block)
                    ).model_dump(mode="json")

                    yield f"event: section_chunk\ndata: {json.dumps(block_data, ensure_ascii=False)}\n\n"

                last_block_count = len(all_blocks)

                # 检查是否全部章节的任务都已完成
                task_result = await db.execute(
                    select(Task).where(
                        Task.project_id == project_id,
                        Task.task_type == TaskType.WRITE_SECTION,
                    )
                )
                write_tasks = task_result.scalars().all()
                all_done = all(t.status == TaskStatus.COMPLETED for t in write_tasks)

                if all_done and len(write_tasks) > 0:
                    yield f"event: draft_complete\ndata: {json.dumps({'project_id': pid_str, 'total_blocks': last_block_count})}\n\n"
                    return

            await _asyncio.sleep(5)  # 每 5 秒轮询一次
            wait_cycles += 1

        yield f"event: error\ndata: {json.dumps({'error': 'SSE 流超时'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ================================================================
# GET /api/v1/projects/{project_id}/blocks —— 获取所有文档块
# ================================================================

@router.get("/{project_id}/blocks", response_model=DocumentBlockListResponse)
async def list_document_blocks(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    获取项目所有文档块（按 order_index 排序）。
    前端 Tiptap 编辑器加载此数据，渲染为可编辑的块列表。
    """
    result = await db.execute(
        select(Project).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"项目 {project_id} 不存在",
        )

    block_result = await db.execute(
        select(DocumentBlock)
        .where(DocumentBlock.project_id == project_id)
        .order_by(DocumentBlock.order_index)
    )
    blocks = block_result.scalars().all()

    return DocumentBlockListResponse(
        project_id=project.id,
        blocks=[DocumentBlockResponse.model_validate(orm_to_dict(b)) for b in blocks],
    )


# ================================================================
# GET /api/v1/projects/{project_id}/content —— 获取报告全文内容
# ================================================================

@router.get("/{project_id}/content", response_model=ReportContentResponse)
async def get_report_content(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    获取项目的完整报告内容（按章节顺序排列）。

    返回每章的 Markdown 正文 + 引用 URL 映射，
    供 ReportPage 渲染带溯源的报告阅读器。
    """
    # 1. 验证项目存在
    result = await db.execute(
        select(Project).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"项目 {project_id} 不存在",
        )

    # 2. 查询所有章节文档，按 section_order 排序
    doc_result = await db.execute(
        select(Document)
        .where(Document.project_id == project_id)
        .order_by(Document.section_order)
    )
    documents = doc_result.scalars().all()

    # 3. 组装返回数据
    sections: list[SectionContent] = []
    for doc in documents:
        citations: dict[str, str] = {}
        if doc.source_urls:
            try:
                urls: list[str] = json.loads(doc.source_urls)
                for idx, url in enumerate(urls):
                    citations[str(idx + 1)] = url
            except json.JSONDecodeError:
                logger.warning(
                    "解析 source_urls JSON 失败 | project_id=%s | section='%s' | raw=%s",
                    project_id, doc.section_title, doc.source_urls,
                )

        sections.append(SectionContent(
            title=doc.section_title,
            order=doc.section_order,
            content=doc.content,
            citations=citations,
        ))

    return ReportContentResponse(
        project_id=project.id,
        topic=project.topic,
        sections=sections,
    )


# ================================================================
# GET /api/v1/projects/{project_id}/download —— 获取 PDF 下载链接
# ================================================================

@router.get("/{project_id}/download", response_model=DownloadResponse)
async def download_report(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    当报告生成完毕后，获取 PDF 文件的下载链接。

    - 如果项目尚未完成，返回 409 Conflict
    - 如果项目已完成，返回可下载的 URL
    """
    result = await db.execute(
        select(Project).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"项目 {project_id} 不存在",
        )

    if project.status in (ProjectStatus.PREPARING_DATA, ProjectStatus.WAITING_OUTLINE_APPROVAL, ProjectStatus.DRAFTING):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"报告正在生成中（当前状态: {project.status}），请先查询进度接口等待完成",
        )
    if project.status == ProjectStatus.FAILED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"报告生成失败，错误原因: {project.error_message or '未知错误'}",
        )

    if not project.pdf_path:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="项目已完成但 PDF 路径为空，请联系管理员",
        )

    settings = get_settings()
    pdf_full_path = os.path.join(settings.OUTPUT_DIR, project.pdf_path)
    if not os.path.exists(pdf_full_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"PDF 文件未找到（路径: {pdf_full_path}），可能已被清理",
        )

    file_size = os.path.getsize(pdf_full_path)
    download_url = f"{settings.PDF_DOWNLOAD_BASE_URL}/{project.pdf_path}"

    return DownloadResponse(
        project_id=project.id,
        topic=project.topic,
        download_url=download_url,
        filename=os.path.basename(project.pdf_path),
        file_size_bytes=file_size,
        report_ready=True,
    )


# ================================================================
# GET /api/v1/projects —— 获取当前用户的项目列表
# ================================================================

@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
):
    """
    获取当前用户的所有项目列表（按创建时间倒序）。
    """
    result = await db.execute(
        select(Project)
        .order_by(Project.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    projects = result.scalars().all()
    return [ProjectResponse.model_validate(orm_to_dict(p)) for p in projects]
