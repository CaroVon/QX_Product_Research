"""
============================================================
FastAPI 应用入口工厂
—— 生产就绪的应用实例构建
============================================================
"""

from __future__ import annotations

import os
import sys
import asyncio
import logging
from pathlib import Path
from contextlib import asynccontextmanager

# ─── Windows asyncio 兼容性修复 ─────────────────────────────────
if sys.platform == "win32":
    try:
        from asyncio import WindowsSelectorEventLoopPolicy
        asyncio.set_event_loop_policy(WindowsSelectorEventLoopPolicy())
    except ImportError:
        pass

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.core.database import engine
from app.models import Base
from app.api.v1.router import router as v1_router

# ─── 日志配置 ─────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


# ================================================================
# 生命周期管理
# ================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期钩子：
    - 启动时：创建数据库表（生产环境应使用 Alembic 迁移）
    - 关闭时：关闭数据库引擎
    """
    settings = get_settings()

    # ─── 启动 ──────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("  %s v%s 启动中...", settings.APP_NAME, settings.APP_VERSION)
    logger.info("  Debug 模式: %s", settings.DEBUG)
    logger.info("=" * 60)

    # 创建输出目录（如果不存在）
    os.makedirs(settings.OUTPUT_DIR, exist_ok=True)

    # TODO: 生产环境应使用 Alembic 迁移，而非自动建表
    # 此处仅为开发/演示方便
    async with engine.begin() as conn:
        # 仅在 DEBUG 模式下自动创建表（避免生产环境误操作）
        if settings.DEBUG:
            await conn.run_sync(Base.metadata.create_all)
            logger.info("[DB] 数据库表已自动创建（DEBUG 模式）")

    yield  # 应用运行中...

    # ─── 关闭 ──────────────────────────────────────────────────
    await engine.dispose()
    logger.info("[APP] 数据库连接已关闭，应用退出")


# ================================================================
# 应用工厂
# ================================================================

def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="AI 产品分析 Agent —— 高并发异步 API 服务\n\n"
        "支持异步任务队列、混合检索增强生成（RAG）、多模态生图、PDF 渲染",
        lifespan=lifespan,
        docs_url="/docs",          # Swagger UI
        redoc_url="/redoc",        # ReDoc
    )

    # ─── CORS 中间件 ──────────────────────────────────────────
    # 允许前端跨域访问
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # TODO: 生产环境限制具体域名
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ─── 注册路由 ──────────────────────────────────────────────
    app.include_router(v1_router)

    # ─── 静态文件服务 ──────────────────────────────────────────
    # 提供输出文件（PDF/Markdown/图片）的 HTTP 访问
    # 文件位于 /app/outputs 目录，通过 /api/v1/files/{path} 访问
    outputs_path = Path(settings.OUTPUT_DIR)
    outputs_path.mkdir(parents=True, exist_ok=True)
    app.mount("/api/v1/files", StaticFiles(directory=str(outputs_path)), name="files")

    # ─── 全局异常处理 ──────────────────────────────────────────
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error("未捕获的全局异常: %s | URL: %s", str(exc), request.url, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"detail": f"服务器内部错误: {str(exc)}", "error_code": "INTERNAL_ERROR"},
        )

    # ─── 根路径 —— 前端仪表板 ──────────────────────────────────
    STATIC_DIR = Path(__file__).parent / "static"

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def index():
        """返回前端仪表板首页"""
        index_path = STATIC_DIR / "index.html"
        if index_path.exists():
            return HTMLResponse(content=index_path.read_text(encoding="utf-8"))
        return HTMLResponse(content="<h1>Research Agent API</h1><p>前端页面未找到，请访问 <a href='/docs'>Swagger 文档</a></p>")

    # ─── 健康检查 ──────────────────────────────────────────────
    @app.get("/health")
    async def health_check():
        return {
            "status": "ok",
            "app": settings.APP_NAME,
            "version": settings.APP_VERSION,
        }

    logger.info("[APP] FastAPI 应用初始化完成")
    return app


# ─── 应用实例（用于 uvicorn 直接启动） ──────────────────────
app = create_app()
