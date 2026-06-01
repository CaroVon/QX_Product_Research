"""
============================================================
大纲生成 & 章节撰写任务
—— 封装原有的 app/planner/outline_generator.py 和 app/report/section_writer.py
============================================================
"""

from __future__ import annotations

import os
import re
import json
import logging
from typing import Any

from celery import Task

from app.core.celery_app import celery_app
from app.core.config import get_settings
from app.core.celery_db import update_task_status_sync, save_document_sync

from app.models.task import TaskType, TaskStatus

logger = logging.getLogger(__name__)


class WritingTask(Task):
    _settings = None

    @property
    def settings(self):
        if self._settings is None:
            self._settings = get_settings()
        return self._settings


@celery_app.task(
    bind=True,
    base=WritingTask,
    name="writing.generate_outline",
    max_retries=2,
    default_retry_delay=10,
    acks_late=True,
)
def generate_outline_task(self: WritingTask, project_id: str) -> str:
    """
    第3步：生成分析报告大纲
    —— 封装原有的 outline_generator.py

    返回 6 大固定章节的 Markdown 大纲文本。
    """
    logger.info("[TASK] 生成大纲 | project_id=%s", project_id)

    # 从数据库获取 topic
    import uuid as _uuid
    from sqlalchemy import text
    from app.core.celery_db import get_sync_engine

    # SQLite 中 UUID 存储为无连字符的 32 位 hex 格式
    project_id_hex = _uuid.UUID(project_id).hex

    settings = self.settings
    engine = get_sync_engine()

    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT topic FROM projects WHERE id = :pid"),
            {"pid": project_id_hex},
        )
        row = result.fetchone()
        if row is None:
            raise ValueError(f"项目不存在: {project_id}")
        topic = row[0]

    # ─── 调用原有的大纲生成逻辑 ──────────────────────────────
    # 注：原有的 outline_generator 返回固定 6 大章节
    # 此处也可以根据需要改为调用 LLM 动态生成
    from app.planner.outline_generator import generate_outline

    outline = generate_outline(topic)
    logger.info("[TASK] 大纲生成完成 | project=%s", project_id)

    return outline


@celery_app.task(
    bind=True,
    base=WritingTask,
    name="writing.write_section",
    max_retries=3,
    default_retry_delay=15,
    acks_late=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=120,
)
def write_single_section(
    self: WritingTask,
    project_id: str,
    section_title: str,
    section_order: int = 0,
) -> str:
    """
    第4步（子步骤）：撰写单个章节
    —— 封装原有的 section_writer.py

    包含:
    - 混合检索 (BM25 + 向量检索 + Source Ranking)
    - LLM 调用撰写
    - 溯源角标解析
    - 多模态生图（当章节名包含"生图/图鉴/概念图"时）

    参数:
        project_id: 项目 UUID
        section_title: 章节标题（如 "1. 产品设计理念"）
        section_order: 章节顺序

    返回:
        Markdown 格式的章节完整内容
    """
    logger.info("[TASK] 撰写章节 | project=%s | section=%s", project_id, section_title)

    settings = self.settings

    # ─── 1. 设置环境变量（LLM API Key 等） ────────────────────
    os.environ["DEEPSEEK_API_KEY"] = settings.DEEPSEEK_API_KEY
    os.environ["DEEPSEEK_BASE_URL"] = settings.DEEPSEEK_BASE_URL

    # ─── 2. 从数据库获取 topic ────────────────────────────────
    import uuid as _uuid
    from sqlalchemy import text
    from app.core.celery_db import get_sync_engine

    # SQLite 中 UUID 存储为无连字符的 32 位 hex 格式
    project_id_hex = _uuid.UUID(project_id).hex

    engine = get_sync_engine()

    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT topic FROM projects WHERE id = :pid"),
            {"pid": project_id_hex},
        )
        row = result.fetchone()
        if row is None:
            raise ValueError(f"项目不存在: {project_id}")
        topic = row[0]

    # ─── 3. 调用原有章节撰写逻辑 ──────────────────────────────
    # 复用原有的 write_section 函数（它内部调用了 LLM + RAG）
    from app.report.section_writer import write_section

    try:
        # 调用原有逻辑（包含 LLM 调用、RAG 检索、引用解析）
        content = write_section(topic, section_title)

        if not content:
            content = f"## {section_title}\n\n[本章节生成内容为空]\n"

        # ─── 4. 保存章节快照到数据库 ──────────────────────────
        # 提取引用 URL
        source_urls = re.findall(r'<([^>]+)>', content) if content else []
        # 保存文档
        save_document_sync(
            project_id=project_id,
            section_title=section_title,
            content=content,
            raw_content=content,
            source_urls=list(set(source_urls)),
            section_order=section_order,
        )

        logger.info("[TASK] 章节撰写完成 | project=%s | section='%s' | len=%d",
                    project_id, section_title, len(content))
        return content

    except Exception as e:
        logger.error("[TASK] 章节撰写失败 | project=%s | section='%s' | error=%s",
                     project_id, section_title, str(e))
        # LLM API 超时等需要重试
        raise self.retry(exc=e)
