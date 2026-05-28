"""
============================================================
报告生成主工作流（根任务）
—— 编排整个研报生成流程，串行执行各个步骤
============================================================
"""

from __future__ import annotations

import os
import re
import json
import logging
import asyncio
from datetime import datetime, timezone

from celery import chain, group, signature
from sqlalchemy import select

from app.core.celery_app import celery_app
from app.core.celery_db import (
    update_task_status,
    update_project_status,
    create_section_tasks,
    get_celery_db,
)
from app.models.task import TaskStatus, TaskType
from app.models.project import ProjectStatus, Project

logger = logging.getLogger(__name__)


def extract_sections(outline: str) -> list[str]:
    """从大纲 Markdown 中提取 ## 章节标题"""
    lines = outline.split("\n")
    sections = []
    for line in lines:
        line = line.strip()
        if line.startswith("##"):
            title = re.sub(r"^##\s*", "", line)
            sections.append(title)
    return sections


@celery_app.task(
    bind=True,
    name="workflow.run_full_report",
    max_retries=1,
    default_retry_delay=30,
    acks_late=True,
)
def run_full_report_workflow(self, project_id: str):
    """
    完整报告生成工作流（入口点）。
    这是一个 Celery 编排任务，依次调用各子任务。

    执行步骤:
    1. search_and_crawl     - 数据采集（Tavily + Firecrawl）
    2. build_knowledge_base - 知识库构建（Chunk + Chroma + BM25）
    3. generate_outline     - 生成大纲，并动态创建章节撰写任务
    4. write_section_*      - 并行/串行撰写各章节
    5. build_report_md      - 组装完整 Markdown 报告
    6. generate_pdf         - 渲染 PDF
    """
    logger.info("=" * 60)
    logger.info("[WORKFLOW] 开始执行完整报告生成 | project_id=%s", project_id)
    logger.info("=" * 60)

    try:
        # ─── 第1步：数据采集 ──────────────────────────────────
        logger.info("[STEP 1/6] 数据采集 (Tavily + Firecrawl)...")
        update_task_status_sync(project_id, TaskType.SEARCH, TaskStatus.PROCESSING)

        try:
            from app.tasks.search_tasks import search_and_crawl
            search_result = search_and_crawl(project_id)
            logger.info("[STEP 1/6] 数据采集完成，共获取 %d 个 URL 内容", len(search_result))
        except Exception as e:
            update_task_status_sync(project_id, TaskType.SEARCH, TaskStatus.FAILED, str(e))
            raise

        update_task_status_sync(project_id, TaskType.SEARCH, TaskStatus.COMPLETED)

        # ─── 保存爬取数据到临时文件（供 build_knowledge_base 读取）──
        import json
        temp_data_path = f"/tmp/crawled_data_{project_id}.json"
        with open(temp_data_path, "w", encoding="utf-8") as f:
            json.dump(search_result, f, ensure_ascii=False)
        logger.info("[WORKFLOW] 爬取数据已保存到临时文件: %s", temp_data_path)

        # ─── 第2步：知识库构建 ────────────────────────────────
        logger.info("[STEP 2/6] 知识库构建 (Chunk + Chroma + BM25)...")
        update_task_status_sync(project_id, TaskType.BUILD_KNOWLEDGE_BASE, TaskStatus.PROCESSING)

        try:
            from app.tasks.knowledge_tasks import build_knowledge_base
            build_knowledge_base(project_id)
        except Exception as e:
            update_task_status_sync(project_id, TaskType.BUILD_KNOWLEDGE_BASE, TaskStatus.FAILED, str(e))
            raise

        update_task_status_sync(project_id, TaskType.BUILD_KNOWLEDGE_BASE, TaskStatus.COMPLETED)

        # ─── 第3步：生成大纲 ──────────────────────────────────
        logger.info("[STEP 3/6] 生成研报大纲...")
        update_task_status_sync(project_id, TaskType.GENERATE_OUTLINE, TaskStatus.PROCESSING)

        try:
            from app.tasks.writing_tasks import generate_outline_task
            outline = generate_outline_task(project_id)
            logger.info("[STEP 3/6] 大纲生成完成")
        except Exception as e:
            update_task_status_sync(project_id, TaskType.GENERATE_OUTLINE, TaskStatus.FAILED, str(e))
            raise

        update_task_status_sync(project_id, TaskType.GENERATE_OUTLINE, TaskStatus.COMPLETED)

        # ─── 动态创建章节撰写任务 ──────────────────────────────
        section_titles = extract_sections(outline)
        # 同步调用创建章节任务（在数据库中插入 Task 记录）
        asyncio.run(create_section_tasks(project_id, section_titles))
        logger.info("[WORKFLOW] 已创建 %d 个章节撰写任务", len(section_titles))

        # ─── 第4步：并行撰写所有章节 ──────────────────────────
        logger.info("[STEP 4/6] 并行撰写各章节...")
        section_results = []
        for idx, section_title in enumerate(section_titles):
            try:
                from app.tasks.writing_tasks import write_single_section
                content = write_single_section(
                    project_id, section_title, idx
                )
                section_results.append(content)
                logger.info("  [OK] 章节 '%s' 撰写完成", section_title)
            except Exception as e:
                logger.error("  [FAIL] 章节 '%s' 撰写失败: %s", section_title, str(e))
                section_results.append(f"## {section_title}\n\n[本章节生成失败: {str(e)}]\n")

        # ─── 第5步：组装 Markdown 报告 ────────────────────────
        logger.info("[STEP 5/6] 组装 Markdown 报告...")
        update_task_status_sync(project_id, TaskType.BUILD_REPORT, TaskStatus.PROCESSING)

        try:
            from app.tasks.render_tasks import build_report_markdown
            md_path = build_report_markdown(project_id, section_results)
        except Exception as e:
            update_task_status_sync(project_id, TaskType.BUILD_REPORT, TaskStatus.FAILED, str(e))
            raise

        update_task_status_sync(project_id, TaskType.BUILD_REPORT, TaskStatus.COMPLETED)

        # ─── 第6步：生成 PDF ──────────────────────────────────
        logger.info("[STEP 6/6] 渲染 PDF...")
        update_task_status_sync(project_id, TaskType.GENERATE_PDF, TaskStatus.PROCESSING)

        try:
            from app.tasks.render_tasks import generate_pdf_report
            pdf_path = generate_pdf_report(project_id, md_path)
        except Exception as e:
            update_task_status_sync(project_id, TaskType.GENERATE_PDF, TaskStatus.FAILED, str(e))
            raise

        update_task_status_sync(project_id, TaskType.GENERATE_PDF, TaskStatus.COMPLETED)

        # ─── 全部完成 ──────────────────────────────────────────
        update_project_status_sync(project_id, ProjectStatus.COMPLETED, pdf_path=pdf_path, md_path=md_path)

        logger.info("=" * 60)
        logger.info("[WORKFLOW] ✅ 报告生成全部完成 | project_id=%s", project_id)
        logger.info("[WORKFLOW] PDF 路径: %s", pdf_path)
        logger.info("=" * 60)

        return {
            "project_id": project_id,
            "status": "completed",
            "md_path": md_path,
            "pdf_path": pdf_path,
        }

    except Exception as exc:
        logger.error("[WORKFLOW] ❌ 报告生成失败 | project_id=%s | error=%s", project_id, str(exc), exc_info=True)
        update_project_status_sync(project_id, ProjectStatus.FAILED, error_message=str(exc))

        # 触发重试
        try:
            self.retry(exc=exc)
        except Exception as retry_exc:
            logger.error("[WORKFLOW] 重试也失败: %s", str(retry_exc))
            raise

        return {
            "project_id": project_id,
            "status": "failed",
            "error": str(exc),
        }


# ================================================================
# 同步包装器（Celery Task 中需要同步调用异步数据库操作）
# ================================================================

def update_task_status_sync(project_id: str, task_type: TaskType, status: TaskStatus, error: str | None = None):
    """同步包装：更新任务状态"""
    asyncio.run(update_task_status(project_id, task_type, status, error))


def update_project_status_sync(project_id: str, status: ProjectStatus, error_message: str | None = None, pdf_path: str | None = None, md_path: str | None = None):
    """同步包装：更新项目状态"""
    asyncio.run(update_project_status(project_id, status, error_message, pdf_path, md_path))
