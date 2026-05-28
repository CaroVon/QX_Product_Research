"""
============================================================
知识库构建任务
—— 封装原有的 app/rag/vector_store.py 和 chunker 逻辑
============================================================
"""

from __future__ import annotations

import os
import json
import logging
from typing import Any

from celery import Task

from app.core.celery_app import celery_app
from app.core.config import get_settings

logger = logging.getLogger(__name__)


class KnowledgeTask(Task):
    _settings = None

    @property
    def settings(self):
        if self._settings is None:
            self._settings = get_settings()
        return self._settings


@celery_app.task(
    bind=True,
    base=KnowledgeTask,
    name="knowledge.build_knowledge_base",
    max_retries=2,
    default_retry_delay=15,
    acks_late=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def build_knowledge_base(self: KnowledgeTask, project_id: str) -> dict[str, Any]:
    """
    第2步：知识库构建
    —— 将爬取的文本切片后存入 Chroma 向量库和 BM25 持久化文件

    未来多租户扩展：
    当引入多租户时，此处需要根据 project 的 tenant_id
    切换不同的 CHROMA_PERSIST_DIR / BM25_PERSIST_DIR
    例如: /app/chroma_db/{tenant_id}/{project_id}
    """
    logger.info("[TASK] 开始构建知识库 | project_id=%s", project_id)

    settings = self.settings

    # ─── 1. 从数据库获取爬取数据快照 ──────────────────────────
    # 目前方案：search_and_crawl 任务的返回值通过链式调用传递
    # 注意：Celery 链式调用任务之间通过返回值和参数传递数据
    # 这里我们直接从 storage 获取，或者通过任务签名传递
    # 简化方案：重新调用搜索任务（或从文件读取）
    #
    # TODO: 生产环境建议将 crawled_data 存入 Redis 或 Task 结果中
    # 这里演示标准流程，实际部署时由 workflow 编排传入数据

    # ─── 2. 文本切片 ──────────────────────────────────────────
    from app.rag.chunker import chunk_text
    from app.rag.vector_store import build_vector_store

    # 由于 Celery 链式调用中无法直接传递大量数据（受 Broker 限制），
    # 我们采用"先存后读"策略：search_and_crawl 将结果保存到文件/Redis，
    # 此处再读取。
    #
    # 演示简化：使用项目级临时文件传递数据
    # 实际项目建议使用 Redis 或 S3
    temp_data_path = f"/tmp/crawled_data_{project_id}.json"

    if os.path.exists(temp_data_path):
        with open(temp_data_path, "r", encoding="utf-8") as f:
            crawled_data = json.load(f)
    else:
        # 如果找不到临时文件，说明 search_and_crawl 可能未执行
        # 从结果后端获取（Celery 链式调用时可用）
        logger.warning("[TASK] 未找到临时数据文件，尝试从上游任务结果获取")
        # 这里简化处理：如果 workflow 正确传参，不会走到这里
        raise FileNotFoundError(f"临时数据文件不存在: {temp_data_path}")

    # ─── 3. 执行切片 ──────────────────────────────────────────
    all_chunks_with_meta = []
    for item in crawled_data:
        content = item.get("content", "")
        url = item.get("url", "unknown")

        if not content:
            continue

        chunks = chunk_text(content)
        for chunk in chunks:
            all_chunks_with_meta.append({
                "content": chunk,
                "url": url,
            })

        logger.info("[TASK] 切片完成: %s -> %d chunks", url, len(chunks))

    logger.info("[TASK] 共 %d 个切片，开始构建向量库", len(all_chunks_with_meta))

    # ─── 4. 构建向量库 + BM25 ─────────────────────────────────
    # 未来多租户：此处根据 tenant_id 切换目录
    # chroma_dir = settings.CHROMA_PERSIST_DIR_TEMPLATE.format(tenant_id=tenant_id)
    # bm25_dir = settings.BM25_PERSIST_DIR_TEMPLATE.format(tenant_id=tenant_id)

    # 保存原始 CWD，防止毒害其他 Celery 工作进程的数据库连接
    _orig_cwd = os.getcwd()
    os.chdir("/app")  # 确保工作目录正确（与原有脚本兼容）
    try:
        build_vector_store(all_chunks_with_meta)
    finally:
        os.chdir(_orig_cwd)  # 恢复 CWD，避免影响后续任务

    # ─── 5. 清理临时文件 ──────────────────────────────────────
    try:
        os.remove(temp_data_path)
    except OSError:
        pass

    logger.info("[TASK] 知识库构建完成 | project=%s | total_chunks=%d",
                project_id, len(all_chunks_with_meta))

    return {
        "project_id": project_id,
        "total_chunks": len(all_chunks_with_meta),
        "status": "completed",
    }
