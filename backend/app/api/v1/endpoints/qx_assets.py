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

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
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
    # 推荐入参：由 Prompt Forge 后端统一组装（与 agent 路径同源）
    schema_asset_id: str | None = Field(default=None, description="关键词资产 ID（Schema v2）→ 后端组装")
    view: str | None = Field(default=None, description="视图：atlas/hero/ortho/detail/cutaway（默认 atlas）")
    style_key: str | None = Field(default=None, description="风格预设 key（默认 auto）")
    # 兼容入参：裸 prompt 直发
    prompt: str | None = Field(default=None, max_length=8000, description="生图提示词（直发模式）")
    project_id: str | None = Field(default=None, description="可选，挂载的 QX 任务 ID")
    name: str | None = Field(default=None, max_length=200, description="展示名（默认取提示词前 40 字）")
    thread_id: str | None = Field(default=None, max_length=64, description="发起会话 ID（前端直发时携带）")


def _thread_of(request: Request, explicit: str | None) -> str | None:
    """会话关联：显式参数优先，其次 qx_tools 服务头 X-QX-Thread。"""
    return (explicit or "").strip() or request.headers.get("X-QX-Thread", "").strip() or None


def _sanitize_schema(schema: dict) -> dict:
    """Schema v2 深度清洗（长度/数量限制，防滥用）。"""
    import json as _json

    raw = _json.dumps(schema, ensure_ascii=False, default=str)
    if len(raw) > 60000:
        raise HTTPException(status_code=422, detail="schema 过大（>60KB）")
    out: dict = {"layers": []}
    for layer in (schema.get("layers") or [])[:12]:
        out["layers"].append({
            "key": str(layer.get("key", "misc"))[:32],
            "items": [
                {
                    "zh": str(it.get("zh") or "")[:120],
                    "en": str(it.get("en") or "")[:240],
                    "visualizability": max(0, min(3, int(it.get("visualizability") or 0))),
                    "priority": "must" if it.get("priority") == "must" else "optional",
                    "source": [str(x)[:60] for x in (it.get("source") or [])][:5],
                }
                for it in (layer.get("items") or [])[:20]
            ],
        })
    if schema.get("conflicts"):
        out["conflicts"] = schema["conflicts"][:10]
    if schema.get("positioning"):
        out["positioning"] = schema["positioning"]
    if schema.get("spec_tree"):
        out["spec_tree"] = str(schema["spec_tree"])[:4000]
    return out


class AssetAttachRequest(BaseModel):
    project_id: str | None = Field(default=None, description="目标项目 ID；null/空 = 取消挂载")


class KeywordAssetCreateRequest(BaseModel):
    """关键词资产。Schema v2（8 层结构化）兼容旧 5 组格式。"""
    groups: dict[str, list[str]] | None = Field(default=None, description="旧格式：组名 → 关键词列表")
    schema: dict | None = Field(default=None, description="Schema v2：{layers, conflicts, positioning, spec_tree}")
    name: str | None = Field(default=None, max_length=200)
    project_id: str | None = Field(default=None)
    thread_id: str | None = Field(default=None)


class KeywordAssetUpdateRequest(BaseModel):
    groups: dict[str, list[str]] | None = Field(default=None, description="旧格式：组名 → 关键词列表")
    schema: dict | None = Field(default=None, description="Schema v2（编辑后整体回传）")


