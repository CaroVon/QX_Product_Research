"""
============================================================
Celery 应用实例
—— 异步任务队列的核心配置
============================================================
"""

from __future__ import annotations

from celery import Celery

from app.core.config import get_settings

settings = get_settings()

# ─── Broker 地址 ──────────────────────────────────────────────
# 当没有 Redis 可用时，使用内存传输（仅适用于本地开发/测试）
# 生产环境请确保设置了 CELERY_BROKER_URL
_broker_url = settings.CELERY_BROKER_URL
_backend_url = settings.CELERY_RESULT_BACKEND
if not _broker_url:
    _broker_url = "memory://"
    _backend_url = "cache+memory://"

# ─── 创建 Celery 应用 ─────────────────────────────────────────
celery_app = Celery(
    "research_agent",
    broker=_broker_url,
    backend=_backend_url,
    include=[
        "app.tasks.report_workflow",   # 主工作流任务
        "app.tasks.search_tasks",       # 搜索采集任务
        "app.tasks.knowledge_tasks",    # 知识库构建任务
        "app.tasks.writing_tasks",      # 章节撰写任务
        "app.tasks.render_tasks",       # PDF 渲染任务
    ],
)

# ─── Celery 配置 ──────────────────────────────────────────────
celery_app.conf.update(
    # 任务序列化
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    # 任务结果保存时间（秒）
    result_expires=60 * 60 * 24,  # 24 小时后过期
    # 每个 Worker 最多预取 1 个任务（保证公平调度，防止大任务阻塞队列）
    worker_prefetch_multiplier=1,
    # 任务软超时时间（秒），超时后触发 SoftTimeLimitExceeded
    task_soft_time_limit=60 * 30,  # 30 分钟
    # 任务硬超时时间（秒），超时后 Worker 杀掉进程
    task_time_limit=60 * 45,  # 45 分钟
    # 任务重试策略
    task_acks_late=True,  # 任务完成后才确认，确保至少执行一次
    task_reject_on_worker_lost=True,  # Worker 丢失时拒绝任务以便重试
    # 默认重试策略
    task_default_retry_delay=10,  # 首次重试延迟 10 秒
    task_max_retries=3,  # 最多重试 3 次
)
