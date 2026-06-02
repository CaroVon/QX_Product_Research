# 🔬 QX Product Research Agent

> **v0.1** — AI 驱动的产品分析报告自动生成系统：从信息搜集、知识检索到精美排版 PDF，全流程自动化。支持 Web 管理界面与异步任务队列，三栏式交互工作台。

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.136-green.svg)](https://fastapi.tiangolo.com/)
[![Celery](https://img.shields.io/badge/Celery-5.6.3-purple.svg)](https://docs.celeryq.dev/)
[![React](https://img.shields.io/badge/React-18.3-blue.svg)](https://react.dev/)
[![Vite](https://img.shields.io/badge/Vite-6.4-yellow.svg)](https://vitejs.dev/)
[![Redis](https://img.shields.io/badge/Redis-8.0-red.svg)](https://redis.io/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 📖 项目简介

输入一个产品/行业分析主题，系统自动执行网络搜索 → 网页抓取 → 知识库构建 → 大纲规划 → 逐章撰写 → 引用溯源，最终输出专业排版的 Markdown 和 **16:9 横版 PPT 风格 PDF**。

### 三大组件

| 组件 | 技术栈 | 说明 |
|------|--------|------|
| **🧠 研究引擎** `app/` | LangChain + Chroma + BM25 | 核心 RAG 管道与报告生成逻辑 |
| **⚙️ 后端服务** `backend/` | FastAPI + Celery + SQLite | REST API + 异步任务队列 + 持久化 |
| **🎨 前端界面** `frontend/` | React + Vite + TypeScript + Tailwind CSS | 三栏式交互工作台 |

### 核心能力

- 🔍 **自动信息搜集** — Tavily 搜索引擎获取最新行业资讯
- 🕷️ **网页内容抓取** — Firecrawl 将网页转为结构化 Markdown
- 📚 **双引擎知识库** — Chroma 向量检索 + BM25 关键词检索混合召回
- 🧠 **AI 深度撰写** — DeepSeek 大模型基于检索资料撰写专业研报
- 📎 **学术级引用溯源** — 自动编号、角标嵌入、参考资料章节
- 🎯 **信息源分级排序** — 区分权威来源与 UGC 内容，自动加权排序
- 🎨 **多模态概念图** — 硅基流动 FLUX.1 自动生成产品概念设计图
- 📄 **横版 PPT 风格 PDF** — WeasyPrint 渲染，16:9 宽屏比例
- 🖥️ **实时运行日志** — 终端控制台风格时间轴
- 🔄 **交互式状态机** — 资料审核 → 大纲确认 → AI 撰写 → PDF 下载
- 🌐 **三栏式工作台** — 大纲目录 + 块级编辑器 + 实时日志/引用溯源面板
- 🗑️ **项目管理** — 支持删除项目及关联数据
- ⚡ **异步任务队列** — Celery + Redis（Windows 线程池模式）

---

## 🚀 快速开始

### 环境要求

- Python 3.10+
- Node.js 18+
- Redis（推荐 8.0+，支持 3.x 需额外配置 `broker_transport_options`）

### 一键启动（推荐）

```batch
# 双击运行项目根目录下的批处理文件：
start_project.bat
```

自动完成：Redis 检测 → FastAPI (8000) → Celery Worker → Vite 前端，弹出 3 个独立窗口。

### 手动启动

```bash
# 1. 安装依赖
pip install -r requirements.txt
cd frontend && npm install && cd ..

# 2. 配置 API 密钥（参考 backend/.env.example）
cp backend/.env.example backend/.env
# 编辑 backend/.env 填入密钥

# 3. 启动 Redis
redis-server

# 4. 启动后端 (端口 8000)
cd backend
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# 5. 启动 Celery Worker (Windows 线程池模式)
celery -A app.core.celery_app.celery_app worker --loglevel=info --concurrency=4 --pool=threads

# 6. 启动前端 (端口 5173)
cd frontend && npm run dev
```

### 历史项目修复

```bash
cd backend && python fix_stuck_projects.py
```

### 浏览器访问

| 服务 | 地址 |
|------|------|
| **前端界面** | **http://localhost:5173** |
| API 文档 (Swagger) | http://localhost:8000/docs |
| 健康检查 | http://localhost:8000/health |

---

## 🌐 API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/v1/projects` | 创建新项目 |
| `GET` | `/api/v1/projects` | 获取项目列表 |
| `DELETE` | `/api/v1/projects/{id}` | 🆕 删除项目及关联数据 |
| `GET` | `/api/v1/projects/{id}/status` | 查询项目进度 |
| `GET` | `/api/v1/projects/{id}/sources` | 获取资料列表（交互节点1） |
| `POST` | `/api/v1/projects/{id}/review-sources` | 提交资料审核 |
| `POST` | `/api/v1/projects/{id}/approve-outline` | 确认大纲（交互节点2） |
| `GET` | `/api/v1/projects/{id}/blocks` | 获取文档块列表 |
| `GET` | `/api/v1/projects/{id}/content` | 获取报告全文 |
| `GET` | `/api/v1/projects/{id}/logs` | 获取实时运行日志 |
| `GET` | `/api/v1/projects/{id}/stream-draft` | SSE 流式草稿输出 |
| `GET` | `/api/v1/projects/{id}/download` | 下载 PDF 报告 |
| `POST` | `/api/v1/editor/revise` | Inline AI 划词改写 |

---

## 🔄 状态机

```
PREPARING_DATA ──(自动)──→ WAITING_FOR_SOURCES  🛑 用户审核资料
                                 │
                    POST /review-sources
                                 ↓
                       PREPARING_OUTLINE ──(自动)──→ WAITING_FOR_OUTLINE  🛑 用户确认大纲
                                                           │
                                              POST /approve-outline
                                                           ↓
                                                     DRAFTING ──(自动)──→ COMPLETED ✅
```

---

## 🧪 测试

```bash
# 集成测试
cd backend && python -m pytest tests/test_api_integration.py -v

# 评测脚本
python tests/eval_retrieval.py
python tests/eval_ranking.py
python tests/eval_citation.py
```

---

## 📁 项目结构（精简版）

```
QX_agent/
├── app/                         # 核心研究引擎 (RAG/LLM/PDF)
├── backend/                     # FastAPI 后端
│   ├── app/api/v1/endpoints/    # REST API 端点
│   ├── app/models/              # ORM 模型
│   ├── app/tasks/               # Celery 异步任务
│   ├── alembic/                 # 数据库迁移
│   └── local_dev.db             # SQLite 开发数据库
├── frontend/                    # React 前端
│   └── src/
│       ├── pages/               # Dashboard / Workspace / Report
│       ├── components/          # ProjectCard / Editor / Timeline
│       └── hooks/               # React Query hooks
├── tests/                       # 评测脚本
├── start_project.bat            # 一键启动脚本
├── requirements.txt             # Python 依赖
└── .env                         # API 密钥配置
```

---

## 🔧 架构关键修复 (v0.1)

本次版本修复了两个系统级缺陷：

1. **Windows spawn 池崩溃** — Celery 强制线程池模式（`--pool=threads`），解决 Python 3.14 `spawn` 下 `trace._localized` 解包崩溃
2. **SSE ORM 状态过期死循环** — `stream_draft` 端点循环内强制 `await db.refresh(project)` 拉取最新数据库状态
3. **Redis 协议兼容** — 旧版 Redis 3.x 不支持 HELLO/RESP3，已修复代理地址和协议降级配置

---

## 📄 License

MIT License