def _asset_dict(a: QxAsset) -> dict:
    return {
        "id": str(a.id),
        "owner_id": str(a.owner_id) if a.owner_id else None,
        "thread_id": a.thread_id,
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
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """提交独立生图（异步 Celery），立即返回资产 ID 供轮询。

    两条入参路径：
    - 推荐：schema_asset_id + view + style_key → Prompt Forge 统一组装（前后端/agent 同源，
      带预算报告，meta.forge_report 可审计）
    - 兼容：裸 prompt 直发
    计费（W3-4）：预检 image 余额并即时扣减 1 张；生成失败由任务侧退补。
    内容安全（W5-6）：prompt 黑名单拦截。
    """
    import json as _json

    from app.services.content_safety import check_prompt
    from app.services.credits import consume
    from app.services.prompt_forge import DEFAULT_VIEW, VIEW_SPECS, build_prompt
    from app.tasks.asset_tasks import generate_standalone_image

    forge_report = None
    if body.schema_asset_id:
        kw = await db.get(QxAsset, uuid.UUID(body.schema_asset_id))
        if kw is None or kw.kind != "keywords":
            raise HTTPException(status_code=404, detail="关键词资产不存在")
        schema_obj = ((kw.meta and _json.loads(kw.meta)) or {}).get("schema_v2")
        if not schema_obj:
            raise HTTPException(status_code=422, detail="该关键词资产不是 Schema v2 格式")
        view = body.view if body.view in VIEW_SPECS else DEFAULT_VIEW
        prompt, forge_report = build_prompt(
            schema_obj, view, body.style_key or "auto",
            image_backend=__import__("os").environ.get("IMAGE_BACKEND", "minimax"),
        )
        label = VIEW_SPECS[view]["label"]
        name = body.name or f"{label}·{kw.name or ''}"[:60]
    else:
        prompt = body.prompt or ""
        view = body.view or DEFAULT_VIEW
        name = body.name or (prompt[:40] or "独立生图")
    if not prompt:
        raise HTTPException(status_code=422, detail="prompt 与 schema_asset_id 至少提供一项")

    violation = check_prompt(prompt)
    if violation:
        raise HTTPException(status_code=422, detail=violation)

    project_uuid: uuid.UUID | None = None
    if body.project_id:
        project_uuid = uuid.UUID(body.project_id)  # 非法 ID 直接 422

    ok, left = await consume(db, user, "image", 1, f"独立生图({view})", None)
    if not ok:
        raise HTTPException(status_code=402, detail=f"生图额度不足（剩 {left} 张）：请联系管理员补充")

    meta_obj: dict = {}
    if forge_report:
        meta_obj["forge_report"] = forge_report
    asset = QxAsset(
        kind="image",
        origin="agent",
        status="pending",
        name=name,
        prompt=prompt,
        project_id=project_uuid,
        owner_id=user.id,
        thread_id=_thread_of(request, body.thread_id),
        meta=_json.dumps(meta_obj, ensure_ascii=False) if meta_obj else None,
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)

    generate_standalone_image.delay(str(asset.id), prompt, body.project_id or "")
    logger.info("[qx-assets] 生图已派发 | asset=%s | project=%s | user=%s | forge=%s | len=%s",
                asset.id, project_uuid, user.username,
                forge_report and forge_report.get("forge_version"), len(prompt))
    return {"generation_id": str(asset.id), "status": asset.status, "asset": _asset_dict(asset),
            "forge_report": forge_report}


@router.get("")
async def list_assets(
    kind: str | None = None,
    project_id: str | None = None,
    status: str | None = None,
    thread_id: str | None = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """资产列表（新→旧）。project_id=none 只看未挂载；thread_id=none 只看历史（无会话关联）。"""
    q = select(QxAsset).order_by(QxAsset.created_at.desc()).limit(min(limit, 200))
    flt = _owner_filter(user)
    if flt is not None:
        q = q.where(flt)
    if kind:
        q = q.where(QxAsset.kind == kind)
    if status:
        q = q.where(QxAsset.status == status)
    if project_id == "none":
        q = q.where(QxAsset.project_id.is_(None))
    elif project_id:
        q = q.where(QxAsset.project_id == uuid.UUID(project_id))
    if thread_id == "none":
        q = q.where(QxAsset.thread_id.is_(None))
    elif thread_id:
        q = q.where(QxAsset.thread_id == thread_id)
    rows = (await db.execute(q)).scalars().all()
    return {"assets": [_asset_dict(a) for a in rows]}


class SuiteGenerateRequest(BaseModel):
    schema_asset_id: str = Field(..., description="关键词资产 ID（Schema v2）")
    views: list[str] = Field(default_factory=lambda: ["atlas", "hero", "ortho", "detail"])
    style_key: str = Field(default="auto")
    project_id: str | None = Field(default=None)
    thread_id: str | None = Field(default=None)


@router.post("/generate-suite")
async def generate_asset_suite(
    body: SuiteGenerateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """一键套装（W7+Prompt Forge）：后端按视图循环组装提交，返回逐视图结果与预算报告。"""
    import json as _json

    from app.services.content_safety import check_prompt
    from app.services.credits import consume
    from app.services.prompt_forge import DEFAULT_VIEW, VIEW_SPECS, build_prompt
    from app.tasks.asset_tasks import generate_standalone_image

    kw = await db.get(QxAsset, uuid.UUID(body.schema_asset_id))
    if kw is None or kw.kind != "keywords":
        raise HTTPException(status_code=404, detail="关键词资产不存在")
    schema_obj = ((kw.meta and _json.loads(kw.meta)) or {}).get("schema_v2")
    if not schema_obj:
        raise HTTPException(status_code=422, detail="该关键词资产不是 Schema v2 格式")

    views = [v for v in body.views if v in VIEW_SPECS] or [DEFAULT_VIEW]
    # 预检组装（长度/黑名单先过一遍再扣额度）
    forged = []
    for v in views:
        prompt, report = build_prompt(
            schema_obj, v, body.style_key,
            image_backend=__import__("os").environ.get("IMAGE_BACKEND", "minimax"),
        )
        violation = check_prompt(prompt)
        if violation:
            raise HTTPException(status_code=422, detail=f"{VIEW_SPECS[v]['label']}: {violation}")
        forged.append((v, prompt, report))

    ok, left = await consume(db, user, "image", len(forged), f"套装生图 x{len(forged)}", {"kw": body.schema_asset_id})
    if not ok:
        raise HTTPException(status_code=402, detail=f"生图额度不足（套装需 {len(forged)} 张，剩 {left} 张）：请联系管理员补充")

    thread_id = _thread_of(request, body.thread_id)
    project_uuid = uuid.UUID(body.project_id) if body.project_id else None
    results = []
    for v, prompt, report in forged:
        asset = QxAsset(
            kind="image", origin="agent", status="pending",
            name=f"{VIEW_SPECS[v]['label']}·{kw.name or ''}"[:60],
            prompt=prompt, project_id=project_uuid, owner_id=user.id, thread_id=thread_id,
            meta=_json.dumps({"forge_report": report}, ensure_ascii=False),
        )
        db.add(asset)
        await db.commit()
        await db.refresh(asset)
        generate_standalone_image.delay(str(asset.id), prompt, body.project_id or "")
        results.append({"view": v, "generation_id": str(asset.id), "forge_report": report})
    return {"count": len(results), "results": results}


@router.get("/images-zip")
async def download_images_zip(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """导出我的全部已完成生图为 ZIP（作品集图片包）。"""
    import io
    import zipfile
    from pathlib import Path

    from fastapi.responses import Response
    from app.core.config import get_settings

    q = select(QxAsset).where(
        QxAsset.kind == "image", QxAsset.status == "done",
        QxAsset.file_rel.is_not(None), QxAsset.owner_id == user.id,
    ).order_by(QxAsset.created_at.desc()).limit(200)
    assets = (await db.execute(q)).scalars().all()
    if not assets:
        raise HTTPException(status_code=404, detail="暂无可导出的生图作品")

    out_dir = Path(get_settings().OUTPUT_DIR)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, a in enumerate(assets, 1):
            fp = out_dir / a.file_rel
            if fp.is_file():
                ext = fp.suffix or ".png"
                zf.write(fp, f"作品_{i:03d}_{(a.name or 'generated')[:30]}{ext}")
    logger.info("[qx-assets] 作品 ZIP | user=%s | %d 张", user.username, len(assets))
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="qx_portfolio_{user.username.split("@")[0]}.zip"'},
    )


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


def _is_admin(user) -> bool:
    from app.core.config import get_settings
    admins = {x.strip() for x in (get_settings().QX_ADMIN_EMAILS or "").split(",") if x.strip()}
    return (user.username or "") in admins


def _owner_filter(user):
    """列表归属过滤：本人可见自己的；admin 全览；旧数据（owner NULL）所有人可见。"""
    from sqlalchemy import or_
    return or_(QxAsset.owner_id == user.id, QxAsset.owner_id.is_(None)) if not _is_admin(user) else None


_ALLOWED_UPLOAD_EXT = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg",
    ".pdf", ".md", ".txt", ".docx", ".pptx", ".csv", ".json", ".xlsx",
}
_MAX_UPLOAD_BYTES = 20 * 1024 * 1024


@router.post("/keywords")
async def create_keyword_asset(
    body: KeywordAssetCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """保存关键词资产（研究产出 → 设计种子）：独立入库，可挂项目。

    两种格式：
    - 旧 5 组：groups={组名: [关键词]}
    - Schema v2：schema={layers:[{key, items:[{zh,en,visualizability,priority,source}]}],
      conflicts, positioning, spec_tree}（8 层产品设计规格，双语，评分与冲突元数据）
    """
    meta_obj: dict
    if body.schema:
        meta_obj = {"schema_v2": _sanitize_schema(body.schema)}
        if not meta_obj["schema_v2"].get("layers"):
            raise HTTPException(status_code=422, detail="schema.layers 不能为空")
        summary = "; ".join(
            f"{l.get('key')}: " + "、".join(
                str(it.get("zh") or it.get("en") or "")[:30]
                for it in (l.get("items") or [])[:4]
            )
            for l in meta_obj["schema_v2"]["layers"][:4]
        )
    else:
        cleaned = {
            str(k)[:32]: [str(w)[:80] for w in (v or [])][:30]
            for k, v in (body.groups or {}).items()
        }
        if not cleaned:
            raise HTTPException(status_code=422, detail="关键词组不能为空")
        meta_obj = {"groups": cleaned}
        summary = "; ".join(f"{k}: {'、'.join(v[:4])}" for k, v in list(cleaned.items())[:4])
    asset = QxAsset(
        kind="keywords",
        origin="agent",
        status="done",
        name=body.name or "关键词资产",
        prompt=("[Schema v2] " + summary[:3800]) if body.schema else json.dumps(
            meta_obj.get("groups", {}), ensure_ascii=False),
        meta=json.dumps({**meta_obj, "summary": summary[:200]}, ensure_ascii=False),
        project_id=uuid.UUID(body.project_id) if body.project_id else None,
        owner_id=user.id,
        thread_id=_thread_of(request, body.thread_id),
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
    """更新关键词资产（聊天面板内联编辑后的保存，兼容两种格式）。"""
    a = await db.get(QxAsset, asset_id)
    if a is None or a.kind != "keywords":
        raise HTTPException(status_code=404, detail="关键词资产不存在")
    if body.schema:
        meta_obj = {"schema_v2": _sanitize_schema(body.schema)}
    elif body.groups:
        meta_obj = {"groups": {
            str(k)[:32]: [str(w)[:80] for w in (v or [])][:30]
            for k, v in body.groups.items()
        }}
    else:
        raise HTTPException(status_code=422, detail="groups 与 schema 至少提供一项")
    old_meta = json.loads(a.meta or "{}")
    a.meta = json.dumps({**old_meta, **meta_obj}, ensure_ascii=False)
    if "groups" in meta_obj:
        a.prompt = json.dumps(meta_obj["groups"], ensure_ascii=False)
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
        owner_id=user.id,
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    return _asset_dict(asset)
