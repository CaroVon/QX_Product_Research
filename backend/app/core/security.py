"""
============================================================
轻量认证模块（stdlib only，无新依赖）
—— HMAC 签名 token（JWT-like），支持 AUTH_ENABLED 开关
============================================================
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.models import User


# ─── Token 签发 / 校验 ────────────────────────────────────────

def _secret() -> bytes:
    return get_settings().AUTH_SECRET.encode("utf-8")


def create_token(username: str, expires_hours: int | None = None) -> str:
    """签发 HMAC token：base64url(payload).hex(signature)"""
    ttl = expires_hours or get_settings().AUTH_TOKEN_TTL_HOURS
    payload = {
        "u": username,
        "exp": int(time.time()) + ttl * 3600,
    }
    body = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii").rstrip("=")
    sig = hmac.new(_secret(), body.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def verify_token(token: str) -> str | None:
    """校验 token，返回用户名；无效/过期返回 None。"""
    try:
        body, sig = token.rsplit(".", 1)
        expect = hmac.new(_secret(), body.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expect):
            return None
        pad = "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(body + pad))
        if int(payload.get("exp", 0)) < time.time():
            return None
        return str(payload.get("u") or "")
    except Exception:
        return None


# ─── FastAPI 依赖 ─────────────────────────────────────────────

async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """认证依赖（优先级从高到低）：

    1. 服务间认证：X-QX-Service-Key 匹配 + X-QX-User 用户头 —— nginx 在
       auth_request 校验 deer-flow JWT 后注入（浏览器路径），或 qx_tools
       服务调用携带。用户身份以 deer-flow 为唯一源（R4 认证统一）。
    2. Authorization: Bearer <token>（本地签发，遗留/测试路径）。

    AUTH_ENABLED=false 时（本地开发）自动放行演示用户。
    """
    settings = get_settings()
    if not settings.AUTH_ENABLED:
        return await _resolve_user(db, settings.AUTH_ADMIN_USERNAME)

    service_key = request.headers.get("X-QX-Service-Key", "")
    if service_key and settings.QX_SERVICE_KEY and hmac.compare_digest(service_key, settings.QX_SERVICE_KEY):
        user_email = (request.headers.get("X-QX-User") or "").strip()
        if user_email:
            return await _resolve_user(db, user_email)

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供有效的访问令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )
    username = verify_token(auth_header[7:].strip())
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="访问令牌无效或已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await _resolve_user(db, username)


async def _resolve_user(db: AsyncSession, username: str) -> User:
    """按用户名查找用户；不存在则自动创建（单用户工作区模型）。"""
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(id=uuid.uuid4(), username=username)
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return user
