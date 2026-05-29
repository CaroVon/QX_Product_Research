"""
============================================================
Pydantic V2 请求/响应模型
—— 用于 API 路由的校验和文档生成
    新增状态机交互相关的 Schema：大纲审批、DocumentBlock 块级响应、SSE 事件
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
    outline_content: str | None = Field(None, description="暂存的大纲 Markdown")
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
# 大纲审批 (Outline Approval) Schemas
# ================================================================

class OutlineApproveRequest(BaseModel):
    """
    用户确认/修改大纲的请求体。
    用户可以在前端 Tiptap 编辑器中修改大纲后提交，
    或者直接确认 LLM 生成的原始大纲。
    """
    outline: str = Field(
        ...,
        min_length=10,
        max_length=50000,
        description="最终确认的大纲 Markdown 内容（用户可能已在前端修改）",
        examples=[
            "# AI眼镜行业深度研究\n"
            "## 1. 行业概述\n"
            "## 2. 市场规模\n"
            "## 3. 竞争格局\n"
            "## 4. 技术趋势\n"
            "## 5. 投资建议\n"
            "## 6. 风险提示\n"
        ],
    )


class OutlineApproveResponse(BaseModel):
    """大纲确认后的响应"""
    project_id: uuid.UUID = Field(..., description="项目 UUID")
    new_status: str = Field(..., description="项目新状态（应为 'drafting'）")
    message: str = Field(..., description="提示消息")
    sections_count: int = Field(..., description="从大纲解析出的章节数量")
    celery_task_id: str | None = Field(None, description="已触发的草稿生成根任务 ID")


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
    outline_content: str | None = Field(None, description="暂存大纲内容（WAITING_OUTLINE_APPROVAL 时有值）")
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
# 文档块 (DocumentBlock) Schemas
# ================================================================

class DocumentBlockResponse(BaseModel):
    """文档块响应——面向 Tiptap 块级编辑器"""
    id: uuid.UUID = Field(..., description="文档块 UUID")
    section_title: str = Field(..., description="归属的章节标题")
    order_index: int = Field(..., description="全局排序序号")
    content: str = Field(..., description="块内容（Markdown）")
    citations: str | None = Field(None, description="引用映射（JSON 格式）")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime | None = Field(None, description="更新时间")

    model_config = ConfigDict(from_attributes=True)


class DocumentBlockListResponse(BaseModel):
    """项目所有文档块列表"""
    project_id: uuid.UUID = Field(..., description="项目 UUID")
    blocks: list[DocumentBlockResponse] = Field(
        default_factory=list,
        description="按 order_index 排序的文档块列表",
    )


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
# SSE (Server-Sent Events) Schemas
# ================================================================

class SSEDraftEvent(BaseModel):
    """
    SSE 草稿流事件负载。
    当后端逐块完成撰写时，通过 SSE 推送给前端，
    前端 Tiptap 编辑器可实时插入/追加内容块。
    """
    event: str = Field(
        ...,
        description="事件类型：section_start | section_chunk | section_complete | draft_complete | error",
    )
    project_id: str = Field(..., description="项目 ID")
    section_title: str | None = Field(None, description="当前处理的章节标题")
    block: DocumentBlockResponse | None = Field(None, description="已完成的文档块")
    error: str | None = Field(None, description="错误信息")


# ================================================================
# 编辑器 (Editor) Schemas
# ================================================================

class EditorReviseRequest(BaseModel):
    """编辑器 AI 改写请求"""
    selected_text: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="用户在编辑器中选中的文本内容",
    )
    instruction: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="改写指令，例如：扩写、精简、润色、正式化等",
        examples=["扩写", "精简", "润色", "使表达更正式"],
    )
    context: str | None = Field(
        None,
        max_length=20000,
        description="可选的上下文信息（如段落前后文），帮助 LLM 理解语境",
    )


class EditorReviseResponse(BaseModel):
    """编辑器 AI 改写响应"""
    revised_text: str = Field(
        ...,
        description="LLM 改写后的文本",
    )


# ================================================================
# 报告内容 (Report Content) Schema
# ================================================================

class ReportContentResponse(BaseModel):
    """报告全文内容响应"""
    project_id: uuid.UUID = Field(..., description="项目 UUID")
    topic: str = Field(..., description="研报主题")
    sections: list[SectionContent] = Field(
        default_factory=list,
        description="按顺序排列的章节内容列表",
    )


class SectionContent(BaseModel):
    """单个章节内容"""
    title: str = Field(..., description="章节标题")
    order: int = Field(..., description="章节顺序")
    content: str = Field(..., description="Markdown 正文")
    citations: dict[str, str] = Field(
        default_factory=dict,
        description="引用映射 {序号: URL}",
    )


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
