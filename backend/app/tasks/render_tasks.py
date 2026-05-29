"""
============================================================
报告组装 & PDF 渲染任务
—— 封装原有的 markdown_formatter.py 和 pdf_generator.py
============================================================
"""

from __future__ import annotations

import os
import re
import logging
from datetime import datetime

from celery import Task

from app.core.celery_app import celery_app
from app.core.config import get_settings

logger = logging.getLogger(__name__)


class RenderTask(Task):
    _settings = None

    @property
    def settings(self):
        if self._settings is None:
            self._settings = get_settings()
        return self._settings


@celery_app.task(
    bind=True,
    base=RenderTask,
    name="render.build_report_markdown",
    max_retries=2,
    default_retry_delay=10,
    acks_late=True,
)
def build_report_markdown(
    self: RenderTask,
    project_id: str,
    section_contents: list[str],
) -> str:
    """
    第5步：组装完整 Markdown 报告

    参数:
        project_id: 项目 UUID
        section_contents: 各章节内容的列表（按顺序）

    返回:
        md_path: 生成的 Markdown 文件相对路径
    """
    logger.info("[TASK] 组装 Markdown 报告 | project_id=%s", project_id)
    settings = self.settings

    # ─── 1. 从数据库获取 topic ────────────────────────────────
    import uuid as _uuid
    from sqlalchemy import create_engine, text

    # SQLite 中 UUID 存储为无连字符的 32 位 hex 格式
    project_id_hex = _uuid.UUID(project_id).hex

    engine = create_engine(settings.DATABASE_URL_SYNC)

    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT topic FROM projects WHERE id = :pid"),
            {"pid": project_id_hex},
        )
        row = result.fetchone()
        if row is None:
            raise ValueError(f"项目不存在: {project_id}")
        topic = row[0]

    # ─── 2. 组装完整的 Markdown ───────────────────────────────
    report = f"# {topic}\n\n"
    for section in section_contents:
        report += section + "\n\n"

    # ─── 3. 写入文件 ──────────────────────────────────────────
    # 输出目录
    output_dir = settings.OUTPUT_DIR
    os.makedirs(output_dir, exist_ok=True)

    # 文件名：topic_日期时间.md
    safe_topic = re.sub(r'[\\/:*?"<>|]', '_', topic)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{safe_topic}_report_{timestamp}.md"
    relative_path = filename  # 相对 OUTPUT_DIR 的路径
    full_path = os.path.join(output_dir, filename)

    with open(full_path, "w", encoding="utf-8") as f:
        f.write(report)

    logger.info("[TASK] Markdown 报告已保存 | path=%s | size=%d",
                full_path, len(report))

    # ─── 4. 更新数据库中的 md_path ────────────────────────────
    from app.core.celery_db import update_project_status_sync
    update_project_status_sync(project_id, None, md_path=relative_path)

    return relative_path


@celery_app.task(
    bind=True,
    base=RenderTask,
    name="render.generate_pdf",
    max_retries=2,
    default_retry_delay=15,
    acks_late=True,
)
def generate_pdf_report(
    self: RenderTask,
    project_id: str,
    md_relative_path: str,
) -> str:
    """
    第6步：将 Markdown 渲染为精美 PDF

    参数:
        project_id: 项目 UUID
        md_relative_path: Markdown 文件相对路径（相对于 OUTPUT_DIR）

    返回:
        pdf_path: 生成的 PDF 文件相对路径
    """
    logger.info("[TASK] 渲染 PDF | project_id=%s | md=%s", project_id, md_relative_path)
    settings = self.settings

    output_dir = settings.OUTPUT_DIR
    md_full_path = os.path.join(output_dir, md_relative_path)

    if not os.path.exists(md_full_path):
        raise FileNotFoundError(f"Markdown 文件未找到: {md_full_path}")

    # ─── 生成 PDF 文件名 ─────────────────────────────────────
    pdf_filename = md_relative_path.replace(".md", ".pdf")
    pdf_full_path = os.path.join(output_dir, pdf_filename)

    # ─── 调用 PDF 生成器 ─────────────────────────────────────
    from app.report.pdf_generator import markdown_to_pdf

    try:
        markdown_to_pdf(md_full_path, pdf_full_path)
        logger.info("[TASK] PDF 渲染完成 | path=%s", pdf_full_path)
    except Exception as e:
        logger.error("[TASK] PDF 渲染失败: %s", str(e))
        raise

    # ─── 验证文件是否生成成功 ─────────────────────────────────
    if not os.path.exists(pdf_full_path):
        raise RuntimeError(f"PDF 文件未生成: {pdf_full_path}")

    file_size = os.path.getsize(pdf_full_path)
    logger.info("[TASK] PDF 文件已确认 | path=%s | size=%d bytes", pdf_full_path, file_size)

    # ─── 更新数据库中的 pdf_path ─────────────────────────────
    from app.core.celery_db import update_project_status_sync
    update_project_status_sync(project_id, None, pdf_path=pdf_filename)

    return pdf_filename
