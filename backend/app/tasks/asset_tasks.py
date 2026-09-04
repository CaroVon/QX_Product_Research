"""
============================================================
独立资产生成任务 —— qx_assets（独立生图等）
============================================================

由 /assets/generate 端点派发：产物落盘 + 状态写回 qx_assets。
两种通道：
  - 无 project_id：独立生图（image_gen.py 子进程，产物入 design_studio/standalone/）
  - 有 project_id：走项目 design-studio 资产通道（含版本管理），资产行记录引用
"""

from __future__ import annotations

import glob
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import update

from app.core.celery_app import celery_app
from app.core.celery_db import get_sync_engine
from app.core.config import get_settings
from app.models.qx_asset import QxAsset

logger = logging.getLogger(__name__)


def _set_asset(asset_id: str, **fields) -> None:
    if fields:
        fields.setdefault("updated_at", datetime.now(timezone.utc))
        with get_sync_engine().begin() as conn:
            conn.execute(update(QxAsset).where(QxAsset.id == asset_id).values(**fields))


@celery_app.task(
    bind=True,
    name="assets.generate_standalone_image",
    max_retries=0,
    acks_late=False,
    soft_time_limit=420,
    time_limit=450,
)
def generate_standalone_image(self, asset_id: str, prompt: str, product_id: str = ""):  # noqa: ANN001
    """生成一张独立产品/概念图，产物与状态持久化到 qx_assets。"""
    settings = get_settings()
    _set_asset(asset_id, status="running")
    # MiniMax 等生图后端普遍限制 prompt 长度（实测 1500），统一防御截断保首部
    prompt = prompt[:1490]
    try:
        if product_id:
            file_rel, meta = _generate_via_design_studio(product_id, prompt)
        else:
            file_rel, meta = _generate_standalone(settings, asset_id, prompt)
        _set_asset(asset_id, status="done", file_rel=file_rel,
                   meta=json.dumps(meta, ensure_ascii=False), error=None)
        logger.info("[qx-assets] 生图成功 | asset=%s | file=%s", asset_id, file_rel)
        return {"asset_id": asset_id, "status": "done", "file_rel": file_rel}
    except Exception as exc:  # noqa: BLE001
        _set_asset(asset_id, status="failed", error=str(exc)[:500])
        _refund_image(asset_id)
        logger.warning("[qx-assets] 生图失败 | asset=%s | %s", asset_id, exc)
        return {"asset_id": asset_id, "status": "failed", "error": str(exc)[:500]}


def _generate_standalone(settings, asset_id: str, prompt: str) -> tuple[str, dict]:
    """独立通道：image_gen.py 子进程（与 design-studio 同脚本同环境）。"""
    from app.services.design_studio import _image_gen_env, _image_gen_script

    script = _image_gen_script()
    out_dir = Path(settings.OUTPUT_DIR) / "design_studio" / "standalone"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"sa_{asset_id.replace('-', '')[:12]}"
    cmd = [
        sys.executable, str(script), prompt,
        "--aspect_ratio", "16:9", "--image_size", "1K",
        "-o", str(out_dir), "--filename", stem,
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=420,
            cwd=str(script.parent), env=_image_gen_env(),
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("生图超时（>420s）") from exc
    produced = sorted(glob.glob(str(out_dir / f"{stem}.*")), key=os.path.getmtime, reverse=True)
    generated = next((p for p in produced if Path(p).suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")), None)
    if proc.returncode != 0 or not generated:
        detail = (proc.stderr or proc.stdout or "").strip()[-400:] or "生图失败（无输出）"
        raise RuntimeError(f"生图失败: {detail}")
    file_rel = os.path.relpath(generated, settings.OUTPUT_DIR)
    return file_rel, {"channel": "standalone", "backend": _image_gen_env().get("IMAGE_BACKEND", "minimax")}


def _generate_via_design_studio(product_id: str, prompt: str) -> tuple[str, dict]:
    """项目通道：创建 design-studio standalone 条目并生图（含版本管理）。"""
    from app.services import design_studio as ds

    name = prompt[:40] or "独立生图"
    item = ds.create_item(product_id, kind="standalone", name=name, text=prompt)
    item = ds.generate_image_for_item(product_id, item["id"])
    image = item.get("image") or {}
    url = image.get("url") or ""
    # url 形如 /api/v1/files/design_studio/{pid}/{fname}
    file_rel = url.split("/files/", 1)[1] if "/files/" in url else None
    if not file_rel:
        raise RuntimeError("design-studio 生图未返回图片 URL")
    return file_rel, {"channel": "design-studio", "item_id": item["id"], "product_id": product_id}


def _refund_image(asset_id: str) -> None:
    """生图失败退补 1 张额度（找资产 owner）。"""
    import uuid as _uuid
    from sqlalchemy import select

    from app.models.qx_asset import QxAsset

    try:
        with get_sync_engine().connect() as conn:
            row = conn.execute(
                select(QxAsset.owner_id).where(QxAsset.id == _uuid.UUID(asset_id))
            ).fetchone()
        if row is None or row[0] is None:
            return
        from app.core.database import get_sync_session_factory  # noqa: F401
        from sqlalchemy.orm import Session
        with Session(get_sync_engine()) as session:
            from app.models.credit_ledger import CreditLedger
            session.add(CreditLedger(
                user_id=row[0], kind="image", delta=1,
                reason=f"生图失败退补", meta=f'{{"asset_id": "{asset_id}"}}',
            ))
            session.commit()
        logger.info("[qx-assets] 额度退补 | asset=%s", asset_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[qx-assets] 退补失败 | asset=%s | %s", asset_id, exc)
