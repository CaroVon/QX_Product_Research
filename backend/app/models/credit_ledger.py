"""
============================================================
CreditLedger ORM 模型 —— 三类配额账本（W3-4 计费底座）
============================================================

kind ∈ llm_tokens / image / rainforest；delta 正数=发放，负数=消耗。
余额 = SUM(delta)。注册赠送在用户首次映射落库时写入（_resolve_user 钩子）。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDType

CREDIT_KINDS = ("llm_tokens", "image", "rainforest")


class CreditLedger(Base):
    """额度账本行（不可变流水，余额由聚合得出）。"""

    __tablename__ = "credit_ledger"
    __table_args__ = (Index("ix_credit_ledger_user_kind", "user_id", "kind"),)

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True,
                                               doc="用户（users.id）")
    kind: Mapped[str] = mapped_column(String(16), nullable=False, doc="llm_tokens/image/rainforest")
    delta: Mapped[int] = mapped_column(BigInteger, nullable=False, doc="正=发放，负=消耗")
    reason: Mapped[str] = mapped_column(String(200), nullable=False, default="", doc="事由")
    meta: Mapped[str | None] = mapped_column(Text, nullable=True, doc="扩展 JSON（run_id/asset_id 等）")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
