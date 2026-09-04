"""Prompt Forge golden 测试：图鉴范式要素完整 + 长度预算 + 配额优先级 + 降档兜底。

要素对照来源：8 张产品解构图鉴实例（见 docs/PROMPT_PIPELINE.md）。
"""

from __future__ import annotations

import unittest

from app.services.prompt_forge import (
    DEFAULT_VIEW,
    QUOTAS,
    STYLE_PRESETS,
    VIEW_SPECS,
    build_prompt,
    model_limit,
)

# 真实会话形状的 Schema（农业六旋翼，每层多条含 must/评分差异）
SCHEMA = {
    "layers": [
        {"key": "identity", "items": [
            {"zh": "商用农业植保六旋翼", "en": "commercial agricultural crop-protection hexacopter UAV", "visualizability": 3, "priority": "must"},
        ]},
        {"key": "architecture", "items": [
            {"zh": "六电机非共轴对称布局", "en": "six-motor non-coaxial symmetric layout, three bilateral arm pairs", "visualizability": 3, "priority": "must"},
            {"zh": "中央低重心机身", "en": "central low-profile fuselage with low center of gravity", "visualizability": 3, "priority": "optional"},
            {"zh": "宽体横向展开", "en": "wide lateral footprint configuration", "visualizability": 2, "priority": "optional"},
        ]},
        {"key": "geometry", "items": [
            {"zh": "倒角矩形几何", "en": "chamfered rectangular geometry", "visualizability": 3, "priority": "optional"},
        ]},
        {"key": "components", "items": [
            {"zh": "顶部RTK天线", "en": "low-profile cylindrical RTK GNSS antenna mounted on top centerline", "visualizability": 3, "priority": "must"},
            {"zh": "半透明中央药箱", "en": "translucent centrally mounted chemical tank", "visualizability": 3, "priority": "must"},
            {"zh": "四点加强起落架", "en": "four reinforced tubular landing legs, wide stance", "visualizability": 3, "priority": "optional"},
            {"zh": "前置双摄模块", "en": "dual forward-facing stereo cameras in compact housing", "visualizability": 3, "priority": "optional"},
        ]},
        {"key": "materials", "items": [
            {"zh": "哑光碳纤维管机架", "en": "matte black carbon-fiber composite tubular frame", "visualizability": 3, "priority": "must"},
            {"zh": "工程塑料护罩", "en": "dark injection-molded polymer fairings", "visualizability": 3, "priority": "optional"},
        ]},
        {"key": "hardware", "items": [
            {"zh": "离心喷头阵列", "en": "evenly spaced centrifugal atomizing nozzles under the booms", "visualizability": 3, "priority": "must"},
            {"zh": "机腹地形雷达", "en": "downward millimeter-wave terrain radar beneath fuselage", "visualizability": 3, "priority": "optional"},
        ]},
        {"key": "mechanism", "items": [
            {"zh": "三段折叠喷杆", "en": "three-segment folding spray booms with mechanical hinge joints", "visualizability": 3, "priority": "must"},
            {"zh": "向后上方收纳", "en": "booms fold backward and upward for transport", "visualizability": 3, "priority": "optional"},
        ]},
        {"key": "environment", "items": [
            {"zh": "大田作业环境", "en": "large-scale corn field operation context", "visualizability": 3, "priority": "optional"},
        ]},
    ]
}

# 图鉴骨架必须包含的八图范式要素关键词（v1.1.0 依首次成图抽检扩充）
ATLAS_ELEMENTS = [
    "exploded axonometric",      # ① 纵向轴测爆炸
    "vertical assembly axis",    # ①b 单纵轴对齐（防对角漂移）
    "Z-axis",                    # ② 装配轴向
    "three-band poster layout",  # ③ 三段海报版式
    "inset",                     # ④ 拼版区预留（空框成型）
    "dark studio gradient",      # ⑤ 深灰渐变
    "no landscape",              # ⑤b 背景纯净（防环境泄漏）
    "translucent polycarbonate", # ⑥ 材质（半透明具体化）
    "three-point studio lighting",  # ⑦ 三点棚拍光
    "key fill rim",              # ⑦b 光位落地
    "accent color",              # ⑧ 单强调色
    "no text",                   # ⑨ 无文字
    "no watermarks",             # ⑨b 防伪文字强负向
]


