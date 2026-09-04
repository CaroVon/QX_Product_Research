# 生图提示词流水线（Prompt Forge）

> 链路定义来源：产品要求「图片示例 → 总体生图要求 → 关键词 → MiniMax 输入 → 生图」。
> 本文档描述该链路的工程化实现、范式要素对照表与模板改版标准操作流程（SOP）。

## 1. 链路总览

```
图片示例（8 张产品解构图鉴 golden 范式，用户桌面《生图》）
   │  人工提炼要素清单（见 §2 对照表）
   ▼
总体生图要求 ──► prompt_forge.py 版本化常量（唯一事实源）
   │              VIEW_SPECS（五视图骨架）/ QUOTAS（层配额）/ MODEL_LIMITS / STYLE_PRESETS
   ▼
关键词 ────────► qx_assets(kind=keywords, meta.schema_v2)  八层双语 Schema
   │              identity/architecture/geometry/mechanism/components/materials/hardware/environment
   ▼
build_prompt(schema, view, style_key, image_backend)      ← 后端唯一组装点
   │  预算引擎：骨架永不裁剪；满配额 → 配额减半 → 最小集 逐级降档
   │  视图冲突检测：atlas 不取 environment（深色棚拍 vs 场景词），报告记 view-conflict
   ▼
MiniMax 输入（≤ MODEL_LIMITS[backend]，默认 1480 字符）
   │  资产记录落 prompt 全文 + meta.forge_report（入选/丢弃明细，永久可审计）
   ▼
生图 ──────────► 前端生图卡「查看提示词」可审计每个字符；人工抽检对照 8 实例
```

**同源保证**：`POST /assets/generate {schema_asset_id, view, style_key}`（推荐）、
`POST /assets/generate-suite`（套装）、`qx_tools.design.generate_design_image_tool`
三条路径全部经 `build_prompt()` 组装——前端/agent 永远不再自行拼 prompt。
旧裸 `prompt` 入参保留兼容（老 5 组卡片前端本地截断 1400）。

## 2. 八图范式要素 → 图鉴骨架字段对照表

骨架（VIEW_SPECS["atlas"]["skeleton"]，Forge v1.1.0）逐要素落位：

| # | 范式要素（8 实例提炼） | 骨架措辞 | 视觉自检得分（v1.0→v1.1.0） |
|---|---|---|---|
| ① | 纵向轴测爆炸 | `vertical exploded axonometric product poster` | 2.5→3 |
| ①b | 单纵轴对齐（防对角漂移） | `all exploded parts aligned on one vertical assembly axis in Z-axis order, no diagonal scatter` | 2→3 |
| ② | Z 轴装配序 | 同上 `in Z-axis order` | — |
| ③ | 三段海报版式 | `three-band poster layout: top band upper assembly, middle band main body, bottom band base` | 1.5→3 |
| ④ | inset 拼版预留 | `thin-framed empty inset panels along side margins` | 1→2 |
| ⑤ | 深灰渐变背景（纯净） | `pure dark studio gradient background, no landscape` | 0.5→3 |
| ⑥ | 哑光+金属+半透明 | `matte low-gloss housing, brushed metal accents, translucent polycarbonate parts` | 1→2.5 |
| ⑦ | 三点棚拍光（光位落地） | `key fill rim three-point studio lighting` | 1.5→2.5 |
| ⑧ | 单工业强调色 | `single industrial accent color on dark gray` | 2.5→3 |
| ⑨ | anatomy 营销美学 | `anatomy-marketing engineering aesthetic` | 2.5→3 |
| ⑩ | 无文字（强负向） | `no text no letters no numbers no labels no watermarks, clean unlabeled surfaces` | 0→2.5 |

> v1.1.0 修订依据：首次成图视觉自检 19.5/30，暴露伪文字（最严重）、对角漂移、
> 三段模糊、环境层「农田」污染背景、半透明缺失。修订后 26/30。
> 标题/编号/角标等**真实文字系统**属合成标注层（AtlasAnnotate 真实数据标注导出），
> 不属底图职责——底图严格 no-text，避免模型伪文字。

**层→视图槽位映射**（atlas）：IDENTITY←identity；STRUCTURE←architecture/geometry/mechanism；
PARTS←components/hardware；SURFACE←materials。environment 不入 atlas（view-conflict），
hero/scene 类视图保留。

## 3. 预算引擎与降档顺序

```
满配额组装（QUOTAS: id 1/arch 2/geo 1/mech 2/comp 3/mat 2/hw 2/env 1，must 优先 → visualizability 降序，仅取 ≥2）
  ├─ ≤ 预算 → 采纳
  ├─ > 预算 → 配额减半重组装（骨架不动）
  └─ 仍超  → 最小集（骨架 + identity 1 条）
```

- 层内选择：`priority==must` 优先，同优先级按 `visualizability` 降序；`visualizability<2` 永不入选。
- 报告 `meta.forge_report`：`{view, style, limit, total_len, included, dropped:[{layer,zh,reason}], forge_version}`，
  reason ∈ quota / view-conflict / minimal-fallback。

## 4. 模板改版标准操作流程（SOP）

1. 改 `app/services/prompt_forge.py` 常量（VIEW_SPECS/QUOTAS/STYLE_PRESETS），**升 FORGE_VERSION**；
2. 同步 `tests/test_prompt_forge.py` 的 ATLAS_ELEMENTS 断言（`python3 -m unittest tests.test_prompt_forge`，须全绿）；
3. 用真实会话 schema 走 `POST /assets/generate {schema_asset_id, view}` 生成一张图鉴；
4. prompt 全文 + forge_report + 成图呈报，与 8 实例人工对照（自动断言 + 人工抽检）；
5. 确认后重建部署（后端改常量需重启 uvicorn；前端仅展示无需改）。

## 5. 相关文件

| 文件 | 职责 |
|---|---|
| `backend/app/services/prompt_forge.py` | 骨架/配额/限制/风格常量 + build_prompt 预算引擎 |
| `backend/tests/test_prompt_forge.py` | golden 断言（8 项：限长/要素全/配额must/降档/低分排除/视图冲突/全视图/风格） |
| `backend/app/api/v1/endpoints/qx_assets.py` | generate / generate-suite 端点（schema_asset_id 同源路径） |
| `qx-deerflow/packages/qx_tools/qx_tools/design.py` | agent 工具同 schema_asset_id 入参 |
| `deer-flow/frontend/src/core/qx/api.ts` | generateFromSchema / generateSuite 客户端 |
| `deer-flow/frontend/src/core/qx/views.ts` | 降级为纯展示常量（视图名/描述） |
| `deer-flow/frontend/src/components/workspace/qx/keyword-schema-card.tsx` | 生图对话框 + 组装报告展示 |
| `deer-flow/frontend/src/components/workspace/qx/qx-task-panel.tsx` | 三态生图卡 + 「查看提示词」审计入口 |
