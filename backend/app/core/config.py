"""
============================================================
企业级应用核心配置 —— 基于 Pydantic V2 Settings
支持环境变量覆盖，便于 Docker 部署
============================================================
"""

from __future__ import annotations

import os
from pathlib import Path
from functools import lru_cache

from pydantic_settings import BaseSettings
from pydantic import Field, PostgresDsn, RedisDsn


class Settings(BaseSettings):
    # ─── 应用基础 ────────────────────────────────────────────────
    APP_NAME: str = "Research Agent API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = Field(default=False)

    # ─── 数据库 ──────────────────────────────────────────────────
    # 优先级：DATABASE_URL（环境变量）> 自动拼接 PostgreSQL
    # 本地开发推荐设置 DATABASE_URL=sqlite+aiosqlite:///./local_dev.db
    DATABASE_URL: str | None = Field(default=None)

    # PostgreSQL 参数（仅在 DATABASE_URL 未设置时生效）
    POSTGRES_USER: str = Field(default="postgres")
    POSTGRES_PASSWORD: str = Field(default="postgres")
    POSTGRES_HOST: str = Field(default="postgres")
    POSTGRES_PORT: int = Field(default=5432)
    POSTGRES_DB: str = Field(default="research_agent")

    @property
    def DATABASE_URL_ASYNC(self) -> str:
        """异步 SQLAlchemy 连接串（用于 FastAPI）"""
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def DATABASE_URL_SYNC(self) -> str:
        """同步 SQLAlchemy 连接串（用于 Alembic 迁移）"""
        if self.DATABASE_URL:
            # 将异步驱动名替换为同步驱动名
            return self.DATABASE_URL.replace("+aiosqlite", "").replace("+asyncpg", "")
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    # ─── Redis ──────────────────────────────────────────────────
    REDIS_HOST: str = Field(default="redis")
    REDIS_PORT: int = Field(default=6379)
    REDIS_DB: int = Field(default=0)

    @property
    def REDIS_URL(self) -> str:
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    # ─── Celery ─────────────────────────────────────────────────
    CELERY_BROKER_URL: str = Field(default="redis://redis:6379/1")
    CELERY_RESULT_BACKEND: str = Field(default="redis://redis:6379/2")

    # ─── 文件存储 ────────────────────────────────────────────────
    # 报告输出目录（本地开发用 ./outputs）
    OUTPUT_DIR: str = Field(default="./outputs")
    # PDF 文件对外提供下载的 Base URL
    PDF_DOWNLOAD_BASE_URL: str = Field(default="/api/v1/files")

    # ─── 外部 API Key（优先从 .env 读取） ────────────────────────
    TAVILY_API_KEY: str = Field(default="")
    FIRECRAWL_API_KEY: str = Field(default="")
    DEEPSEEK_API_KEY: str = Field(default="")
    DEEPSEEK_BASE_URL: str = Field(default="https://api.deepseek.com/v1")
    DEEPSEEK_MODEL: str = Field(default="deepseek-chat")

    # ─── 多租户（向量库隔离） ────────────────────────────────────
    # 未来：当引入多租户时，每个 tenant 拥有独立的 Chroma 持久化路径
    # CHROMA_PERSIST_DIR_TEMPLATE: str = "/app/chroma_db/{tenant_id}"
    # BM25_PERSIST_DIR_TEMPLATE: str = "/app/bm25_db/{tenant_id}"
    CHROMA_PERSIST_DIR: str = Field(default="./chroma_db")
    BM25_PERSIST_DIR: str = Field(default="./bm25_db")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache()
def get_settings() -> Settings:
    """全局单例获取配置"""
    return Settings()

settings = Settings()

