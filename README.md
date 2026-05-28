# 🔬 Research Agent

> AI 驱动的行业研究报告自动生成系统 —— 从信息搜集、知识检索到精美排版 PDF，全流程自动化。

[![Python](https://img.shields.io/badge/Python-3.10-blue.svg)](https://www.python.org/)
[![LangChain](https://img.shields.io/badge/LangChain-0.2+-green.svg)](https://www.langchain.com/)
[![Chroma](https://img.shields.io/badge/Chroma-0.5+-orange.svg)](https://www.trychroma.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 📖 项目简介

Research Agent 自动完成行业研究报告的端到端生成：输入一个研究主题，系统自动执行网络搜索、网页内容抓取、本地知识库构建、大纲规划、逐章深度撰写、学术级引用溯源，最终输出专业排版的 Markdown 和印刷级 PDF。

**核心能力：**

- 🔍 **自动信息搜集** — 调用 Tavily 搜索引擎获取最新行业资讯
- 🕷️ **网页内容抓取** — 通过 Firecrawl 将网页转为结构化 Markdown
- 📚 **双引擎知识库** — Chroma 向量检索 + BM25 关键词检索混合召回
- 🧠 **AI 深度撰写** — DeepSeek 大模型基于检索资料撰写专业研报
- 📎 **学术级引用溯源** — 自动编号、角标嵌入、参考资料章节
- 🎯 **信息源分级排序** — 区分权威来源与 UGC 内容，自动加权排序
- 🎨 **多模态概念图** — 自动生成产品概念设计图
- 📄 **印刷级 PDF** — WeasyPrint 渲染，精美封面 + 专业排版

---

## 🏗️ 架构说明

```
research_agent/
├── app/
│   ├── orchestrator/          # 🔑 主工作流编排
│   │   └── workflow.py        #    全流程入口：知识库→大纲→撰写→PDF
│   │
│   ├── planner/               # 📋 规划层
│   │   ├── outline_generator.py  # 大纲生成（固定6大章节）
│   │   ├── query_planner.py      # 查询规划：章节→多检索词拆解
│   │   └── compare_query.py      # 检索策略对比评测
│   │
│   ├── search/                # 🔍 搜索层
│   │   └── tavily_search.py      # Tavily 网络搜索 API
│   │
│   ├── crawler/               # 🕷️ 抓取层
│   │   └── firecrawl_crawler.py  # Firecrawl 网页内容抓取
│   │
│   ├── rag/                   # 📚 检索增强生成（核心）
│   │   ├── chunker.py            # 文本分块（RecursiveCharacterTextSplitter）
│   │   ├── vector_store.py       # Chroma 向量库 + BM25 持久化
│   │   ├── retriever.py          # 混合检索：Vector+BM25+RRF+SourceRanking
│   │   ├── citation_utils.py     # 引用编号与参考资料解析引擎
│   │   └── rag_pipeline.py       # 知识库构建完整管道
│   │
│   ├── context/               # 📝 上下文处理
│   │   └── context_builder.py    # 搜索结果格式化
│   │
│   ├── report/                # 📄 报告生成
│   │   ├── section_writer.py     # 章节撰写（RAG文本 + 多模态绘图分流）
│   │   ├── markdown_formatter.py # Markdown 报告组装
│   │   └── pdf_generator.py      # WeasyPrint 印刷级 PDF（精美CSS封面）
│   │
│   ├── retrieval/             # 📥 简化研究管道
│   │   └── research_pipeline.py  # 搜索+抓取聚合（备用）
│   │
│   └── llm/                   # 🤖 大模型接口
│       ├── client.py             # DeepSeek Chat + Pollinations 图片生成
│       └── client01.py           # 本地 Qwen2.5-7B-Instruct 备用方案
│
├── tests/                     # 🧪 评测脚本
│   ├── eval_retrieval.py         # 纯向量 vs 混合检索对比
│   ├── eval_ranking.py           # Source Ranking 权重算法验证
│   └── eval_citation.py          # 引用溯源引擎单元测试
│
├── outputs/                   # 📦 输出目录
│   ├── v2(citation)_{topic}_report.md
│   ├── v2(citation)_{topic}_report.pdf
│   └── images/{topic}_concept.png
│
├── chroma_db/                 # 向量数据库持久化
├── bm25_db/                   # BM25 语料持久化
├── requirements.txt
└── .env                       # API 密钥配置
```

---

## 🚀 安装方式

### 环境要求

- Python 3.10+
- pip

### 安装步骤

```bash
# 1. 克隆项目
git clone <repo-url>
cd research_agent

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置 API 密钥（创建 .env 文件）
cat > .env << EOF
DEEPSEEK_API_KEY=sk-your-deepseek-key
TAVILY_API_KEY=tvly-your-tavily-key
FIRECRAWL_API_KEY=fc-your-firecrawl-key
EOF
```

### API 密钥获取

| 服务 | 用途 | 获取地址 |
|------|------|----------|
| DeepSeek | 大模型文本生成 | https://platform.deepseek.com |
| Tavily | 网络搜索 | https://tavily.com |
| Firecrawl | 网页内容抓取 | https://firecrawl.dev |

---

## 📘 使用示例

### 一键运行

```bash
cd research_agent
python app/orchestrator/workflow.py
```

在 [`workflow.py`](app/orchestrator/workflow.py) 底部修改 `topic` 变量即可切换研究主题：

```python
if __name__ == "__main__":
    topic = "AI眼镜行业"          # 修改这里
    run_workflow(topic)
```

### 单独测试各模块

```bash
# 知识库构建
python app/rag/rag_pipeline.py

# 混合检索测试
python app/rag/retriever.py

# 大纲生成测试
python app/planner/outline_generator.py

# 查询规划测试
python app/planner/query_planner.py

# 检索策略评测
python tests/eval_retrieval.py

# Source Ranking 算法评测
python tests/eval_ranking.py

# 引用溯源引擎评测
python tests/eval_citation.py
```

---

## 🔄 工作流说明

```mermaid
flowchart TD
    A[输入研究主题] --> B["1. 构建知识库"]
    B --> B1[Tavily 网络搜索]
    B1 --> B2[Firecrawl 抓取前3个网页]
    B2 --> B3[文本分块 - chunk_size=1200]
    B3 --> B4[Chroma 向量库 + BM25 持久化]
    
    B4 --> C["2. 生成大纲"]
    C --> C1[固定6大章节模板]
    
    C1 --> D["3. 逐章撰写"]
    D --> D1{章节类型?}
    D1 -->|图鉴/生图/概念图| D2A[LLM 生成英文图像 Prompt]
    D2A --> D2B[Pollinations API 生成概念图]
    D2B --> D2C[返回图片 Markdown]
    D1 -->|文本章节| D3A["混合检索: Vector + BM25"]
    D3A --> D3B["RRF 融合 + Source Ranking 重排"]
    D3B --> D3C[Citation 引擎编号上下文]
    D3C --> D3D[LLM 撰写含脚注角标内容]
    D3D --> D3E[解析角标 → 组装参考资料]
    
    D2C --> E["4. 组装报告"]
    D3E --> E
    E --> E1[Markdown 拼接]
    E1 --> E2[保存 .md 文件]
    
    E2 --> F["5. 生成 PDF"]
    F --> F1[markdown2 转 HTML]
    F1 --> F2[注入精美 CSS + 封面]
    F2 --> F3[WeasyPrint 渲染 PDF]
```

### 关键机制详解

#### 混合检索
同时执行两种互补检索策略：
- **向量检索**（Chroma）— 利用 `bge-small-zh-v1.5` 捕捉语义相似度
- **关键词检索**（BM25 + Jieba 分词）— 精确匹配专有名词和技术术语

#### RRF 融合排序
采用 Reciprocal Rank Fusion 算法融合两路结果，同时引入 **Source Ranking** 信息源分级权重：

| 级别 | 权重 | 来源类型 | 示例 |
|------|------|----------|------|
| T0 | ×1.5 | PDF 报告、政府网站、交易所 | `.pdf`, `.gov`, `sse.com.cn` |
| T1 | ×1.2 | 专业商业媒体、深度研报 | `36kr.com`, `caixin.com`, `huxiu.com` |
| T2 | ×1.0 | 普通新闻网站 | 默认 |
| T3 | ×0.5 | UGC 社区、自媒体 | `zhihu.com`, `weibo.com`, `xiaohongshu.com` |

#### 引用溯源
1. **阶段一**：URL 去重编号，同一来源的多个 Chunk 共享一个编号
2. **阶段二**：LLM 在正文中使用 `[^n]` 格式的脚注角标
3. **阶段三**：正则解析所有使用过的编号，自动在文末拼接「参考资料」章节

#### 多模态绘图分流
当章节标题包含「图鉴」「生图」「概念图」关键词时，自动切换为绘图管道：
1. LLM 将研究主题转化为英文工业设计 Prompt
2. 调用 Pollinations API（基于 FLUX 模型）生成概念图
3. 以 Markdown 图片语法嵌入报告

---

## 📊 输出结果示例

运行完成后，在 `outputs/` 目录生成以下文件：

```
outputs/
├── v2(citation)_{topic}_report.md      # Markdown 报告（含引用角标）
├── v2(citation)_{topic}_report.html    # 中间 HTML
├── v2(citation)_{topic}_report.pdf     # 印刷级 PDF（精美封面+排版）
└── images/
    └── {topic}_concept.png             # 产品概念设计图
```

### 报告章节结构

```markdown
# {研究主题}

## 1. 产品设计理念
## 2. 使用场景
## 3. 现有产品分析
## 4. 市场分析
## 5. 人的使用习惯
## 6. 产品概念简易图鉴

---

### 📚 参考资料
[^1]: 来源链接: <https://...>
[^2]: 来源链接: <https://...>
```

---

## 🧪 评测体系

项目内置三套自动化评测脚本：

| 脚本 | 评测目标 | 对比维度 |
|------|----------|----------|
| `eval_retrieval.py` | 检索质量 | 纯向量检索 vs 混合检索（Vector + BM25 + RRF） |
| `eval_ranking.py` | 排序公平性 | 无权重 RRF vs 加权 Source Ranking RRF |
| `eval_citation.py` | 引用准确性 | URL 去重编号、角标解析、参考资料组装 |

运行方式：

```bash
cd research_agent
python tests/eval_retrieval.py    # 输出: tests/retrieval_comparison_result.md
python tests/eval_ranking.py      # 输出: tests/source_ranking_result.md
python tests/eval_citation.py     # 控制台输出
```

---

## 🗺️ 后续规划

- [ ] **动态大纲生成** — 当前为固定6章节模板，支持 LLM 根据主题自动规划章节
- [ ] **多模型适配** — 抽象 LLM Provider 接口，支持 OpenAI / Claude / 本地模型切换
- [ ] **本地搜索增强** — 支持 SearXNG 等自部署搜索引擎，降低 API 依赖
- [ ] **增量知识库更新** — 避免每次运行都重建整个向量库
- [ ] **报告模板自定义** — 支持用户自定义章节结构和排版风格
- [ ] **多轮交互编辑** — 支持用户对生成内容提出修改意见并迭代
- [ ] **PDF 中文排版优化** — 引入更丰富的中文字体支持
- [ ] **更多检索评测指标** — 引入 NDCG、MAP 等标准检索评测指标
- [ ] **章节任务状态追踪** — 章节撰写子任务异步化，确保 Celery 任务状态正确更新
- [ ] **BM25 语料持久化路径统一** — 修复 Worker 进程中 BM25 语料加载路径不一致的问题

---

## 📅 每日工作日志 / Daily Changelog

> 记录每日功能更新与待优化内容（中文 + English）。

### 2026-05-28 / May 28, 2026

#### ✨ 每日功能更新 / Daily Feature Updates

| # | 更新内容 | 文件/模块 | 说明 |
|---|---------|-----------|------|
| 1 | 🐛 **修复 `name 'asyncio' is not defined` 运行时错误** | [`app/core/celery_db.py`](backend/app/core/celery_db.py:11) | `update_project_status_sync` 调用 `asyncio.run()` 但模块缺少 `import asyncio`，导致 Celery Worker 在 `STEP 5/6 build_report_markdown` 阶段崩溃。已添加 `import asyncio`。 |
| 2 | ✅ **全流程 6 步工作流端到端验证通过** | [`app/tasks/report_workflow.py`](backend/app/tasks/report_workflow.py) | 以"高端乳制品"为主题，完整运行 6 步工作流：搜索(Tavily+Firecrawl 3 URLs) → 知识库(21 Chunks) → 大纲(6章节) → 章节撰写(DeepSeek API) → Markdown 组装(11KB) → PDF 渲染(WeasyPrint, 717KB) + 概念图生成。总耗时约 162 秒。 |
| 3 | 🔄 **Celery Worker 进程重启 & 数据库重置** | — | 清除旧 Worker 进程，重启新 Worker；数据库重置为 `PENDING` 状态后重新提交任务，成功完成全流程。 |
| 4 | 📁 **输出文件验证** | [`backend/outputs/`](backend/outputs/) | 确认 PDF 报告（717KB）及其配套 Markdown、HTML、概念图文件均已正确生成并存档。 |

```bash
# 本次运行输出文件清单
backend/outputs/
├── 高端乳制品_report_20260529_002319.md      # Markdown (11KB)
├── 高端乳制品_report_20260529_002319.html    # HTML 中间文件
├── 高端乳制品_report_20260529_002319.pdf     # 印刷级 PDF (717KB)
└── images/
    └── 高端乳制品_concept.png                 # 产品概念设计图
```

#### 🎯 每日待优化内容 / Daily Optimization Items

| # | 问题描述 | 影响 | 建议修复方向 |
|---|---------|------|-------------|
| 1 | **BM25 语料加载失败 → 降级为纯向量检索** | 非关键，混合检索退化为纯向量检索，召回精度下降 | 统一 Worker 进程中的 `bm25_db/docs.pkl` 持久化路径，确保 `vector_store.py` 中的 `save_bm25_corpus()` 写入位置与 `retriever.py` 中 `retrieve()` 读取位置一致 |
| 2 | **章节撰写子任务状态未正确更新** | 6个章节撰写任务在数据库中始终为 `PENDING`，无法区分已完成/进行中 | `report_workflow.py` 中 `write_single_section` 以同步方式直接调用，应改为通过 `send_task()` 异步投递，并在 Celery 回调中更新 `section_tasks` 状态 |
| 3 | **数据库 CHECK 约束使用大写枚举值** | 手动 SQL 更新易因大小写错误触发 `CHECK constraint failed` | 建议在 `ProjectStatus` 枚举中同时支持大小写不敏感解析，或统一在应用层强制大写转换 |
| 4 | **`build_report_markdown` 中的 `asyncio.run()` 开销** | 每次调用都新建事件循环，高频场景可能有性能损耗 | 考虑在 Worker 启动时创建全局事件循环，或改用 `nest_asyncio` 补丁 |

---

<!-- ============================================================ -->
<!--  ENGLISH VERSION (每日工作日志 / Daily Changelog) -->
<!-- ============================================================ -->

### May 28, 2026 — Daily Changelog (English)

#### ✨ Feature Updates

| # | Update | Module | Details |
|---|--------|--------|---------|
| 1 | 🐛 **Fixed `name 'asyncio' is not defined` runtime error** | [`app/core/celery_db.py`](backend/app/core/celery_db.py:11) | `update_project_status_sync()` called `asyncio.run()` without importing `asyncio`, causing the Celery Worker to crash at `STEP 5/6 (build_report_markdown)`. Fixed by adding `import asyncio` at line 11. |
| 2 | ✅ **End-to-end 6-step workflow verified** | [`app/tasks/report_workflow.py`](backend/app/tasks/report_workflow.py) | Successfully ran the full workflow on topic "高端乳制品" (High-end Dairy Products): Search (Tavily+Firecrawl, 3 URLs crawled) → Knowledge Base (21 chunks) → Outline (6 sections) → Section Writing (DeepSeek API) → Markdown Assembly (11KB) → PDF Rendering via WeasyPrint (717KB) + Concept Image. Total time: ~162s. |
| 3 | 🔄 **Celery Worker restart & DB reset** | — | Killed stale Worker processes, launched a fresh Worker, reset DB project status to `PENDING`, re-submitted the task, and completed the full pipeline. |
| 4 | 📁 **Output file verification** | [`backend/outputs/`](backend/outputs/) | Confirmed that the PDF report (717KB), Markdown, HTML, and concept image were correctly generated and archived. |

#### 🎯 Optimization Items

| # | Issue | Impact | Suggested Fix |
|---|-------|--------|---------------|
| 1 | **BM25 corpus load failure → falls back to vector-only retrieval** | Non-critical; hybrid retrieval degrades to pure vector search, reducing recall precision | Unify the BM25 persistence path so `save_bm25_corpus()` in `vector_store.py` writes to the same location that `retrieve()` in `retriever.py` reads from within the Worker process |
| 2 | **Section writing subtask status not updated** | All 6 section-writing tasks remain `PENDING` in the DB instead of `COMPLETED` | Change synchronous `write_single_section` calls in `report_workflow.py` to async Celery `send_task()` invocations, updating `section_tasks` status via callbacks |
| 3 | **DB CHECK constraints use uppercase enum values** | Manual SQL updates risk `CHECK constraint failed` on case mismatch | Add case-insensitive parsing in `ProjectStatus` enum or enforce uppercase conversion at the application layer |
| 4 | **`asyncio.run()` overhead in `build_report_markdown`** | Creates a new event loop on each call; potential performance issue under high frequency | Use a global event loop initialized at Worker startup, or patch with `nest_asyncio` |

---

## 📄 许可证

MIT License
