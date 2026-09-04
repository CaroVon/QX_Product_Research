"""Prompt Forge 冒烟：常量完整性 + 真实 DB schema 组装断言（无 LLM，秒级）。

用法：
    venv/bin/python scripts/prompt_forge_smoke.py            # 用 golden SCHEMA
    venv/bin/python scripts/prompt_forge_smoke.py <asset_id> # 用线上真实关键词资产

部署后检查项：所有视图 ≤ 模型限制、图鉴骨架要素一个不丢、环境层 view-conflict 留痕。
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_BACKEND_DIR = _PROJECT_ROOT / "backend"
for _d in (str(_BACKEND_DIR), str(_PROJECT_ROOT)):
    if _d not in sys.path:
        sys.path.insert(0, _d)

from app.services.prompt_forge import (  # noqa: E402
    DEFAULT_VIEW,
    FORGE_VERSION,
    MODEL_LIMITS,
    VIEW_SPECS,
    build_prompt,
    model_limit,
)

GOLDEN_SCHEMA = {
    "layers": [
        {"key": "identity", "items": [
            {"zh": "商用农业植保六旋翼", "en": "commercial agricultural crop-protection hexacopter UAV",
             "visualizability": 3, "priority": "must"}]},
        {"key": "architecture", "items": [
            {"zh": "六电机对称布局", "en": "six-motor symmetric layout, three bilateral arm pairs",
             "visualizability": 3, "priority": "must"}]},
        {"key": "components", "items": [
            {"zh": "半透明中央药箱", "en": "translucent centrally mounted chemical tank",
             "visualizability": 3, "priority": "must"}]},
        {"key": "environment", "items": [
            {"zh": "大田作业环境", "en": "large-scale corn field operation context",
             "visualizability": 3, "priority": "optional"}]},
    ]
}

ATLAS_MUST = [
    "exploded axonometric", "vertical assembly axis", "Z-axis",
    "three-band poster layout", "inset", "dark studio gradient", "no landscape",
    "translucent polycarbonate", "three-point studio lighting", "key fill rim",
    "accent color", "no text", "no watermarks",
]


def load_real_schema(asset_id: str) -> dict:
    from sqlalchemy.orm import Session

    from app.core.celery_db import get_sync_engine
    from app.models.qx_asset import QxAsset

    with Session(get_sync_engine()) as session:
        asset = session.get(QxAsset, uuid.UUID(asset_id))
        if asset is None or asset.kind != "keywords":
            raise SystemExit(f"资产不存在或非 keywords: {asset_id}")
        meta = asset.meta or "{}"
        schema = (json.loads(meta) if isinstance(meta, str) else meta).get("schema_v2")
        if not schema:
            raise SystemExit(f"资产无 schema_v2: {asset_id}")
        return schema


def main() -> None:
    schema = load_real_schema(sys.argv[1]) if len(sys.argv) > 1 else GOLDEN_SCHEMA
    limit = model_limit("minimax")
    failures: list[str] = []

    print(f"🔨 Prompt Forge 冒烟 | Forge v{FORGE_VERSION} | limit={limit} | "
          f"schema={'DB#' + sys.argv[1][:8] if len(sys.argv) > 1 else 'golden'}")

    for view in VIEW_SPECS:
        prompt, report = build_prompt(schema, view, "auto", image_backend="minimax")
        ok_len = len(prompt) <= limit
        print(f"  [{view:7s}] len={report['total_len']:4d}/{limit} "
              f"included={report['included']:2d} dropped={len(report['dropped']):2d} "
              f"{'✓' if ok_len else '✗ 超限'}")
        if not ok_len:
            failures.append(f"{view} 超限 {report['total_len']}>{limit}")

    atlas_prompt, atlas_report = build_prompt(schema, DEFAULT_VIEW, "auto", image_backend="minimax")
    low = atlas_prompt.lower()
    missing = [e for e in ATLAS_MUST if e.lower() not in low]
    conflict = [d for d in atlas_report["dropped"] if d.get("reason") == "view-conflict"]
    print(f"  [atlas  ] 范式要素 {len(ATLAS_MUST) - len(missing)}/{len(ATLAS_MUST)} "
          f"{'✓' if not missing else '✗ 缺 ' + str(missing)}")
    print(f"  [atlas  ] environment view-conflict 留痕 {len(conflict)} 条 "
          f"{'✓' if conflict else '（无 environment 条目，跳过）'}")
    if missing:
        failures.append(f"atlas 缺要素: {missing}")
    print(f"\n  atlas prompt ({atlas_report['total_len']} 字符):\n    {atlas_prompt}")

    if failures:
        print("\n❌ FAIL:", "; ".join(failures))
        raise SystemExit(1)
    print(f"\n✅ PASS | MODEL_LIMITS={MODEL_LIMITS} | views={list(VIEW_SPECS)}")


if __name__ == "__main__":
    main()
