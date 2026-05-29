"""
============================================================
搜索与数据采集任务
—— 封装原有的 Tavily 搜索 + Firecrawl 爬取逻辑
============================================================
"""

from __future__ import annotations

import os
import logging
from typing import Any

from celery import Task

from app.core.celery_app import celery_app
from app.core.config import get_settings

logger = logging.getLogger(__name__)


class SearchTask(Task):
    """搜索任务基类 —— 自动注入配置"""
    _settings = None

    @property
    def settings(self):
        if self._settings is None:
            self._settings = get_settings()
        return self._settings


@celery_app.task(
    bind=True,
    base=SearchTask,
    name="search.search_and_crawl",
    max_retries=3,
    default_retry_delay=10,
    acks_late=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
)
def search_and_crawl(self: SearchTask, project_id: str) -> list[dict[str, Any]]:
    """
    第1步：搜索 + 爬取数据
    —— 将原有 app/search/tavily_search.py + app/crawler/firecrawl_crawler.py 的逻辑封装至此

    执行流程:
    1. 从数据库读取 project 的 topic
    2. 调用 Tavily API 搜索
    3. 对前 N 个结果调用 Firecrawl 爬取
    4. 返回 [{content, url}, ...] 格式的数据列表
    """
    logger.info("[TASK] 开始数据采集 | project_id=%s", project_id)

    # ─── 1. 从数据库获取主题 ──────────────────────────────────
    import uuid as _uuid
    from sqlalchemy import create_engine
    from app.models.project import Project

    # SQLite 中 UUID 存储为无连字符的 32 位 hex 格式
    project_id_hex = _uuid.UUID(project_id).hex

    settings = self.settings
    sync_engine = create_engine(settings.DATABASE_URL_SYNC)

    with sync_engine.connect() as conn:
        from sqlalchemy import text
        result = conn.execute(
            text("SELECT topic FROM projects WHERE id = :pid"),
            {"pid": project_id_hex},
        )
        row = result.fetchone()
        if row is None:
            raise ValueError(f"项目不存在: {project_id}")
        topic = row[0]

    logger.info("[TASK] 研究主题: %s", topic)

    # ─── 2. Tavily 搜索 ────────────────────────────────────────
    try:
        from app.search.tavily_search import tavily_search

        # 设置 API Key
        os.environ["TAVILY_API_KEY"] = settings.TAVILY_API_KEY

        search_results = tavily_search(topic, max_results=5)
        results = search_results.get("results", [])
        logger.info("[TASK] Tavily 搜索完成，返回 %d 条结果", len(results))
    except Exception as e:
        logger.error("[TASK] Tavily 搜索失败: %s", str(e))
        # 搜索失败时应重试
        raise self.retry(exc=e)

    # ─── 3. Firecrawl 爬取前 3 个 URL ─────────────────────────
    from app.crawler.firecrawl_crawler import crawl_url

    os.environ["FIRECRAWL_API_KEY"] = settings.FIRECRAWL_API_KEY

    crawled_data = []
    for item in results[:3]:
        url = item.get("url", "")
        if not url:
            continue

        logger.info("[TASK] 正在爬取: %s", url)
        try:
            crawl_result = crawl_url(url)
            markdown = ""
            # 兼容 Firecrawl 返回的不同格式
            if hasattr(crawl_result, "markdown"):
                markdown = getattr(crawl_result, "markdown", "")
            elif isinstance(crawl_result, dict):
                markdown = crawl_result.get("markdown", crawl_result.get("content", ""))

            if markdown:
                crawled_data.append({
                    "content": markdown,
                    "url": url,
                })
                logger.info("[TASK] 爬取成功: %s (%d chars)", url, len(markdown))
            else:
                logger.warning("[TASK] 爬取内容为空: %s", url)

        except Exception as e:
            logger.warning("[TASK] 爬取失败 %s: %s", url, str(e))
            # 单个 URL 爬取失败不中断流程，继续处理下一个
            continue

    logger.info("[TASK] 数据采集完成 | project=%s | chunks=%d", project_id, len(crawled_data))
    return crawled_data
