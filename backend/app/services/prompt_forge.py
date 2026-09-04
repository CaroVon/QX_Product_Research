"""
============================================================
Prompt Forge —— 生图提示词流水线（图片示例→总体生图要求→关键词→MiniMax 输入）
============================================================

设计目标：让「关键词 Schema → MiniMax 输入」成为后端唯一的同源组装点，
带长度预算引擎（骨架永不裁剪，条目按配额精选、逐级降档），产物附预算报告。

链路与来源：
  - 图片示例（8 张产品解构图鉴 golden 范式）→ 要素清单见 PROMPT_PIPELINE.md
  - 总体生图要求 = 本模块 VIEW_SPECS（版本化常量，改模板走 golden 测试+人工抽检）
  - 关键词 = qx_assets(kind=keywords) 的 Schema v2（8 层双语+评分+优先级）
"""

from __future__ import annotations

import logging
from typing import TypedDict

logger = logging.getLogger(__name__)

# ─── 模型输入限制（按 IMAGE_BACKEND 取用；新后端加一行）─────────
MODEL_LIMITS: dict[str, int] = {
    "minimax": 1480,
    "siliconflow": 1480,
}
DEFAULT_LIMIT = 1480


class Item(TypedDict, total=False):
    zh: str
    en: str
    visualizability: int
    priority: str


class Layer(TypedDict, total=False):
    key: str
    items: list[Item]


class Schema(TypedDict, total=False):
    layers: list[Layer]


# ─── 总体生图要求：五视图骨架（八图范式要素一个不丢）──────────────
# 图鉴骨架要素对照：①纵向轴测爆炸 ②Z轴装配序 ③三段海报版式 ④inset 拼版预留
# ⑤深灰渐变背景 ⑥哑光+金属+半透明材质 ⑦三点棚拍光 ⑧单工业强调色 ⑨anatomy 风格 ⑩无文字
VIEW_SPECS: dict[str, dict] = {
    "atlas": {
        # v1.1.0 骨架：依首次成图人工/视觉抽检修正——
        #   ①纵向单轴对齐（防对角漂移） ②三段版式落到具体区带 ③inset 空框成型
        #   ④背景纯净 no landscape（防环境泄漏） ⑤半透明具体化为 polycarbonate
        #   ⑥三点光落到 key/fill/rim ⑦防伪文字强负向（no numbers/watermarks/clean unlabeled）
        # 注意：atlas 不取 environment 层（深色棚拍范式与场景词冲突，按 view-conflict 丢弃）
        "label": "解构图鉴（默认）",
        "skeleton": (
            "vertical exploded axonometric product poster, "
            "all exploded parts aligned on one vertical assembly axis in Z-axis order, no diagonal scatter, "
            "three-band poster layout: top band upper assembly, middle band main body, bottom band base, "
            "thin-framed empty inset panels along side margins, "
            "pure dark studio gradient background, no landscape, "
            "matte low-gloss housing, brushed metal accents, translucent polycarbonate parts, "
            "key fill rim three-point studio lighting, "
            "single industrial accent color on dark gray, anatomy-marketing engineering aesthetic, "
            "no text no letters no numbers no labels no watermarks, clean unlabeled surfaces"
        ),
        "slots": [
            ("IDENTITY", ["identity"]),
            ("STRUCTURE", ["architecture", "geometry", "mechanism"]),
            ("PARTS", ["components", "hardware"]),
            ("SURFACE", ["materials"]),
        ],
    },
    "hero": {
        "label": "Hero 产品渲染",
        "skeleton": (
            "three-quarter front view hero product render, complete assembled product, "
            "realistic industrial product visualization, premium commercial photography, "
            "shallow depth of field, studio lighting"
        ),
        "slots": [
            ("IDENTITY", ["identity"]),
            ("STRUCTURE", ["architecture", "geometry"]),
            ("DETAIL", ["components", "materials", "hardware"]),
            ("CONTEXT", ["environment"]),
        ],
    },
    "ortho": {
        "label": "三视图",
        "skeleton": (
            "orthographic industrial design presentation, front view + side view + top view in a clean grid, "
            "consistent proportions across views, precise line-quality render with subtle shading"
        ),
        "slots": [
            ("IDENTITY", ["identity"]),
            ("STRUCTURE", ["architecture", "geometry"]),
            ("DETAIL", ["components", "materials"]),
        ],
    },
    "detail": {
        "label": "细节特写",
        "skeleton": (
            "close-up industrial design study of the core mechanism and key components, "
            "macro detail, tactile material rendering, engineering illustration quality"
        ),
        "slots": [
            ("IDENTITY", ["identity"]),
            ("FOCUS", ["mechanism", "components"]),
            ("SURFACE", ["materials"]),
        ],
    },
    "cutaway": {
        "label": "剖面剖视",
        "skeleton": (
            "technical section cutaway view, visible internal mechanical structure, "
            "internal components and structural frame revealed, engineering illustration quality"
        ),
        "slots": [
            ("IDENTITY", ["identity"]),
            ("STRUCTURE", ["architecture", "mechanism"]),
            ("INTERNAL", ["hardware", "components"]),
            ("SURFACE", ["materials"]),
        ],
    },
}

# ─── 配额表：每层最多入选条数（must 优先 → visualizability 降序）──
QUOTAS: dict[str, int] = {
    "identity": 1, "architecture": 2, "geometry": 1, "mechanism": 2,
    "components": 3, "materials": 2, "hardware": 2, "environment": 1,
}

