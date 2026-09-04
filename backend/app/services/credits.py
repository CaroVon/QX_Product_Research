"""
============================================================
Credits 服务 —— 三类配额（llm_tokens / image / rainforest）
============================================================

余额=账本聚合（无锁，数十用户规模足够；消耗前余额校验）。
LLM 用量同步：直读 gateway sqlite 的 runs 表（单机部署），按 run 幂等入账。
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.credit_ledger import CREDIT_KINDS, CreditLedger
from app.models.user import User

logger = logging.getLogger(__name__)


async def balance_map(db: AsyncSession, user_id: uuid.UUID) -> dict[str, int]:
    """各类型余额。"""
    rows = await db.execute(
        select(CreditLedger.kind, func.sum(CreditLedger.delta))
        .where(CreditLedger.user_id == user_id)
        .group_by(CreditLedger.kind)
    )
    got = {k: int(v or 0) for k, v in rows.all()}
    return {kind: got.get(kind, 0) for kind in CREDIT_KINDS}


async def record(
    db: AsyncSession, user_id: uuid.UUID, kind: str, delta: int,
    reason: str = "", meta: dict | None = None,
) -> CreditLedger:
    entry = CreditLedger(
        user_id=user_id, kind=kind, delta=delta, reason=reason[:200],
        meta=json.dumps(meta, ensure_ascii=False) if meta else None,
    )
    db.add(entry)
    return entry


def is_admin(user: User) -> bool:
    """QX_ADMIN_EMAILS 命中即管理员（无限额：记账不拦截）。"""
    admins = {a.strip() for a in (get_settings().QX_ADMIN_EMAILS or "").split(",") if a.strip()}
    return (getattr(user, "username", "") or "") in admins


async def consume(
    db: AsyncSession, user: User, kind: str, amount: int,
    reason: str = "", meta: dict | None = None, *, enforce: bool = True,
) -> tuple[bool, int]:
    """消耗额度；enforce 类型余额不足时拒绝（返回 False 与当前余额）。

    管理员（QX_ADMIN_EMAILS）无限额：照常记账、永不拒绝。
    """
    if amount <= 0:
        return True, 0
    balances = await balance_map(db, user.id)
    left = balances.get(kind, 0)
    if is_admin(user):
        enforce = False
    if enforce and left < amount:
        return False, left
    await record(db, user.id, kind, -amount, reason, meta)
    await db.commit()
    return True, left - amount


async def seed_initial_credits(db: AsyncSession, user_id: uuid.UUID) -> None:
    """注册赠送（用户首次映射落库时调用一次）。"""
    settings = get_settings()
    grants = (
        ("llm_tokens", settings.CREDITS_INITIAL_LLM_TOKENS),
        ("image", settings.CREDITS_INITIAL_IMAGES),
        ("rainforest", settings.CREDITS_INITIAL_RAINFOREST),
    )
    for kind, amount in grants:
        if amount > 0:
            await record(db, user_id, kind, amount, "注册赠送")
    await db.commit()
    logger.info("[credits] 注册赠送 | user=%s | %s", user_id, grants)


def _sync_run_ids(entries: list[str]) -> set[str]:
    seen: set[str] = set()
    for raw in entries:
        try:
            rid = (json.loads(raw) or {}).get("run_id")
            if rid:
                seen.add(str(rid))
        except (ValueError, TypeError):
            continue
    return seen


async def sync_llm_usage(db: AsyncSession, *, only_user: User | None = None) -> dict:
    """把 gateway runs 的 token 用量幂等入账（按 run_id 去重）。

    单机部署直读 deerflow sqlite（只读）；email → QX users 映射（缺失则跳过）。
    """
    import sqlite3
    from pathlib import Path

    from sqlalchemy import text as _text

    from app.models.user import User as QxUser

    settings = get_settings()
    db_path = Path(settings.DEERFLOW_DB_PATH)
    if not db_path.is_file():
        return {"error": f"deerflow sqlite 不存在: {db_path}"}

    # 已入账的 run_id
    rows = await db.execute(
        select(CreditLedger.meta).where(CreditLedger.kind == "llm_tokens")
    )
    seen = _sync_run_ids([r[0] for r in rows.all() if r[0]])

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        runs = conn.execute(
            "SELECT r.run_id, r.user_id, r.total_tokens, r.created_at, u.email "
            "FROM runs r JOIN users u ON u.id = r.user_id "
            "WHERE r.total_tokens > 0 ORDER BY r.created_at"
        ).fetchall()
    finally:
        conn.close()

    # email → QX user（一次性载入，数十用户规模）
    qusers = {
        u.username: u
        for u in (await db.execute(select(QxUser))).scalars().all()
    }

    written, skipped = 0, 0
    for run_id, _gw_user, tokens, created_at, email in runs:
        if str(run_id) in seen:
            skipped += 1
            continue
        u = qusers.get(email)
        if u is None:
            skipped += 1
            continue
        if only_user is not None and u.id != only_user.id:
            continue
        await record(
            db, u.id, "llm_tokens", -int(tokens), "LLM 对话（自动同步）",
            {"run_id": str(run_id), "gateway_created_at": created_at},
        )
        written += 1
    await db.commit()
    logger.info("[credits] LLM 同步 | 入账 %d 条 | 跳过 %d 条", written, skipped)
    return {"written": written, "skipped": skipped, "total_runs": len(runs)}
