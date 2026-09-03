"""
============================================================
QX Studio 独立资产库 API —— /api/v1/assets
============================================================

统一承载独立生图 / 关键词资产 / 手动上传资产：
  POST /assets/generate        独立生图（agent 工具与前端按钮共用）
  GET  /assets                 资产列表（kind/project_id 过滤）
  GET  /assets/{id}            资产详情（轮询生图状态）
  DELETE /assets/{id}          删除资产记录（文件保留）
  POST /assets/{id}/attach     挂载/取消挂载到项目（跨场景联动）
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.qx_asset import QxAsset
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/assets", tags=["qx-assets"])


class AssetGenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000, description="生图提示词")
    project_id: str | None = Field(default=None, description="可选，挂载的 QX 任务 ID")
    name: str | None = Field(default=None, max_length=200, description="展示名（默认取提示词前 40 字）")


class AssetAttachRequest(BaseModel):
    project_id: str | None = Field(default=None, description="目标项目 ID；null/空 = 取消挂载")


class KeywordAssetCreateRequest(BaseModel):
    """关键词资产（5 组：design/function/appearance/audience/scenario）。"""
    groups: dict[str, list[str]] = Field(..., description="组名 → 关键词列表")
    name: str | None = Field(default=None, max_length=200)
    project_id: str | None = Field(default=None)


class KeywordAssetUpdateRequest(BaseModel):
    groups: dict[str, list[str]] = Field(..., description="组名 → 关键词列表")


def _asset_dict(a: QxAsset) -> dict:
    return {
        "id": str(a.id),
        "kind": a.kind,
        "origin": a.origin,
        "status": a.status,
        "name": a.name,
        "prompt": a.prompt,
        "file_rel": a.file_rel,
        # 前端/agent 直接可用的图片 URL（经 StaticFiles 提供）
        "image_url": f"/api/v1/files/{a.file_rel}" if a.file_rel else None,
        "meta": json.loads(a.meta) if a.meta else None,
        "project_id": str(a.project_id) if a.project_id else None,
        "error": a.error,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


@router.post("/generate")
async def generate_asset(
    body: AssetGenerateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """提交独立生图（异步 Celery），立即返回资产 ID 供轮询。"""
    from app.tasks.asset_tasks import generate_standalone_image

    project_uuid: uuid.UUID | None = None
    if body.project_id:
        project_uuid = uuid.UUID(body.project_id)  # 非法 ID 直接 422

    asset = QxAsset(
        kind="image",
        origin="agent",
        status="pending",
        name=(body.name or body.prompt[:40] or "独立生图"),
        prompt=body.prompt,
        project_id=project_uuid,
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)

    generate_standalone_image.delay(str(asset.id), body.prompt, body.project_id or "")
    logger.info("[qx-assets] 生图已派发 | asset=%s | project=%s", asset.id, project_uuid)
    return {"generation_id": str(asset.id), "status": asset.status, "asset": _asset_dict(asset)}


@router.get("")
async def list_assets(
    kind: str | None = None,
    project_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """资产列表（新→旧）。project_id=none 表示只看未挂载的独立资产。"""
    q = select(QxAsset).order_by(QxAsset.created_at.desc()).limit(min(limit, 200))
    if kind:
        q = q.where(QxAsset.kind == kind)
    if status:
        q = q.where(QxAsset.status == status)
    if project_id == "none":
        q = q.where(QxAsset.project_id.is_(None))
    elif project_id:
        q = q.where(QxAsset.project_id == uuid.UUID(project_id))
    rows = (await db.execute(q)).scalars().all()
    return {"assets": [_asset_dict(a) for a in rows]}


@router.get("/{asset_id}")
async def get_asset(
    asset_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """资产详情（生图轮询端点）。"""
    a = await db.get(QxAsset, asset_id)
    if a is None:
        raise HTTPException(status_code=404, detail="资产不存在")
    return _asset_dict(a)


@router.delete("/{asset_id}")
async def delete_asset(
    asset_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """删除资产记录（产物文件保留在磁盘）。"""
    a = await db.get(QxAsset, asset_id)
    if a is None:
        raise HTTPException(status_code=404, detail="资产不存在")
    await db.delete(a)
    await db.commit()
    return {"deleted": str(asset_id)}


@router.post("/{asset_id}/attach")
async def attach_asset(
    asset_id: uuid.UUID,
    body: AssetAttachRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """挂载到项目 / 取消挂载（跨场景引用联动的落点）。"""
    a = await db.get(QxAsset, asset_id)
    if a is None:
        raise HTTPException(status_code=404, detail="资产不存在")
    a.project_id = uuid.UUID(body.project_id) if body.project_id else None
    a.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return _asset_dict(a)


_ALLOWED_UPLOAD_EXT = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg",
    ".pdf", ".md", ".txt", ".docx", ".pptx", ".csv", ".json", ".xlsx",
}
_MAX_UPLOAD_BYTES = 20 * 1024 * 1024


@router.post("/keywords")
async def create_keyword_asset(
    body: KeywordAssetCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """保存关键词资产（研究产出 → 设计种子）：独立入库，可挂项目。

    groups 的键通常为 design/function/appearance/audience/scenario，
    前端「用关键词生图」按组拼接提示词。
    """
    cleaned = {
        str(k)[:32]: [str(w)[:80] for w in (v or [])][:30]
        for k, v in (body.groups or {}).items()
    }
    if not cleaned:
        raise HTTPException(status_code=422, detail="关键词组不能为空")
    asset = QxAsset(
        kind="keywords",
        origin="agent",
        status="done",
        name=body.name or "关键词资产",
        prompt=json.dumps(cleaned, ensure_ascii=False),
        meta=json.dumps({"groups": cleaned}, ensure_ascii=False),
        project_id=uuid.UUID(body.project_id) if body.project_id else None,
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    return _asset_dict(asset)


@router.put("/keywords/{asset_id}")
async def update_keyword_asset(
    asset_id: uuid.UUID,
    body: KeywordAssetUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """更新关键词资产（聊天面板内联编辑后的保存）。"""
    a = await db.get(QxAsset, asset_id)
    if a is None or a.kind != "keywords":
        raise HTTPException(status_code=404, detail="关键词资产不存在")
    cleaned = {
        str(k)[:32]: [str(w)[:80] for w in (v or [])][:30]
        for k, v in (body.groups or {}).items()
    }
    a.prompt = json.dumps(cleaned, ensure_ascii=False)
    a.meta = json.dumps({"groups": cleaned}, ensure_ascii=False)
    a.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(a)
    return _asset_dict(a)


@router.post("/upload")
async def upload_asset(
    file: UploadFile = File(...),
    name: str = Form(default=""),
    project_id: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """手动上传资产（图片/文档）入库：origin=manual，可挂项目。"""
    settings = get_settings()
    ext = Path(file.filename or "").suffix.lower()
    if ext and ext not in _ALLOWED_UPLOAD_EXT:
        raise HTTPException(status_code=422, detail=f"不支持的文件类型: {ext}")
    out_dir = Path(settings.OUTPUT_DIR) / "asset_uploads"
    out_dir.mkdir(parents=True, exist_ok=True)
    asset_id = uuid.uuid4()
    dest = out_dir / f"{asset_id.hex}{ext}"
    size = 0
    with dest.open("wb") as fp:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > _MAX_UPLOAD_BYTES:
                fp.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="文件超过 20MB 上限")
            fp.write(chunk)
    kind = "image" if ext in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"} else "document"
    asset = QxAsset(
        id=asset_id,
        kind=kind,
        origin="manual",
        status="done",
        name=name or (file.filename or "上传资产"),
        file_rel=str(dest.relative_to(settings.OUTPUT_DIR)),
        project_id=uuid.UUID(project_id) if project_id else None,
        meta=json.dumps({"upload_filename": file.filename, "size": size}, ensure_ascii=False),
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    return _asset_dict(asset)