# ─── 风格预设（九档；后端为唯一事实源，前端仅展示）────────────────
STYLE_PRESETS: dict[str, str] = {
    "auto": "",
    "minimal": "minimal studio product render, soft diffuse lighting, clean background",
    "sketch": "industrial design sketch, marker and ballpoint linework, detail close-ups on paper",
    "scene": "lifestyle scene photography, natural light, shallow depth of field",
    "c4d": "C4D/OC render style, soft inflated shapes, vivid gradient background",
    "watercolor": "hand-painted watercolor illustration, gentle washes, paper texture",
    "matte": "matte CMF presentation, muted premium palette, soft gradients",
    "scifi": "concept sci-fi product render, metal and glass, cinematic depth",
    "collage": "editorial collage layout, swiss grid, typography-friendly negative space",
}

DEFAULT_VIEW = "atlas"


class Report(TypedDict, total=False):
    view: str
    style: str
    limit: int
    total_len: int
    included: int
    dropped: list  # [{layer, zh, reason}]
    forge_version: str


FORGE_VERSION = "1.1.0"


def model_limit(backend: str | None) -> int:
    return MODEL_LIMITS.get((backend or "").lower(), DEFAULT_LIMIT)


def _select(items: list[Item], quota: int, halved: bool = False) -> tuple[list[Item], list[Item]]:
    """层内选择：must 优先 → visualizability 降序；返回 (入选, 丢弃)。"""
    usable = [it for it in items if (it.get("en") or "").strip() and it.get("visualizability", 2) >= 2]
    ranked = sorted(
        enumerate(usable),
        key=lambda p: (0 if p[1].get("priority") == "must" else 1, -(p[1].get("visualizability") or 0)),
    )
    take = max(1, quota // 2) if halved else quota
    chosen_idx = {i for i, _ in ranked[:take]}
    chosen = [it for i, it in enumerate(usable) if i in chosen_idx]
    dropped = [it for i, it in enumerate(usable) if i not in chosen_idx]
    return chosen, dropped


def build_prompt(
    schema: Schema,
    view: str = DEFAULT_VIEW,
    style_key: str = "auto",
    *,
    limit: int | None = None,
    image_backend: str | None = None,
) -> tuple[str, Report]:
    """Schema v2 → MiniMax 输入（预算引擎：骨架永不裁，条目逐级降档）。

    返回 (prompt, report)。超限降档顺序：满配额 → optional 先丢 → 配额减半 → 最小集。
    """
    spec = VIEW_SPECS.get(view) or VIEW_SPECS[DEFAULT_VIEW]
    style = STYLE_PRESETS.get(style_key, "")
    budget = limit if limit is not None else model_limit(image_backend)
    layers: dict[str, list[Item]] = {}
    for layer in schema.get("layers") or []:
        layers.setdefault(layer.get("key", ""), []).extend(layer.get("items") or [])

    def assemble(halved: bool) -> tuple[str, list[dict]]:
        parts: list[str] = [spec["skeleton"]]
        dropped: list[dict] = []
        used_en: set[str] = set()
        for slot_name, layer_keys in spec["slots"]:
            slot_items: list[Item] = []
            for lk in layer_keys:
                chosen, drop = _select(layers.get(lk, []), QUOTAS.get(lk, 1), halved)
                slot_items.extend(chosen)
                for it in drop:
                    if it.get("en") not in used_en:
                        dropped.append({"layer": lk, "zh": it.get("zh") or it.get("en", "")[:30], "reason": "quota"})
                for it in chosen:
                    used_en.add(it.get("en") or "")
            if slot_items:
                ens = [it["en"].strip().rstrip(".") for it in slot_items if it.get("en")]
                if ens:
                    parts.append(", ".join(ens))
        # 本视图不覆盖的层（如 atlas 的 environment）→ 按视图冲突丢弃，留痕于报告
        covered = {lk for _slot, lks in spec["slots"] for lk in lks}
        for lk in QUOTAS:
            if lk not in covered:
                for it in layers.get(lk, []):
                    if (it.get("en") or "").strip() and it.get("visualizability", 2) >= 2:
                        dropped.append({"layer": lk, "zh": it.get("zh") or it.get("en", "")[:30], "reason": "view-conflict"})
        if style:
            parts.append(style)
        return ", ".join(parts), dropped

    prompt, dropped = assemble(halved=False)
    # 降档兜底：仍超限 → 配额减半重拼（骨架永不裁剪）
    if len(prompt) > budget:
        logger.info("[prompt-forge] 超限降档 | len=%d > %d | view=%s", len(prompt), budget, view)
        prompt, dropped2 = assemble(halved=True)
        dropped = dropped + dropped2
    # 极端兜底：仅骨架 + identity
    if len(prompt) > budget:
        ident = ", ".join(
            it["en"].strip() for it in _select(layers.get("identity", []), 1)[0] if it.get("en")
        )
        prompt = f"{spec['skeleton']}{', ' + ident if ident else ''}"
        dropped.append({"layer": "*", "zh": "全部非 identity 条目", "reason": "minimal-fallback"})

    included = len(
        [1 for _slot, lks in spec["slots"] for lk in lks for _ in _select(layers.get(lk, []), QUOTAS.get(lk, 1))[0]]
    )
    report: Report = {
        "view": view, "style": style_key, "limit": budget,
        "total_len": len(prompt), "included": included, "dropped": dropped[:20],
        "forge_version": FORGE_VERSION,
    }
    return prompt, report
