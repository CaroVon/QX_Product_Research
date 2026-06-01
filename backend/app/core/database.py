"""
============================================================
异步数据库引擎与会话工厂
使用 SQLAlchemy 2.0 asyncio 扩展
============================================================
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings
from app.models.base import Base  # 复用 models 中的统一 Base

settings = get_settings()

# ─── 异步引擎 ───────────────────────────────────────────────────
engine = create_async_engine(
    settings.DATABASE_URL_ASYNC,
    echo=settings.DEBUG,
    pool_size=10,           # 连接池大小
    max_overflow=20,         # 最大溢出连接数
    pool_pre_ping=True,      # 连接前探活
)

# ─── 异步会话工厂 ───────────────────────────────────────────────
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # 防止 commit 后属性过期
)


async def get_db() -> AsyncSession:
    """FastAPI 依赖注入：获取异步数据库会话"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
