"""
============================================================
报告生成工作流（拆分为两个独立节点）
—— 🎯 状态机驱动：从线性流水线 → 交互式多步 Agent

节点1: prepare_data_workflow（自动执行，无需用户干预）
  搜索 → 知识库 → 大纲生成 → 等待用户确认

节点2: run_draft_sections_workflow（用户确认大纲后触发）
  分章节撰写 → 组装报告 → PDF渲染

状态机映射：
  PREPARING_DATA                        ← 节点1 开始
    → WAITING_OUTLINE_APPROVAL          ← 节点1 完成（📌 交互节点）
      → DRAFTING                        ← 节点2 开始（用户点击"确认大纲"后）
        → COMPLETED                     ← 节点2 完成
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
    update_project_outline,
    save_document_block,
    create_section_tasks,
    get_celery_db,
)
from app.models.task import TaskStatus, TaskType
from app.models.project import ProjectStatus, Project

logger = logging.getLogger(__name__)


# ================================================================
# 辅助函数
# ================================================================

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


def log_state(project_id: str, step: str, msg: str):
    """状态机日志打印——产品化关键标志"""
    logger.info("🔷 [STATE] project=%s | step=%s | %s", project_id, step, msg)


# ================================================================
# 同步包装器（Celery Task 中需要同步调用异步数据库操作）
# ================================================================

def update_task_status_sync(project_id: str, task_type: TaskType, status: TaskStatus, error: str | None = None):
    """同步包装：更新任务状态"""
    asyncio.run(update_task_status(project_id, task_type, status, error))


def update_project_status_sync(project_id: str, status: ProjectStatus, error_message: str | None = None, pdf_path: str | None = None, md_path: str | None = None):
    """同步包装：更新项目状态"""
    asyncio.run(update_project_status(project_id, status, error_message, pdf_path, md_path))


def update_project_outline_sync(project_id: str, outline_content: str):
    """同步包装：保存大纲"""
    asyncio.run(update_project_outline(project_id, outline_content))


# ================================================================
# 🎯 节点1：资料准备与大纲生成（自动 → 等待用户确认）
# ================================================================

@celery_app.task(
    bind=True,
    name="workflow.prepare_data",
    max_retries=1,
    default_retry_delay=30,
    acks_late=True,
)
def prepare_data_workflow(self, project_id: str):
    """
    🎯 节点1：资料准备与大纲生成
    ==============================
    状态机：PREPARING_DATA → (自动) → WAITING_OUTLINE_APPROVAL

    本节点完全自动执行，依次完成：
    1. 数据采集（Tavily + Firecrawl）
    2. 知识库构建（Chunk + Chroma + BM25）
    3. 生成研报大纲（大纲内容暂存到数据库）

    完成后将 Project.status 更新为 WAITING_OUTLINE_APPROVAL，
    同时将生成的大纲保存到 project.outline_content 字段，
    前端读取后渲染到 Tiptap 编辑器中供用户审阅/修改。

    用户确认后通过 POST /approve-outline 触发节点2。
    """
    logger.info("=" * 60)
    logger.info("[NODE 1] 🚀 资料准备与大纲生成 | project_id=%s", project_id)
    logger.info("[NODE 1] 状态: PREPARING_DATA → WAITING_OUTLINE_APPROVAL")
    logger.info("=" * 60)

    try:
        # ─── 状态机日志 ──────────────────────────────────────
        log_state(project_id, "preparing_data", "节点1 开始执行")

        # ─── 第1步：数据采集 ──────────────────────────────────
        logger.info("[STEP 1/3] 数据采集 (Tavily + Firecrawl)...")
        update_task_status_sync(project_id, TaskType.SEARCH, TaskStatus.PROCESSING)

        try:
            from app.tasks.search_tasks import search_and_crawl
            search_result = search_and_crawl(project_id)
            logger.info("[STEP 1/3] 数据采集完成，共获取 %d 个 URL 内容", len(search_result))
        except Exception as e:
            update_task_status_sync(project_id, TaskType.SEARCH, TaskStatus.FAILED, str(e))
            raise

        update_task_status_sync(project_id, TaskType.SEARCH, TaskStatus.COMPLETED)

        # 保存爬取数据到临时文件（供 build_knowledge_base 读取）
        temp_data_path = f"/tmp/crawled_data_{project_id}.json"
        with open(temp_data_path, "w", encoding="utf-8") as f:
            json.dump(search_result, f, ensure_ascii=False)

        # ─── 第2步：知识库构建 ────────────────────────────────
        logger.info("[STEP 2/3] 知识库构建 (Chunk + Chroma + BM25)...")
        update_task_status_sync(project_id, TaskType.BUILD_KNOWLEDGE_BASE, TaskStatus.PROCESSING)

        try:
            from app.tasks.knowledge_tasks import build_knowledge_base
            build_knowledge_base(project_id)
        except Exception as e:
            update_task_status_sync(project_id, TaskType.BUILD_KNOWLEDGE_BASE, TaskStatus.FAILED, str(e))
            raise

        update_task_status_sync(project_id, TaskType.BUILD_KNOWLEDGE_BASE, TaskStatus.COMPLETED)

        # ─── 第3步：生成大纲 ──────────────────────────────────
        logger.info("[STEP 3/3] 生成研报大纲...")
        update_task_status_sync(project_id, TaskType.GENERATE_OUTLINE, TaskStatus.PROCESSING)

        try:
            from app.tasks.writing_tasks import generate_outline_task
            outline = generate_outline_task(project_id)
            logger.info("[STEP 3/3] 大纲生成完成，长度: %d 字符", len(outline))
        except Exception as e:
            update_task_status_sync(project_id, TaskType.GENERATE_OUTLINE, TaskStatus.FAILED, str(e))
            raise

        update_task_status_sync(project_id, TaskType.GENERATE_OUTLINE, TaskStatus.COMPLETED)

        # ─── 暂存大纲到数据库（等待用户确认） ────────────────
        update_project_outline_sync(project_id, outline)

        # ─── 状态机推进：PREPARING_DATA → WAITING_OUTLINE_APPROVAL ──
        log_state(project_id, "waiting_outline_approval",
                  f"✅ 资料准备完毕，大纲已生成（{len(outline)} 字符），等待用户确认")
        update_project_status_sync(project_id, ProjectStatus.WAITING_OUTLINE_APPROVAL)

        logger.info("=" * 60)
        logger.info("[NODE 1] ✅ 资料准备完毕 | project_id=%s", project_id)
        logger.info("[NODE 1] 📌 当前状态: WAITING_OUTLINE_APPROVAL")
        logger.info("[NODE 1] 🔔 请用户通过 POST /api/v1/projects/%s/approve-outline 确认大纲", project_id)
        logger.info("=" * 60)

        return {
            "project_id": project_id,
            "status": "waiting_outline_approval",
            "outline_length": len(outline),
        }

    except Exception as exc:
        logger.error("[NODE 1] ❌ 资料准备失败 | project_id=%s | error=%s", project_id, str(exc), exc_info=True)
        update_project_status_sync(project_id, ProjectStatus.FAILED, error_message=str(exc))

        try:
            self.retry(exc=exc)
        except Exception as retry_exc:
            logger.error("[NODE 1] 重试也失败: %s", str(retry_exc))
            raise

        return {
            "project_id": project_id,
            "status": "failed",
            "error": str(exc),
        }


# ================================================================
# 🎯 节点2：分章节异步撰写（用户确认大纲后触发）
# ================================================================

@celery_app.task(
    bind=True,
    name="workflow.run_draft_sections",
    max_retries=1,
    default_retry_delay=30,
    acks_late=True,
)
def run_draft_sections_workflow(self, project_id: str):
    """
    🎯 节点2：分章节异步撰写
    =========================
    状态机：DRAFTING → (自动) → COMPLETED

    此节点在用户确认/修改大纲后触发。前端通过 POST /approve-outline
    提交确认后，此任务被执行。

    执行步骤：
    1. 读取 Project.outline_content（用户确认的最终大纲）
    2. 解析 ## 章节标题
    3. 逐章节调用 LLM 撰写（复用已有的 section_writer）
    4. 每完成一个块，写入 DocumentBlock 表（SSE 端点可实时推送）
    5. 全部章节完成后，组装 Markdown + 渲染 PDF
    6. 状态机推进到 COMPLETED
    """
    logger.info("=" * 60)
    logger.info("[NODE 2] 🚀 分章节异步撰写 | project_id=%s", project_id)
    logger.info("[NODE 2] 状态: DRAFTING → COMPLETED")
    logger.info("=" * 60)

    try:
        log_state(project_id, "drafting", "节点2 开始执行：分章节异步撰写")

        # ─── 1. 从数据库确认项目状态 & 获取大纲 ──────────────
        import uuid as _uuid

        # 使用同步引擎读取
        from sqlalchemy import create_engine, text
        from app.core.config import get_settings
        settings = get_settings()

        project_id_hex = _uuid.UUID(project_id).hex
        sync_engine = create_engine(settings.DATABASE_URL_SYNC)

        with sync_engine.connect() as conn:
            # 获取 topic 和 outline
            row = conn.execute(
                text("SELECT topic, outline_content FROM projects WHERE id = :pid"),
                {"pid": project_id_hex},
            ).fetchone()
            if row is None:
                raise ValueError(f"项目不存在: {project_id}")
            topic, outline_content = row

        if not outline_content:
            logger.warning("[NODE 2] outline_content 为空，尝试从 outline_content 字段获取")
            outline_content = "# 默认大纲\n## 1. 行业概述\n## 2. 市场分析\n"

        # ─── 2. 解析章节标题 ──────────────────────────────────
        section_titles = extract_sections(outline_content)
        logger.info("[NODE 2] 共 %d 个章节待撰写", len(section_titles))

        if not section_titles:
            # 如果解析失败，使用默认章节
            section_titles = ["1. 行业概述", "2. 市场分析", "3. 竞争格局"]
            logger.warning("[NODE 2] 大纲解析结果为空，使用默认章节: %s", section_titles)

        # ─── 3. 逐章节撰写（目前为串行，未来可改为 group 并行） ──
        section_results = []
        for idx, section_title in enumerate(section_titles):
            logger.info("[STEP %d/%d] 撰写章节: '%s'", idx + 1, len(section_titles), section_title)

            # 更新 Task 状态为 PROCESSING
            _update_section_task_status_sync(project_id, section_title, TaskStatus.PROCESSING)

            try:
                from app.tasks.writing_tasks import write_single_section
                content = write_single_section(
                    project_id, section_title, idx
                )

                if not content:
                    content = f"## {section_title}\n\n[本章节内容为空]\n"

                section_results.append(content)

                # ─── 将章节拆分为多个 DocumentBlock 保存 ──────
                _save_section_as_blocks(project_id, section_title, content, idx)

                # 更新 Task 状态为 COMPLETED
                _update_section_task_status_sync(project_id, section_title, TaskStatus.COMPLETED)

                logger.info("  [OK] 章节 '%s' 撰写完成 (%d 字符)", section_title, len(content))

            except Exception as e:
                logger.error("  [FAIL] 章节 '%s' 撰写失败: %s", section_title, str(e))
                _update_section_task_status_sync(project_id, section_title, TaskStatus.FAILED, str(e))
                section_results.append(f"## {section_title}\n\n[本章节生成失败: {str(e)}]\n")

        # ─── 4. 组装 Markdown 报告 ────────────────────────────
        logger.info("[NODE 2] 组装 Markdown 报告...")
        update_task_status_sync(project_id, TaskType.BUILD_REPORT, TaskStatus.PROCESSING)

        try:
            from app.tasks.render_tasks import build_report_markdown
            md_path = build_report_markdown(project_id, section_results)
        except Exception as e:
            update_task_status_sync(project_id, TaskType.BUILD_REPORT, TaskStatus.FAILED, str(e))
            raise

        update_task_status_sync(project_id, TaskType.BUILD_REPORT, TaskStatus.COMPLETED)

        # ─── 5. 生成 PDF ──────────────────────────────────────
        logger.info("[NODE 2] 渲染 PDF...")
        update_task_status_sync(project_id, TaskType.GENERATE_PDF, TaskStatus.PROCESSING)

        try:
            from app.tasks.render_tasks import generate_pdf_report
            pdf_path = generate_pdf_report(project_id, md_path)
        except Exception as e:
            update_task_status_sync(project_id, TaskType.GENERATE_PDF, TaskStatus.FAILED, str(e))
            raise

        update_task_status_sync(project_id, TaskType.GENERATE_PDF, TaskStatus.COMPLETED)

        # ─── 6. 状态机推进到 COMPLETED ────────────────────────
        update_project_status_sync(project_id, ProjectStatus.COMPLETED, pdf_path=pdf_path, md_path=md_path)

        log_state(project_id, "completed",
                  f"✅ 全部完成！共撰写 {len(section_titles)} 个章节，PDF: {pdf_path}")

        logger.info("=" * 60)
        logger.info("[NODE 2] ✅ 全部完成 | project_id=%s", project_id)
        logger.info("[NODE 2] PDF: %s", pdf_path)
        logger.info("=" * 60)

        return {
            "project_id": project_id,
            "status": "completed",
            "sections_count": len(section_titles),
            "md_path": md_path,
            "pdf_path": pdf_path,
        }

    except Exception as exc:
        logger.error("[NODE 2] ❌ 撰写失败 | project_id=%s | error=%s", project_id, str(exc), exc_info=True)
        update_project_status_sync(project_id, ProjectStatus.FAILED, error_message=str(exc))

        try:
            self.retry(exc=exc)
        except Exception as retry_exc:
            logger.error("[NODE 2] 重试也失败: %s", str(retry_exc))
            raise

        return {
            "project_id": project_id,
            "status": "failed",
            "error": str(exc),
        }


# ================================================================
# 保留旧版「一键全自动」工作流（向后兼容）
# ================================================================

@celery_app.task(
    bind=True,
    name="workflow.run_full_report",
    max_retries=1,
    default_retry_delay=30,
    acks_late=True,
)
def run_full_report_workflow(self, project_id: str):
    """
    （旧版兼容）全自动流水线——从搜索到 PDF 一步到位。
    新项目应优先使用 prepare_data_workflow + approve-outline + run_draft_sections_workflow
    这种交互式两阶段流程。
    """
    logger.info("[WORKFLOW] 旧版全自动流水线（一步到位）| project_id=%s", project_id)
    # 先执行节点1
    prepare_data_workflow(project_id)
    # 再执行节点2
    run_draft_sections_workflow(project_id)
    logger.info("[WORKFLOW] 旧版全自动流水线完成 | project_id=%s", project_id)


# ================================================================
# 内部辅助函数
# ================================================================

def _update_section_task_status_sync(
    project_id: str,
    section_title: str,
    status: TaskStatus,
    error: str | None = None,
):
    """
    更新指定章节的 WRITE_SECTION 任务状态。
    由于一个 project 可能有多个 WRITE_SECTION 任务（不同章节），
    所以需要根据 section_title 精确定位。
    """
    import uuid as _uuid
    from datetime import datetime, timezone
    from sqlalchemy import create_engine, text
    from app.core.config import get_settings

    settings = get_settings()
    sync_engine = create_engine(settings.DATABASE_URL_SYNC)

    status_map = {
        TaskStatus.PENDING: "PENDING",
        TaskStatus.PROCESSING: "PROCESSING",
        TaskStatus.COMPLETED: "COMPLETED",
        TaskStatus.FAILED: "FAILED",
    }

    now_ts = datetime.now(timezone.utc)

    with sync_engine.connect() as conn:
        conn.execute(
            text("""
                UPDATE tasks
                SET status = :status,
                    error_message = :error,
                    started_at = CASE WHEN :status = 'PROCESSING' THEN :now ELSE started_at END,
                    completed_at = CASE WHEN :status IN ('COMPLETED','FAILED') THEN :now ELSE completed_at END
                WHERE project_id = :pid
                  AND task_type = 'WRITE_SECTION'
                  AND section_title = :section
            """),
            {
                "pid": _uuid.UUID(project_id).hex,
                "status": status_map.get(status, "PENDING"),
                "error": error,
                "section": section_title,
                "now": now_ts,
            },
        )
        conn.commit()

    logger.info("[DB] 更新章节任务状态 | project=%s | section='%s' | status=%s",
                project_id, section_title, status.value)


def _save_section_as_blocks(
    project_id: str,
    section_title: str,
    content: str,
    section_index: int,
):
    """
    将单章节的 Markdown 内容拆分为多个 DocumentBlock，
    每个逻辑段落/标题作为一个独立块，供 Tiptap 编辑器加载。

    拆分策略：
    - 每段 ## 二级标题作为一个块（标题行单独成块）
    - 段落之间以空行分隔，每个段落作为一个块
    - 引用映射（citations）从内容中提取

    例如输入：
        ## 1. 行业概述
        2025年市场规模达1000亿[1]。
        增长率15%[2]。
    会生成 3 个 DocumentBlock：
        (order=10) "## 1. 行业概述"
        (order=20) "2025年市场规模达1000亿[1]。"
        (order=30) "增长率15%[2]。"
    """
    import re

    # 提取引用 URL（此处简化：从 Document 表获取，或留空）
    citations: dict[str, str] = {}

    # 按行拆分
    lines = content.split("\n")
    block_lines: list[str] = []
    block_order = (section_index + 1) * 10  # 10, 20, 30...
    sub_idx = 0

    for line in lines:
        stripped = line.strip()
        if stripped == "":
            # 空行——当前块结束，保存
            if block_lines:
                block_content = "\n".join(block_lines)
                if block_content.strip():
                    save_document_block_sync(
                        project_id=project_id,
                        section_title=section_title,
                        content=block_content,
                        citations=citations,
                        order_index=block_order + sub_idx,
                    )
                    sub_idx += 1
                block_lines = []
        else:
            block_lines.append(line)

    # 处理最后剩余的行
    if block_lines:
        block_content = "\n".join(block_lines)
        if block_content.strip():
            save_document_block_sync(
                project_id=project_id,
                section_title=section_title,
                content=block_content,
                citations=citations,
                order_index=block_order + sub_idx,
            )

    logger.info("[BLOCKS] 章节 '%s' 已拆分为 %d 个 DocumentBlock",
                section_title, sub_idx + 1)


# 同步包装
def save_document_block_sync(
    project_id: str,
    section_title: str,
    content: str,
    citations: dict[str, str] | None = None,
    order_index: int = 0,
):
    """同步包装：保存文档块"""
    asyncio.run(
        save_document_block(
            project_id=project_id,
            section_title=section_title,
            content=content,
            citations=citations,
            order_index=order_index,
        )
    )
