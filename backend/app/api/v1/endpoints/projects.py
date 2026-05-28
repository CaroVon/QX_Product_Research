"""
============================================================
项目相关 API 路由
—— POST/GET 等核心业务接口
============================================================
"""

from __future__ import annotations

import uuid
import os
import logging
from typing import Any
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import class_mapper

from app.core.database import get_db
from app.core.config import get_settings
from app.models.project import Project, ProjectStatus
from app.models.task import Task, TaskType, TaskStatus
from app.models.user import User
from app.schemas import (
    ProjectCreateRequest,
    ProjectCreateResponse,
    ProjectResponse,
    ProjectStatusResponse,
    TaskResponse,
    DownloadResponse,
    MessageResponse,
)
from app.tasks.report_workflow import run_full_report_workflow  # Celery 任务
from app.models.base import orm_to_dict

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/projects", tags=["projects"])


# ================================================================
# POST /api/v1/projects —— 创建行研项目并触发异步任务
# ================================================================

@router.post("", response_model=ProjectCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreateRequest,
    db: AsyncSession = Depends(get_db),
    # TODO: 未来接入 Auth 后，从 JWT 中提取当前用户
    # current_user: User = Depends(get_current_user),
):
    """
    创建一个行业研究项目，自动触发后台 Celery 任务链。

    - **topic**: 研报主题，例如 "AI眼镜行业"
    - 返回项目的 UUID 和 Celery Task ID，前端可用后者轮询进度。
    """
    # ─── 伪代码：未来接入认证后，从此处获取真实用户 ────────────
    # 目前使用一个默认的演示用户（id 需提前 seed 到数据库）
    current_user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")

    # ─── 1. 校验用户额度 ──────────────────────────────────────
    # TODO: 取消注释下方逻辑以启用额度校验
    # user = await db.get(User, current_user_id)
    # if user is None:
    #     raise HTTPException(status_code=404, detail="用户不存在")
    # if user.monthly_project_limit != -1 and user.projects_used_this_month >= user.monthly_project_limit:
    #     raise HTTPException(
    #         status_code=429,
    #         detail="本月项目创建额度已用尽，请升级套餐或等待下月重置",
    #     )

    # ─── 2. 创建 Project 记录 ─────────────────────────────────
    project = Project(
        owner_id=current_user_id,
        topic=body.topic,
        status=ProjectStatus.PENDING,
    )
    db.add(project)
    await db.flush()  # 获取 project.id

    # ─── 3. 创建初始 Task 链记录 ──────────────────────────────
    # 定义一个任务链，按顺序执行
    task_definitions = [
        (TaskType.SEARCH, 1, None),
        (TaskType.BUILD_KNOWLEDGE_BASE, 2, None),
        (TaskType.GENERATE_OUTLINE, 3, None),
        # 章节撰写任务将在生成大纲后动态创建（由 Celery 任务内部处理）
        (TaskType.BUILD_REPORT, 97, None),
        (TaskType.GENERATE_PDF, 98, None),
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

    # ─── 4. 提交 Celery 异步任务 ──────────────────────────────
    # 将 project_id 传递给 Celery，任务内部从头开始编排
    celery_task = run_full_report_workflow.delay(str(project.id))

    # ─── 5. 更新 Project 的 celery_task_id ────────────────────
    # （可选：记录根任务 ID 到 project 表）
    # project.celery_root_task_id = celery_task.id

    # 更新项目状态为 processing
    project.status = ProjectStatus.PROCESSING
    await db.commit()

    logger.info(
        "项目已创建 | topic=%s | project_id=%s | celery_task_id=%s",
        body.topic, project.id, celery_task.id,
    )

    return ProjectCreateResponse(
        project=ProjectResponse.model_validate(
            orm_to_dict(project)
        ),
        celery_task_id=celery_task.id,
        message="项目已创建，异步研究任务已提交至后台执行",
    )


# ================================================================
# GET /api/v1/projects/{project_id}/status —— 查询进度
# ================================================================

@router.get("/{project_id}/status", response_model=ProjectStatusResponse)
async def get_project_status(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    查询指定项目的完整进度状态。

    返回项目信息、所有 Task 步骤的详细状态、以及整体进度百分比。
    前端可轮询此接口（建议间隔 2-5 秒）。
    """
    # ─── 1. 查询项目 ──────────────────────────────────────────
    result = await db.execute(
        select(Project).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"项目 {project_id} 不存在",
        )

    # ─── 2. 查询所有任务 ──────────────────────────────────────
    task_result = await db.execute(
        select(Task)
        .where(Task.project_id == project_id)
        .order_by(Task.sequence_order)
    )
    tasks = task_result.scalars().all()

    # ─── 3. 统计进度 ──────────────────────────────────────────
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
        project_status=project.status.value,
        progress=progress,
        tasks=[TaskResponse.model_validate(orm_to_dict(t)) for t in tasks],
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

    # ─── 检查状态 ──────────────────────────────────────────────
    if project.status == ProjectStatus.PENDING or project.status == ProjectStatus.PROCESSING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"报告正在生成中（当前状态: {project.status.value}），请先查询进度接口等待完成",
        )
    if project.status == ProjectStatus.FAILED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"报告生成失败，错误原因: {project.error_message or '未知错误'}",
        )

    # ─── 检查文件是否存在 ──────────────────────────────────────
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

    # ─── 获取文件大小 ──────────────────────────────────────────
    file_size = os.path.getsize(pdf_full_path)

    # ─── 构建下载 URL ──────────────────────────────────────────
    # 实际文件通过静态文件服务提供（见 app/main.py 中的 Mount）
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
    skip: int = 0,
    limit: int = 20,
):
    """
    获取当前用户的所有项目列表（按创建时间倒序）。
    TODO: 当前未做用户隔离，未来应加入 auth 后按 current_user.id 过滤。
    """
    result = await db.execute(
        select(Project)
        .order_by(Project.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    projects = result.scalars().all()
    return [ProjectResponse.model_validate(orm_to_dict(p)) for p in projects]
