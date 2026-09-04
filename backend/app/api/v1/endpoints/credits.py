"""
============================================================
Credits API —— /api/v1/credits（W3-4 计费底座）
============================================================

  GET  /credits/balance         三类余额（当前用户）
  GET  /credits/ledger          账本流水
  GET  /credits/summary         本期用量汇总（账单页）
  POST /credits/consume         消耗（生图/采集工具链调用；image/rainforest 强制余额）
  POST /credits/sync-llm        LLM 用量幂等同步（gateway runs → 账本）
  ── admin ──
  POST /credits/admin/grant     发放/调整额度
  GET  /credits/admin/overview  全员余额总览
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.credit_ledger import CREDIT_KINDS, CreditLedger
from app.models.user import User
from app.services import credits as svc

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/credits", tags=["credits"])


def _is_admin(user: User) -> bool:
    admins = {a.strip() for a in (get_settings().QX_ADMIN_EMAILS or "").split(",") if a.strip()}
    return (user.username or "") in admins


async def _require_admin(user: User) -> None:
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="仅管理员")


@router.get("/balance")
async def get_balance(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return {"user": user.username, "balances": await svc.balance_map(db, user.id)}


@router.get("/ledger")
async def get_ledger(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = (await db.execute(
        select(CreditLedger)
        .where(CreditLedger.user_id == user.id)
        .order_by(CreditLedger.created_at.desc())
        .limit(min(limit, 200))
    )).scalars().all()
    return {
        "entries": [
            {
                "kind": r.kind, "delta": r.delta, "reason": r.reason,
                "meta": json.loads(r.meta) if r.meta else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }


@router.get("/summary")
async def get_summary(
    days: int = 30,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """账单页汇总：本期各类消耗 + 累计消耗 + 当前余额。"""
    since = datetime.now(timezone.utc) - timedelta(days=min(days, 365))
    rows = (await db.execute(
        select(CreditLedger).where(
            CreditLedger.user_id == user.id,
            CreditLedger.created_at >= since,
        )
    )).scalars().all()
    period_used = {k: 0 for k in CREDIT_KINDS}
    for r in rows:
        if r.delta < 0:
            period_used[r.kind] = period_used.get(r.kind, 0) + (-r.delta)
    balances = await svc.balance_map(db, user.id)
    return {
        "user": user.username,
        "period_days": days,
        "period_used": period_used,
        "balances": balances,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


class ConsumeRequest(BaseModel):
    kind: str = Field(..., description="llm_tokens/image/rainforest")
    amount: int = Field(..., gt=0, description="消耗量")
    reason: str = Field(default="", max_length=200)
    meta: dict | None = None
    # llm_tokens 为事后入账（不强拦）；image/rainforest 余额不足返回 402
    enforce: bool | None = None


@router.post("/consume")
async def consume_credits(
    body: ConsumeRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if body.kind not in CREDIT_KINDS:
        raise HTTPException(status_code=422, detail=f"未知额度类型: {body.kind}")
    enforce = body.enforce if body.enforce is not None else body.kind in ("image", "rainforest")
    ok, left = await svc.consume(db, user, body.kind, body.amount, body.reason, body.meta, enforce=enforce)
    if not ok:
        raise HTTPException(
            status_code=402,
            detail=f"{body.kind} 额度不足（剩 {left}）：请联系管理员补充",
        )
    return {"ok": True, "kind": body.kind, "left": left}


@router.post("/sync-llm")
async def sync_llm(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # 非管理员只同步本人 runs；admin 全量
    result = await svc.sync_llm_usage(db, only_user=None if _is_admin(user) else user)
    return {"sync": result, "balances": await svc.balance_map(db, user.id)}


class GrantRequest(BaseModel):
    username: str = Field(..., max_length=255, description="用户名（email）")
    kind: str = Field(..., description="llm_tokens/image/rainforest")
    delta: int = Field(..., description="正=发放，负=扣回")
    reason: str = Field(default="管理员发放", max_length=200)


@router.post("/admin/grant")
async def admin_grant(
    body: GrantRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _require_admin(user)
    if body.kind not in CREDIT_KINDS:
        raise HTTPException(status_code=422, detail=f"未知额度类型: {body.kind}")
    target = (await db.execute(
        select(User).where(User.username == body.username)
    )).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail=f"用户不存在: {body.username}（需先登录过一次以完成映射）")
    await svc.record(db, target.id, body.kind, body.delta, body.reason, {"by": user.username})
    await db.commit()
    return {"user": target.username, "balances": await svc.balance_map(db, target.id)}


@router.get("/admin/overview")
async def admin_overview(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """全员余额总览（admin）。"""
    await _require_admin(user)
    users = (await db.execute(select(User))).scalars().all()
    out = []
    for u in users:
        b = await svc.balance_map(db, u.id)
        if any(v != 0 for v in b.values()) or u.username == user.username:
            out.append({"username": u.username, "balances": b})
    return {"users": out}