class TestPromptForge(unittest.TestCase):
    def setUp(self):
        self.limit = model_limit("minimax")

    def test_atlas_within_limit(self):
        prompt, report = build_prompt(SCHEMA, "atlas", "auto", image_backend="minimax")
        self.assertLessEqual(len(prompt), self.limit, f"超限: {len(prompt)}")
        self.assertEqual(report["total_len"], len(prompt))

    def test_atlas_contains_all_paradigm_elements(self):
        prompt, _ = build_prompt(SCHEMA, "atlas", "auto", image_backend="minimax")
        low = prompt.lower()
        missing = [e for e in ATLAS_ELEMENTS if e.lower() not in low]
        self.assertEqual(missing, [], f"图鉴骨架缺要素: {missing}")

    def test_quota_and_must_priority(self):
        _, report = build_prompt(SCHEMA, "atlas", "auto", image_backend="minimax")
        # components 层 4 条 → 配额 3，被丢 1（optional 的四点起落架或前置双摄）
        dropped_layers = [d["layer"] for d in report["dropped"]]
        self.assertIn("components", dropped_layers)
        dropped_zh = [d["zh"] for d in report["dropped"] if d["layer"] == "components"]
        self.assertNotIn("顶部RTK天线", dropped_zh, "must 条目不应被丢弃")
        self.assertNotIn("半透明中央药箱", dropped_zh, "must 条目不应被丢弃")

    def test_downgrade_never_hurts_skeleton(self):
        # 构造超长 schema（每层塞满长条目）触发降档
        big = {"layers": [
            {"key": k, "items": [
                {"zh": f"条目{i}", "en": f"very long english visual constraint number {i} " + "x" * 80,
                 "visualizability": 3, "priority": "optional"}
                for i in range(8)
            ]}
            for k in QUOTAS
        ]}
        prompt, report = build_prompt(big, "atlas", "auto", image_backend="minimax")
        self.assertLessEqual(len(prompt), self.limit, "降档后仍超限")
        low = prompt.lower()
        for e in ("exploded axonometric", "dark studio gradient", "no text"):
            self.assertIn(e, low, f"降档裁掉了骨架要素: {e}")
        self.assertTrue(any(d.get("reason") in ("quota", "minimal-fallback") for d in report["dropped"]))

    def test_low_visualizability_excluded(self):
        schema = {"layers": [
            {"key": "identity", "items": [
                {"zh": "厘米级定位", "en": "centimeter-level positioning accuracy", "visualizability": 0, "priority": "must"},
                {"zh": "植保无人机", "en": "agricultural spraying UAV", "visualizability": 3, "priority": "optional"},
            ]},
        ]}
        prompt, _ = build_prompt(schema, "atlas", "auto", image_backend="minimax")
        self.assertNotIn("centimeter-level", prompt, "visualizability<2 的条目不应入选")
        self.assertIn("agricultural spraying UAV", prompt)

    def test_atlas_view_conflict_excludes_environment(self):
        # 图鉴=深色棚拍范式，环境层（农田等场景词）与其冲突 → 不入 prompt，报告记 view-conflict
        prompt, report = build_prompt(SCHEMA, "atlas", "auto", image_backend="minimax")
        self.assertNotIn("corn field", prompt, "environment 条目不应进入 atlas prompt")
        self.assertNotIn("operation context", prompt)
        conflict = [d for d in report["dropped"] if d.get("reason") == "view-conflict"]
        self.assertTrue(conflict, "environment 应以 view-conflict 留痕于报告")
        self.assertEqual({d["layer"] for d in conflict}, {"environment"})
        # hero 视图允许环境
        hero_prompt, _ = build_prompt(SCHEMA, "hero", "auto", image_backend="minimax")
        self.assertIn("corn field", hero_prompt, "hero 视图应保留 environment")

    def test_all_views_build_within_limit(self):
        for view in VIEW_SPECS:
            prompt, report = build_prompt(SCHEMA, view, "minimal", image_backend="minimax")
            self.assertLessEqual(len(prompt), self.limit, f"{view} 超限")

    def test_style_presets_applied(self):
        prompt, _ = build_prompt(SCHEMA, "hero", "watercolor", image_backend="minimax")
        self.assertIn("watercolor", prompt.lower())


if __name__ == "__main__":
    unittest.main()
