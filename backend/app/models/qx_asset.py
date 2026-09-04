"""
============================================================
QxAsset ORM 模型 —— QX Studio 独立资产库
============================================================

统一承载不由 QX 流水线直接产出的资产（独立生图 / 关键词资产 / 手动上传），
可选挂到 studio_products（project_id）实现「独立存放、可联动」。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDType


class QxAsset(Base):
    """独立资产（image / keywords / document）。"""

    __tablename__ = "qx_assets"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    # image=生图产物；keywords=关键词资产；document=手动上传文档
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="image", index=True,
                                      doc="资产类型：image/keywords/document")
    # agent=agent 工具产出；manual=用户手动上传
    origin: Mapped[str] = mapped_column(String(16), nullable=False, default="agent",
                                        doc="来源：agent/manual")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True,
                                        doc="生成状态：pending/running/done/failed")
    name: Mapped[str] = mapped_column(String(200), nullable=False, default="", doc="展示名")
    # 生图提示词（image）或关键词组摘要（keywords）
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True, doc="提示词/摘要")
    # 相对 QX_OUTPUT_DIR 的文件路径；经 /api/v1/files/{file_rel} 提供
    file_rel: Mapped[str | None] = mapped_column(String(500), nullable=True, doc="文件相对路径")
    meta: Mapped[str | None] = mapped_column(Text, nullable=True,
                                             doc="扩展元数据 JSON（item_id/引用关系等）")
    # 可选挂载到 QX 任务（studio_products.id）；NULL=独立存放
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, nullable=True, index=True,
                                                         doc="可选关联的 QX 任务 ID")
    # 归属用户（users.id；NULL=旧数据，列表对所有人可见——与 studio_products 同语义）
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, nullable=True, index=True,
                                                       doc="归属用户")
    # 发起的聊天会话（deer-flow thread_id；NULL=历史/非会话来源）
    thread_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True,
                                                  doc="发起会话 ID")
    error: Mapped[str | None] = mapped_column(Text, nullable=True, doc="失败原因")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now(),
                                                        nullable=True)
