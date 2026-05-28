"""
============================================================
Pydantic V2 请求/响应模型
—— 用于 API 路由的校验和文档生成
============================================================
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, ConfigDict


# ================================================================
# 通用消息响应
# ================================================================

class MessageResponse(BaseModel):
    """通用消息响应"""
    detail: str = Field(..., description="操作结果消息")


class ErrorResponse(BaseModel):
    """标准错误响应"""
    detail: str = Field(..., description="错误详情")
    error_code: str | None = Field(None, description="错误码")


# ================================================================
# 项目 (Project) Schemas
# ================================================================

class ProjectCreateRequest(BaseModel):
    """创建项目的请求体"""
    topic: str = Field(
        ...,
        min_length=2,
        max_length=500,
        description="行业研究主题，例如：'AI眼镜行业'",
        examples=["AI眼镜行业"],
    )


class ProjectResponse(BaseModel):
    """项目响应（列表/详情）"""
    id: uuid.UUID = Field(..., description="项目 UUID")
    topic: str = Field(..., description="研报主题")
    status: str = Field(..., description="项目状态")
    pdf_path: str | None = Field(None, description="PDF 文件路径")
    md_path: str | None = Field(None, description="Markdown 文件路径")
    error_message: str | None = Field(None, description="错误信息")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime | None = Field(None, description="更新时间")

    model_config = ConfigDict(from_attributes=True)


class ProjectCreateResponse(BaseModel):
    """创建项目后的响应（含任务跟踪信息）"""
    project: ProjectResponse = Field(..., description="项目信息")
    celery_task_id: str = Field(..., description="Celery 根任务 ID（可用于后续查询）")
    message: str = Field(default="项目已创建，异步任务已提交", description="提示消息")


# ================================================================
# 任务 (Task) Schemas
# ================================================================

class TaskResponse(BaseModel):
    """单个任务步骤的响应"""
    id: uuid.UUID = Field(..., description="任务 UUID")
    task_type: str = Field(..., description="任务类型")
    status: str = Field(..., description="任务状态")
    sequence_order: int = Field(..., description="执行顺序")
    section_title: str | None = Field(None, description="关联章节标题")
    retry_count: int = Field(0, description="已重试次数")
    error_message: str | None = Field(None, description="错误信息")
    started_at: datetime | None = Field(None, description="开始时间")
    completed_at: datetime | None = Field(None, description="完成时间")
    created_at: datetime = Field(..., description="创建时间")

    model_config = ConfigDict(from_attributes=True)


class ProjectStatusResponse(BaseModel):
    """项目进度查询响应"""
    project_id: uuid.UUID = Field(..., description="项目 UUID")
    topic: str = Field(..., description="研报主题")
    project_status: str = Field(..., description="项目整体状态")
    progress: dict[str, Any] = Field(
        default_factory=lambda: {
            "total_tasks": 0,
            "completed_tasks": 0,
            "failed_tasks": 0,
            "percentage": 0.0,
        },
        description="进度概览",
    )
    tasks: list[TaskResponse] = Field(default_factory=list, description="所有任务步骤详情")

    model_config = ConfigDict(from_attributes=True)


# ================================================================
# 文档 (Document) Schemas
# ================================================================

class DocumentResponse(BaseModel):
    """章节文档响应"""
    id: uuid.UUID = Field(..., description="文档 UUID")
    section_title: str = Field(..., description="章节标题")
    section_order: int = Field(..., description="章节顺序")
    version: int = Field(1, description="版本号")
    content: str = Field(..., description="章节内容（Markdown）")
    source_urls: str | None = Field(None, description="参考来源 URL 列表（JSON）")
    created_at: datetime = Field(..., description="创建时间")

    model_config = ConfigDict(from_attributes=True)


# ================================================================
# 下载 Schemas
# ================================================================

class DownloadResponse(BaseModel):
    """下载链接响应"""
    project_id: uuid.UUID = Field(..., description="项目 UUID")
    topic: str = Field(..., description="研报主题")
    download_url: str = Field(..., description="PDF 下载链接")
    filename: str = Field(..., description="推荐的文件名")
    file_size_bytes: int | None = Field(None, description="文件大小（字节）")
    report_ready: bool = Field(True, description="报告是否已就绪")
