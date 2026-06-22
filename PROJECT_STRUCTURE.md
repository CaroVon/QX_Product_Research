# QX Product Research Agent — 项目脚本架构文档

> **版本**: v0.2 | **更新**: 2026-06-22
>
> 本文档描述项目的完整脚本结构、每段脚本的核心代码片段及其在系统中的作用。

---

## 目录

1. [总览：三层架构](#1-总览三层架构)
2. [根目录文件一览](#2-根目录文件一览)
3. [启动与运维脚本](#3-启动与运维脚本)
4. [后端应用层 (backend/app/)](#4-后端应用层-backendapp)
5. [异步任务引擎 (backend/app/tasks/)](#5-异步任务引擎-backendapptasks)
6. [数据仓库层 (backend/app/repositories/)](#6-数据仓库层-backendapprepositories)
7. [研究引擎 (app/)](#7-研究引擎-app)
8. [前端架构 (frontend/src/)](#8-前端架构-frontendsrc)
9. [数据模型 (backend/app/models/)](#9-数据模型-backendappmodels)
10. [状态机流转全景](#10-状态机流转全景)
11. [测试与评测](#11-测试与评测)

---

## 1. 总览：三层架构

```
┌─────────────────────────────────────────────────────────┐
│                   Frontend (React + Vite)               │
│              三栏工作台 + Tiptap 编辑器 + SSE            │
│                    http://localhost:5173                 │
└──────────────────────┬──────────────────────────────────┘
                       │ HTTP REST + SSE
┌──────────────────────▼──────────────────────────────────┐
│                 Backend (FastAPI + Celery)               │
│          状态机编排 + 异步任务队列 + REST API             │
│                    http://localhost:8000                 │
└──────────────────────┬──────────────────────────────────┘
                       │ Python import
┌──────────────────────▼──────────────────────────────────┐
│              Research Engine (app/)                      │
│  搜索→抓取→切片→向量库+BM25→RAG检索→大纲→撰写→PDF       │
└─────────────────────────────────────────────────────────┘
```

---

## 2. 根目录文件一览

```
QX_product_agent/
├── .claude/                    # Claude Code 配置（hooks / settings）
├── .gitignore
├── README.md                   # 项目 README
├── PROJECT_STRUCTURE.md        # 本文档
├── prd.md                      # 产品需求文档 (PRD)
├── requirements.txt            # Python 依赖清单
├── command.txt                 # 快速启动命令备忘
├── test_llm.py                 # LLM 连通性测试脚本
│
├── start_all.sh                # WSL 全模块一键启动
├── stop_all.sh                 # WSL 全模块停止
├── start_project.bat           # Windows 桌面入口（双击→WSL）
│
├── app/                        # 研究引擎（算法核心）
├── backend/                    # FastAPI 后端 + Celery 任务队列
├── frontend/                   # React + Vite 前端
├── tests/                      # 评测脚本（检索/排序/引用质量）
├── fix/                        # 问题修复记录
├── memory/                     # Claude Code 持久记忆
└── venv/                       # Python 虚拟环境
```

---

## 3. 启动与运维脚本

### 3.1 `start_all.sh` — 全模块一键启动 (WSL)

**作用**: 依次检测并启动 Redis、Python venv、FastAPI、Celery Worker、Vite 前端。

```bash
# 核心片段：Redis 容器保活
if docker ps --format '{{.Names}}' | grep -q '^redis-qx$'; then
    ok "Redis 容器已运行"
else
    docker run -d --name redis-qx -p 6379:6379 --restart unless-stopped redis:7-alpine
fi

# 核心片段：清理端口冲突
OLD_PID=$(ss -tlnp | grep ':8000' | grep -oP 'pid=\K[0-9]+' | head -1)
[ -n "$OLD_PID" ] && kill "$OLD_PID"

# 核心片段：启动 FastAPI（后台 + 日志重定向，稳定模式 / 无 --reload）
nohup uvicorn app.main:app --host 0.0.0.0 --port 8000 \
    > "$RUNTIME_DIR/api.log" 2>&1 &

# 核心片段：启动 Celery（Windows 线程池模式，避免 spawn 崩溃）
nohup celery -A app.core.celery_app.celery_app worker \
    --loglevel=info --concurrency=4 --pool=threads \
    > backend/celery.log 2>&1 &

# 核心片段：启动 Vite 前端
nohup npm run dev > frontend/vite.log 2>&1 &

# 核心片段：异步轮询等待后端就绪（ML 模型冷启动需 30-60s）
for i in $(seq 1 60); do
    curl -s http://localhost:8000/health > /dev/null 2>&1 && break
    sleep 1
done
```

### 3.2 `stop_all.sh` — 全模块停止

```bash
# 核心片段：按端口精准杀进程
PID=$(ss -tlnp | grep ':8000' | grep -oP 'pid=\K[0-9]+' | head -1)
[ -n "$PID" ] && kill "$PID"
pkill -f "celery.*worker"
PID=$(ss -tlnp | grep ':5173' | grep -oP 'pid=\K[0-9]+' | head -1)
[ -n "$PID" ] && kill "$PID"
```

### 3.3 `start_project.bat` — Windows 入口

```batch
@echo off
chcp 65001 >nul 2>&1
:: 通过 WSL 调用 bash 启动脚本
wsl -e bash /mnt/d/DEV/agents/QX_product_agent/start_all.sh
pause
```

**设计意图**: Windows 用户双击 bat → 内部委托 WSL 执行 bash 脚本。所有环境（Python、Node、Redis）均在 WSL 内运行，数据统一落在 D 盘。

### 3.4 `test_llm.py` — LLM 连通性快速验证

用于验证 DeepSeek API Key 配置是否正确、模型是否可达的小型诊断脚本。

---

## 4. 后端应用层 (backend/app/)

### 4.1 `backend/app/main.py` — FastAPI 应用工厂

这是整个后端的**唯一入口**。

```python
# 核心片段：双路径注入 —— 同时加入 backend/ 和项目根目录
# backend/ 优先（app.core/app.models/app.schemas 等新模块），
# 项目根目录次之（app.rag/app.search/app.crawler 等研究引擎）。
# 两者缺一不可：从 backend/ 启动时 CWD=backend/ 找不到 app.rag；
# 从项目根启动时 CWD=project_root 找不到 backend/app 新增模块。
_backend_dir = Path(__file__).resolve().parent.parent
_project_root = _backend_dir.parent
for _d in (str(_project_root), str(_backend_dir)):
    if _d not in sys.path:
        sys.path.insert(0, _d)
# 结果：sys.path[0] = backend/（优先），sys.path[1] = 项目根目录

# 核心片段：Windows asyncio 兼容（Python 3.14+ 自动适配）
if sys.platform == "win32" and sys.version_info < (3, 14):
    asyncio.set_event_loop_policy(WindowsSelectorEventLoopPolicy())

# 核心片段：生命周期管理 —— 启动时自动建表
@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("[DB] 数据库表已就绪（create_all 幂等操作）")
    yield
    await engine.dispose()

# 核心片段：注册路由 + CORS + 静态文件
app = FastAPI(title="Product Analysis Agent API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], ...)
app.include_router(v1_router, prefix="/api/v1")
app.mount("/outputs", StaticFiles(directory=settings.OUTPUT_DIR))
```

### 4.2 `backend/app/core/config.py` — 配置中心

**作用**: Pydantic V2 Settings 单例，从 `.env` 自动加载所有配置项，启动时校验关键 API Key。

```python
# 核心片段：.env 文件搜索链
def _find_env_file() -> str:
    candidates = [
        Path(__file__).parent.parent.parent / ".env",       # backend/.env
        Path(__file__).parent.parent.parent.parent / "backend" / ".env",
        Path(".env"),
    ]

# 核心片段：异步/同步数据库 URL 双通道
@property
def DATABASE_URL_ASYNC(self) -> str:
    if self.DATABASE_URL:
        return self.DATABASE_URL
    return f"postgresql+asyncpg://{user}:{pwd}@{host}:{port}/{db}"

# 核心片段：启动时 fail-fast 校验关键 Key
@model_validator(mode="after")
def validate_critical_config(self):
    missing = []
    if not self.DEEPSEEK_API_KEY: missing.append("DEEPSEEK_API_KEY")
    if not self.TAVILY_API_KEY: missing.append("TAVILY_API_KEY")
    if missing:
        raise ValueError(f"❌ 关键 API Key 未配置：\n  • {'  • '.join(missing)}")
```

配置项涵盖：数据库 URL、Redis/Celery broker、DeepSeek API、Tavily Search、Firecrawl、Embedding 模型路径、Chroma/BM25 持久化目录、输出目录等。

### 4.3 `backend/app/core/database.py` — 异步数据库引擎

**作用**: 创建 SQLAlchemy 2.0 异步引擎，SQLite 与 PostgreSQL 双模式。

```python
# 核心片段：SQLite 特殊处理（NullPool + WAL 模式 + check_same_thread）
if _is_sqlite:
    engine = create_async_engine(
        settings.DATABASE_URL_ASYNC,
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")     # 提升并发写性能
        cursor.execute("PRAGMA foreign_keys=ON;")

# 核心片段：FastAPI 依赖注入 —— 自动 commit/rollback
async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

### 4.4 `backend/app/core/celery_app.py` — Celery 应用实例

```python
# 核心片段：配置 Redis broker + 结果后端
celery_app = Celery("research_agent")
celery_app.conf.update(
    broker_url=settings.CELERY_BROKER_URL,
    result_backend=settings.CELERY_RESULT_BACKEND,
    task_serializer="json",
    result_expires=3600,
    task_acks_late=True,           # 任务完成后才确认
    worker_prefetch_multiplier=1,  # 公平调度
    worker_max_tasks_per_child=50, # 防止内存泄漏
)
# 自动发现所有 task 模块
celery_app.autodiscover_tasks([
    "app.tasks.search_tasks",
    "app.tasks.knowledge_tasks",
    "app.tasks.writing_tasks",
    "app.tasks.render_tasks",
    "app.tasks.report_workflow",
])
```

> **关键设计**: `--pool=threads` 是 Windows 必需参数。Python 3.14 的 `spawn` 多进程模式会导致 `trace._localized` 解包崩溃。

### 4.5 `backend/app/core/celery_db.py` — Celery Worker 数据库层

```python
# 核心片段：提供同步引擎（Celery worker 在同步上下文中运行）
@lru_cache()
def get_sync_engine():
    return create_engine(settings.DATABASE_URL_SYNC, echo=settings.DEBUG)

# 核心片段：爬取数据的临时文件路径
def get_crawled_data_path(project_id: str) -> str:
    return os.path.join(settings.OUTPUT_DIR, f"crawled_data_{project_id}.json")
```

### 4.6 `backend/app/api/v1/router.py` — 路由聚合

```python
router = APIRouter()
router.include_router(projects.router)   # /api/v1/projects
router.include_router(editor.router)     # /api/v1/editor
```

### 4.7 `backend/app/api/v1/endpoints/projects.py` — 核心业务 API（约 950 行）

**状态机三节点**的 REST 实现：

```python
# 节点1：创建项目 + 触发 Phase 1（搜索 → 等待审核资料）
@router.post("", response_model=ProjectCreateResponse, status_code=201)
async def create_project(body: ProjectCreateRequest, db: AsyncSession):
    project = Project(owner_id=current_user_id, topic=body.topic,
                      status=ProjectStatus.PREPARING_DATA)
    db.add(project)
    # 创建任务链：SEARCH → BUILD_KNOWLEDGE_BASE → GENERATE_OUTLINE
    for task_type, seq in [(TaskType.SEARCH, 1), ...]:
        db.add(Task(project_id=project.id, task_type=task_type, ...))
    # 提交 Celery 异步工作流
    celery_task = prepare_sources_workflow.delay(str(project.id))

# 节点1确认：用户审核资料 → 触发 Phase 2（大纲生成）
@router.post("/{project_id}/review-sources")
async def review_sources(project_id, body: SourceReviewRequest, db):
    # 状态校验：仅 WAITING_FOR_SOURCES 可操作
    if project.status != ProjectStatus.WAITING_FOR_SOURCES:
        raise HTTPException(409)
    # 筛选资料 + 保存 + 状态机推进 → PREPARING_OUTLINE
    project.status = ProjectStatus.PREPARING_OUTLINE
    celery_task = generate_outline_workflow.delay(str(project.id))

# 节点2确认：用户确认大纲 → 触发 Phase 3（逐章撰写）
@router.post("/{project_id}/approve-outline")
async def approve_outline(project_id, body: OutlineApproveRequest, db):
    if project.status != ProjectStatus.WAITING_FOR_OUTLINE:
        raise HTTPException(409)
    sections = _extract_sections_from_outline(body.outline)
    project.status = ProjectStatus.DRAFTING
    # 为每个章节创建 DocumentBlock 占位 + Task
    for idx, section_title in enumerate(sections):
        db.add(DocumentBlock(project_id=project.id, section_title=section_title,
                             order_index=(idx+1)*10, content=""))
    celery_task = run_draft_sections_workflow.delay(str(project.id))

# SSE 流式输出：轮询 DocumentBlock 表，逐条推送 section_chunk 事件
@router.get("/{project_id}/stream-draft")
async def stream_draft(project_id, db):
    async def event_generator():
        while wait_cycles < 300:
            await db.refresh(project)  # 强制刷新 —— 解决 ORM 状态过期死循环
            blocks = await db.execute(select(DocumentBlock).where(...))
            for block in blocks[last_block_count:]:
                yield f"event: section_chunk\ndata: {json.dumps(block_data)}\n\n"
            if project.status == ProjectStatus.COMPLETED:
                yield f"event: draft_complete\ndata: ...\n\n"
                return
            await asyncio.sleep(2)  # 2 秒轮询间隔
    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

### 4.8 `backend/app/api/v1/endpoints/editor.py` — Inline AI 编辑器 + 侧边栏对话

**1. `/revise` — AI 改写选中文本 (Inline AI Bubble)**

```python
@router.post("/revise", response_model=EditorReviseResponse)
async def revise_text(body: EditorReviseRequest):
    # 快捷指令映射
    quick_commands = {
        "expand": "请将以下内容扩展得更详细...",
        "simplify": "请将以下内容简化...",
        "polish": "请润色以下内容，使其更具专业产品分析感...",
    }
    instruction = quick_commands.get(body.instruction, body.instruction)
    # 使用 DeepSeek LLM + PM/UX 系统人设
    llm = get_llm()
    response = llm.invoke([
        SystemMessage(content="你是一名资深产品经理和用户体验专家..."),
        HumanMessage(content=f"{instruction}\n\n原文：\n{body.selected_text}")
    ])
```

**2. `/chat` — 侧边栏大模型流式对话（SSE + RAG 知识库注入）**

```python
_CHAT_WORK_SYSTEM = (
    "你是一个专业的产品分析师与报告撰写助手。"
    "请务必优先基于【项目知识库参考】或【编辑器选中文本参考】中的信息来客观、严谨地回答用户问题。"
    "如果是提取或总结任务，请直接列出核心主题，不要包含多余的寒暄。"
)

@router.post("/chat")
async def chat_with_editor(body: EditorChatRequest):
    # 拼接当前用户提问 + 编辑器选中文本
    current_content = body.message
    if body.selected_text:
        current_content += f"\n\n【编辑器选中文本参考】\n{body.selected_text}"

    # 🚀 RAG 检索：work 模式自动从 Chroma + BM25 召回 Top-5 切片
    if body.chat_mode == "work" or "test" in body.message.lower():
        try:
            rag_context = retrieve_context(
                query=body.message, k=5,
                project_id=str(body.project_id),  # per-project 隔离
            )
            if rag_context and rag_context.strip():
                current_content += f"\n\n【项目知识库参考（含本地文档）】\n{rag_context}"
        except Exception as e:
            logger.warning("editor/chat RAG 检索异常: %s", str(e))

    messages.append({"role": "user", "content": current_content})
    # → SSE 流式返回 LLM 回复
```

> **设计意图**: `/chat` 在 work 模式下先调用 `retrieve_context()` 从项目隔离的 Chroma + BM25 向量库中召回相关文档切片，再注入到 LLM 上下文中。这彻底打通了"本地上传 PDF → 切片入库 → 对话检索"的完整链路，解决了之前 LLM 不知道用户上传了什么文件的上下文断流 Bug。

### 4.9 `backend/app/schemas/__init__.py` — Pydantic 数据契约

所有请求/响应模型约 300 行，定义 API 的类型契约：

```python
class ProjectStatusResponse(BaseModel):
    project_id: uuid.UUID
    topic: str
    project_status: str
    outline_content: str | None
    progress: dict       # {total_tasks, completed_tasks, percentage, ...}
    current_step: dict | None
    tasks: list[dict]

class EditorReviseRequest(BaseModel):
    project_id: uuid.UUID
    block_id: uuid.UUID
    selected_text: str
    instruction: Literal["expand", "simplify", "polish",
                         "add-competitors", "formalize"] | str

class SSEDraftEvent(BaseModel):
    event_type: Literal["section_start", "section_chunk",
                        "section_complete", "draft_complete", "error"]
    section_title: str | None
    block: DocumentBlockResponse | None
    error: str | None
```

### 4.10 `backend/app/shared/outline_parser.py` — Markdown 大纲解析

```python
def extract_sections(outline: str) -> list[str]:
    """
    从 Markdown 大纲中提取 ## 二级标题作为章节名。
    正确处理：制表符分隔、行内 # 字符、排除 ### 三级标题。
    """
    sections = []
    for line in outline.split("\n"):
        line = line.strip().lstrip("\t")
        if line.startswith("## ") and not line.startswith("### "):
            title = line[3:].strip()
            title = re.sub(r"(\d+)[、.，。,]\s*", r"\1. ", title)
            sections.append(title)
    return sections
```

### 4.11 `backend/app/services/__init__.py` — 服务层占位

预留的业务服务层模块，用于从 API 端点中抽离复杂业务逻辑。

---

## 5. 异步任务引擎 (backend/app/tasks/)

### 5.1 `report_workflow.py` — 三阶段状态机编排器

这是整个系统的**核心编排逻辑**：

```python
# Phase 1：资料准备 → WAITING_FOR_SOURCES（等待用户审核）
@celery_app.task(bind=True, max_retries=3)
def prepare_sources_workflow(self, project_id: str):
    repo = ProjectRepo()
    repo.update_status(project_id, ProjectStatus.PREPARING_DATA)
    results = search_and_crawl(repo.get_project_topic(project_id))
    repo.save_sources(project_id, results)
    repo.update_status(project_id, ProjectStatus.WAITING_FOR_SOURCES)
    repo.append_log(project_id, "milestone",
                    f"已搜集 {len(results)} 条资料，请审核")

# Phase 2：大纲生成 → WAITING_FOR_OUTLINE（等待用户确认）
@celery_app.task(bind=True, max_retries=3)
def generate_outline_workflow(self, project_id: str):
    repo = ProjectRepo()
    build_knowledge_base(repo.get_project_topic(project_id), project_id)
    outline = generate_outline_task(repo.get_project_topic(project_id))
    repo.save_outline(project_id, outline)
    repo.update_status(project_id, ProjectStatus.WAITING_FOR_OUTLINE)

# Phase 3：逐章撰写 → 组装报告 → 生成 PDF → COMPLETED
@celery_app.task(bind=True, max_retries=3)
def run_draft_sections_workflow(self, project_id: str):
    repo = ProjectRepo()
    sections = extract_sections(repo.get_outline(project_id))
    for i, section in enumerate(sections):
        content = write_section_task(project_id, section)
        repo.save_sections(project_id, [(section, i, content)])
    pdf_path = generate_pdf_from_markdown(md_content, project_id)
    repo.update_pdf_path(project_id, pdf_path)
    repo.update_status(project_id, ProjectStatus.COMPLETED)
```

### 5.2 `search_tasks.py` — 搜索 + 抓取

```python
@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def search_and_crawl(self, topic: str) -> list[dict]:
    """Tavily 搜索 + Firecrawl 深度抓取，返回 [{content, url}, ...]"""
    search_results = tavily_search(topic, max_results=5)
    crawled = []
    for result in search_results[:5]:
        try:
            content = crawl_url(result["url"])  # Firecrawl 抓取
            crawled.append({"content": content, "url": result["url"],
                           "title": result.get("title", "")})
        except Exception:
            crawled.append({"content": result.get("content", ""),
                           "url": result["url"]})
    return crawled
```

### 5.3 `knowledge_tasks.py` — 知识库构建

```python
@celery_app.task(bind=True)
def build_knowledge_base(self, topic: str, project_id: str):
    """将爬取文本切片 → 嵌入 → 存入 Chroma 向量库 + BM25 索引"""
    data_path = get_crawled_data_path(project_id)
    with open(data_path) as f:
        sources = json.load(f)
    all_chunks = []
    for src in sources:
        chunks = chunk_text(src["content"], chunk_size=1200, chunk_overlap=200)
        all_chunks.extend(chunks)
    build_vector_store(all_chunks, project_id)  # Chroma 持久化
    build_bm25_index(all_chunks, project_id)    # BM25 持久化
```

### 5.4 `writing_tasks.py` — 大纲生成 + 章节撰写

```python
@celery_app.task(bind=True, max_retries=2)
def generate_outline_task(self, topic: str) -> str:
    return generate_outline(topic)

@celery_app.task(bind=True, max_retries=2, default_retry_delay=60)
def write_section_task(self, project_id: str, section_title: str) -> str:
    return write_section(project_id, section_title)
```

### 5.5 `render_tasks.py` — Markdown 组装 + PDF 渲染

```python
@celery_app.task(bind=True)
def generate_pdf(self, project_id: str) -> str:
    """将报告渲染为 16:9 横版 PPT 风格 PDF"""
    sections = ProjectRepo().get_section_contents(project_id)
    md_content = build_report(topic, sections)
    pdf_path = markdown_to_pdf(md_content, project_id, topic)
    return pdf_path  # 如 "reports/智能手表产品分析_20260618_130425.pdf"
```

---

## 6. 数据仓库层 (backend/app/repositories/)

### 6.1 `project_repo.py` — ProjectRepo 同步数据库仓库

**作用**: 为 Celery Worker 提供统一的同步数据库访问接口，消除散落在各任务中的 raw SQL 和 `asyncio.run()` 调用。

```python
class ProjectRepo:
    """同步数据库仓库——专供 Celery Worker 使用。"""

    def __init__(self):
        self._engine = get_sync_engine()

    # ── 项目查询 ──
    def get_project(self, project_id: str) -> Project          # 获取项目 ORM
    def get_project_topic(self, project_id: str) -> str        # 获取 topic
    def get_project_outline(self, project_id: str) -> str | None  # 获取大纲

    # ── 状态更新 ──
    def update_project_status(self, project_id, status, ...)   # 更新项目状态
    def update_project_outline(self, project_id, outline)      # 保存大纲

    # ── 任务管理 ──
    def update_task_status(self, project_id, task_type, status) # 更新任务状态
    def update_section_task_status(self, ...)                  # 更新章节任务
    def create_section_tasks(self, project_id, titles)         # 动态创建章节任务

    # ── 文档块 (DocumentBlock) ──
    def save_document_block(self, project_id, section, content, citations, order)

    # ── 文档快照 (Document) ──
    def save_document(self, project_id, section, content, source_urls, order)

    # ── 时间轴日志 (ProjectLog) ──
    def append_project_log(self, project_id, step, message, level, icon)
```

> **设计意图**: Celery Worker 在同步上下文中运行。ProjectRepo 使用同步 SQLAlchemy 引擎 + ORM 查询，直接返回 ORM 对象（`session.expunge()` 后 detach），无需 `asyncio.run()` 或 `nest_asyncio`。

---

## 7. 研究引擎 (app/)

> 这是项目的**算法核心**，独立于 FastAPI 后端，可单独作为 Python 模块运行。

### 7.1 `app/llm/client.py` — LLM 客户端工厂

```python
def get_llm(temperature: float = 0.7) -> ChatOpenAI:
    """返回 DeepSeek Chat 实例"""
    return ChatOpenAI(
        model=settings.DEEPSEEK_MODEL,           # deepseek-chat
        api_key=settings.DEEPSEEK_API_KEY,
        base_url=settings.DEEPSEEK_BASE_URL,     # https://api.deepseek.com/v1
        temperature=temperature,
    )
```

### 7.2 `app/llm/prompts.py` — 系统提示词库

集中管理所有 LLM 系统提示词（大纲生成、章节撰写、编辑器润色等），便于统一调优和 A/B 测试。

### 7.3 `app/search/tavily_search.py` — Tavily 搜索封装

```python
def tavily_search(query: str, max_results: int = 5):
    """调用 Tavily Search API，返回结构化搜索结果"""
    client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
    return client.search(query=query, max_results=max_results)
```

### 7.4 `app/crawler/firecrawl_crawler.py` — Firecrawl 深度抓取

```python
def crawl_url(url: str):
    """调用 Firecrawl API 抓取网页，返回 Markdown 格式的正文内容"""
    app = FirecrawlApp(api_key=os.getenv("FIRECRAWL_API_KEY"))
    return app.scrape(url=url, formats=["markdown"])
```

### 7.5 `app/context/context_builder.py` — 搜索上下文构建

将 Tavily 返回的原始搜索结果格式化为 LLM 可消费的结构化上下文块（含来源 URL 和编号）。

### 7.6 `app/rag/chunker.py` — 文本切片

```python
def chunk_text(text: str, chunk_size: int = 1200, chunk_overlap: int = 200):
    """使用 RecursiveCharacterTextSplitter 将长文本切分为重叠片段"""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    return splitter.split_text(text)
```

### 7.7 `app/rag/vector_store.py` — 向量 + BM25 双引擎持久化

```python
class LocalEmbeddingModel:
    """Embedding 模型封装 —— 线程安全单例（SentenceTransformer）"""

def build_vector_store(chunk_data_list: list[dict], project_id: str | None = None):
    """
    接收带元数据的切片列表，构建：
    1. Chroma 向量库（per-project 子目录隔离）
    2. BM25 语料 pickle 持久化
    杜绝多项目并发覆盖。
    """
```

> **关键设计**: 每个项目使用独立子目录 (`chroma_db/<project_id>/`, `bm25_db/<project_id>/`)，杜绝多项目并发时的数据覆盖问题。Embedding 模型路径从配置中心读取，默认使用 `BAAI/bge-small-zh-v1.5`。

### 7.8 `app/rag/retriever.py` — 混合检索引擎

```python
class HybridRetriever:
    """Chroma 向量检索 + BM25 关键词检索 + RRF 融合"""

    def retrieve(self, query: str, k: int = 5) -> list[Document]:
        # 向量检索
        vector_results = self.vector_store.similarity_search(query, k=k*2)
        # BM25 关键词检索
        bm25_results = self.bm25_retriever.search(query, top_k=k*2)
        # RRF (Reciprocal Rank Fusion) 融合排序
        fused = self._rrf_fusion(vector_results, bm25_results)
        return fused[:k]

    def _rrf_fusion(self, results_a, results_b, k=60) -> list:
        scores = {}
        for rank, doc in enumerate(results_a):
            scores[doc.page_content] = scores.get(doc.page_content, 0) + 1/(k+rank+1)
        for rank, doc in enumerate(results_b):
            scores[doc.page_content] = scores.get(doc.page_content, 0) + 1/(k+rank+1)
        return sorted(scores, key=scores.get, reverse=True)
```

### 7.9 `app/rag/rag_pipeline.py` — RAG Pipeline 编排

```python
def build_knowledge_base(query: str, project_id: str | None = None):
    """搜索 → 爬取 → 切片 → 向量化，构建项目知识库的完整流水线"""

def retrieve_context(query: str, k: int = 5, project_id: str | None = None) -> str:
    """检索并格式化为 LLM 可消费的上下文字符串（含来源 URL）"""
```

串联 Tavily 搜索 → Firecrawl 抓取 → chunker 切片 → vector_store 持久化的完整 RAG 构建流程。

### 7.10 `app/rag/citation_utils.py` — 引用溯源引擎

```python
def build_context_with_citations(documents: list[Document]) -> tuple[str, dict]:
    """
    将检索到的文档构建为带编号引用的上下文。
    返回：(带 [^n] 标记的上下文字符串, {ref_num: {title, url, snippet}})
    """
    seen_urls = {}
    context_parts = []
    ref_num = 1
    for doc in documents:
        url = doc.metadata.get("url", "")
        if url and url not in seen_urls:
            seen_urls[url] = ref_num
            context_parts.append(f"[^{ref_num}] {doc.page_content}")
            ref_num += 1
    return "\n\n".join(context_parts), seen_urls
```

### 7.11 `app/planner/outline_generator.py` — 大纲生成

```python
def generate_outline(topic: str) -> str:
    system_prompt = """你是一名资深产品分析专家，拥有 15 年消费电子行业经验。
    为以下产品分析主题生成一份专业大纲，使用 Markdown 格式。
    大纲应覆盖：1) 产品定位 2) 核心功能 3) CMF设计 4) 竞品拆解
    5) 技术可行性 6) 定价策略 7) 使用场景"""
    llm = get_llm(temperature=0.3)
    response = llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"主题：{topic}\n请生成 7-8 个章节的大纲")
    ])
    return response.content
```

### 7.12 `app/planner/query_planner.py` — 检索词规划器

```python
def plan_section_queries(topic: str, section_title: str, num_queries: int = 3) -> list:
    """
    将宽泛的章节标题拆解为多个具体的检索问句 (Query Planning)。
    使用 LLM 生成高密度关键词搜索词组，避免宽泛噪音。
    如 "市场分析" → ["Meta Ray-Ban 华为 Xreal 销量 市场份额", ...]
    """
```

**设计价值**: 原始检索直接用章节标题，往往召回宽泛的噪音。Query Planning 用 LLM 将标题拆解为高密度关键词词组，在三方评测（`tests/eval_ranking.py`）中召回质量显著优于 baseline。

### 7.13 `app/planner/compare_query.py` — Query Planning 对比评测

```python
def run_comparison(topic, section):
    """对比原始检索 vs Query Planning 的检索质量。
    路径 A: 直接使用标题检索 (baseline)
    路径 B: Query Planning 拆解后检索
    输出覆盖度、相关性、耗时三维对比报告。
    """
```

### 7.14 `app/report/section_writer.py` — 章节撰写（含引用）

```python
def write_section(project_id: str, section_title: str) -> str:
    """基于 RAG 检索上下文，生成带学术级引用的章节正文"""
    retriever = HybridRetriever(project_id)
    docs = retriever.retrieve(section_title, k=5)
    context, citations = build_context_with_citations(docs)

    system_prompt = """你是一名资深产品经理。使用提供的参考资料撰写章节。
    规则：1) 必须使用 [^n] 格式引用资料 2) 每条关键数据必须有出处"""

    llm = get_llm(temperature=0.7)
    response = llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"## {section_title}\n\n参考资料：\n{context}")
    ])
    return response.content
```

### 7.15 `app/report/pdf_generator.py` — 16:9 横版 PDF

```python
def markdown_to_pdf(md_content: str, project_id: str, topic: str) -> str:
    """WeasyPrint 渲染 16:9 PPT 风格 PDF"""
    html = f"""
    <html><head><style>
        @page {{ size: 1440px 810px; margin: 80px 100px; }}
        body  {{ font-family: 'PingFang SC','Microsoft YaHei',sans-serif;
                 font-size: 16pt; color: #1e293b; }}
        h1    {{ font-size: 36pt; font-weight: 700; color: #0f172a; }}
        h2    {{ font-size: 24pt; font-weight: 600; page-break-before: always; }}
        .cover {{ text-align: center; padding-top: 250px; }}
        .citation {{ color: #3b82f6; font-size: 9pt; }}
    </style></head><body>
        <div class="cover"><h1>{topic}</h1><p>产品分析报告</p></div>
        {markdown_to_html(md_content)}
    </body></html>"""
    pdf_path = f"outputs/{topic}_{datetime.now():%Y%m%d_%H%M%S}.pdf"
    HTML(string=html).write_pdf(pdf_path)
    return pdf_path
```

### 7.16 `app/report/markdown_formatter.py` — Markdown 报告组装

```python
def build_report(title: str, sections: list) -> str:
    """将标题 + 多个章节正文拼接为完整 Markdown 报告"""
    report = f"# {title}\n\n"
    for section in sections:
        report += section + "\n\n"
    return report
```

### 7.17 `app/retrieval/research_pipeline.py` — CLI 研究流水线

```python
def research_topic(query: str):
    """端到端研究流水线：搜索 → 抓取 → 返回带结构化的文档列表"""
    search_results = tavily_search(query)
    for item in search_results["results"][:3]:
        crawl_result = crawl_url(item["url"])
        collected_docs.append({"title": ..., "url": ..., "content": ...})
    return collected_docs
```

### 7.18 `app/orchestrator/workflow.py` — 端到端流程

```python
def run_workflow(topic: str) -> dict:
    """CLI 可调用的完整工作流（不使用 Celery）"""
    search_results = tavily_search(topic)
    crawled = [crawl_url(r["url"]) for r in search_results[:5]]
    chunks = []
    for c in crawled:
        chunks.extend(chunk_text(c.get("content", "")))
    build_vector_store(chunks, "cli_session")
    build_bm25_index(chunks, "cli_session")
    outline = generate_outline(topic)
    sections = extract_sections(outline)
    written = []
    for s in sections:
        written.append(write_section("cli_session", s))
    md = build_report(topic, written)
    pdf = markdown_to_pdf(md, "cli_session", topic)
    return {"outline": outline, "sections": written, "pdf": pdf}
```

### 7.19 `app/shared/outline_parser.py` — Markdown 大纲解析（副本）

与 `backend/app/shared/outline_parser.py` 功能一致，供 app 层独立运行时使用。

### 7.20 `app/shared/time_utils.py` — 统一 UTC 时间戳

```python
def utcnow() -> datetime:
    """
    返回带 UTC 时区标记的当前时间。
    统一全项目时间处理，替代散落的 datetime.now() 调用。
    """
    return datetime.now(timezone.utc)
```

---

## 8. 前端架构 (frontend/src/)

### 8.1 `main.tsx` — React 入口

```tsx
const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 5_000, gcTime: 5 * 60_000, retry: 2 },
  },
});
createRoot(document.getElementById("root")!).render(
  <BrowserRouter>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </BrowserRouter>
);
```

### 8.2 `App.tsx` — 路由定义

```tsx
<Routes>
  <Route path="/" element={<Layout />}>
    <Route index element={<DashboardPage />} />
    <Route path="projects/:id/workspace" element={<WorkspacePage />} />
    <Route path="projects/:id/progress" element={<ProgressPage />} />
    <Route path="projects/:id/report" element={<ReportPage />} />
  </Route>
</Routes>
```

### 8.3 页面组件

| 文件 | 作用 |
|------|------|
| `pages/DashboardPage.tsx` | 首页仪表盘：项目列表 + 创建新项目 |
| `pages/WorkspacePage.tsx` | **核心页面**：三栏工作台（大纲树 + 中心面板 + 右侧面板） |
| `pages/ProgressPage.tsx` | 项目执行进度全屏视图（实时任务状态 + 时间轴） |
| `pages/ReportPage.tsx` | 最终报告预览页（Markdown 渲染 + 引用角标） |

### 8.4 `pages/WorkspacePage.tsx` — 三栏工作台（核心页面）

```tsx
function WorkspacePage() {
  const { data: status } = useProjectStatus(id);  // 3 秒轮询
  const { blocks, isStreaming } = useEditorSync(id);

  // 根据状态机状态渲染不同组件
  const CenterPanel = () => {
    if (status?.project_status === "waiting_for_sources")
      return <SourcesReview projectId={id} />;
    if (status?.project_status === "waiting_for_outline")
      return <OutlineApproval projectId={id} />;
    return <BlockEditor projectId={id} blocks={blocks} />;
  };

  return (
    <ThreePaneLayout
      left={<OutlineTree sections={...} />}
      center={<CenterPanel />}
      right={<RightPanel />}
    />
  );
}
```

### 8.5 通用组件 (`components/common/`)

| 文件 | 作用 |
|------|------|
| `badge.tsx` | 状态徽章（pending / processing / completed / failed） |
| `button.tsx` | 通用按钮组件 |
| `dialog.tsx` | Radix UI 对话框封装 |
| `input.tsx` | 通用输入框组件 |
| `popover.tsx` | Radix UI 弹出层封装 |

### 8.6 布局组件 (`components/layout/`)

| 文件 | 作用 |
|------|------|
| `Layout.tsx` | 全局布局壳（侧边栏 + `<Outlet />`） |
| `Sidebar.tsx` | 侧边栏导航（项目列表 + Logo + 新建按钮） |
| `ThreePaneLayout.tsx` | 三栏可拖拽布局（左/中/右比例可调） |

### 8.7 项目组件 (`components/projects/`)

| 文件 | 作用 |
|------|------|
| `CreateProjectModal.tsx` | 新建项目弹窗（输入 topic → 调用 create API） |
| `ProjectCard.tsx` | 项目卡片（显示状态 + 进度条 + 点击进入工作台） |
| `ProgressTracker.tsx` | 任务进度追踪条（任务列表 + 状态图标 + 百分比） |
| `SourcesReview.tsx` | 资料审核面板（用户勾选保留/删除搜索到的来源） |
| `OutlineApproval.tsx` | 大纲审核面板（用户确认/编辑 AI 生成的大纲） |
| `TerminalTimeline.tsx` | 终端风格实时日志流（基于 ProjectLog 模型渲染） |

### 8.8 编辑器组件 (`components/editor/`)

**`BlockEditor.tsx`** — Tiptap 块级编辑器：

```tsx
function BlockEditor({ blocks }: { blocks: EditorBlock[] }) {
  const editor = useEditor({
    extensions: [StarterKit, Underline, Placeholder, CitationMark, InlineAIBubble],
    content: blocksToContent(blocks),  // DocumentBlock[] → ProseMirror JSON
    editable: true,
  });
  return <EditorContent editor={editor} />;
}
```

**`InlineAIBubble.tsx`** — 悬浮 AI 菜单：

```tsx
function InlineAIBubble({ editor, projectId }: Props) {
  const handleRevise = async (instruction: string) => {
    const { from, to } = editor.state.selection;
    const selectedText = editor.state.doc.textBetween(from, to);
    const result = await editorApi.revise({ ... });
    showDiff({ original: selectedText, revised: result.revised_text });
  };

  return (
    <BubbleMenu editor={editor}>
      <button onClick={() => handleRevise("polish")}>✨ 润色</button>
      <button onClick={() => handleRevise("expand")}>📝 扩写</button>
      <button onClick={() => handleRevise("simplify")}>🔍 精简</button>
      <input placeholder="自定义指令..." onKeyDown={...} />
    </BubbleMenu>
  );
}
```

**`DiffViewNode.tsx`** — AI 修订 Diff 对比视图，展示原文 vs 润色后文本的差异高亮。

**`extensions/CitationMark.ts`** — ProseMirror 自定义 Mark：将 `[^n]` 引用标记渲染为可点击的蓝色角标徽章。

**`extensions/Citation.tsx`** — 引用角标 React 组件：点击后弹出引用来源卡片（URL + 摘要）。

### 8.9 报告组件 (`components/report/`)

**`CitationMarkdown.tsx`** — 增强 Markdown 渲染器，将正文中的 `[^n]` 引用标记自动渲染为可交互的引用角标，点击弹出引用来源详情。

### 8.10 自定义 Hooks

| Hook | 作用 |
|------|------|
| `useProjects.ts` | 项目列表获取（含创建/删除 mutation） |
| `useProjectStatus.ts` | **状态感知轮询**：运行中 3 秒轮询，交互节点/终态自动停止 |
| `useProjectLogs.ts` | 项目时间轴日志轮询（前端渲染 TerminalTimeline） |
| `useDraftStream.ts` | SSE EventSource 流式接收章节撰写内容 |
| `useEditorSync.ts` | 编辑器内容与后端 DocumentBlock 双向同步 |
| `useCitationStore.ts` | 引用数据全局状态管理（ref_num → {title, url, snippet}） |

### 8.11 `hooks/useProjectStatus.ts` — 状态感知轮询

```tsx
function useProjectStatus(id: string) {
  return useQuery({
    queryKey: ["project-status", id],
    queryFn: () => projectsApi.getStatus(id),
    refetchInterval: (query) => {
      const status = query.state.data?.project_status;
      // 交互节点 + 终态 → 停止轮询（节省带宽）
      if (["waiting_for_sources", "waiting_for_outline",
           "completed", "failed"].includes(status))
        return false;
      return 3000;  // 运行中 → 3 秒轮询
    },
  });
}
```

### 8.12 `hooks/useDraftStream.ts` — SSE 流式接收

```tsx
function useDraftStream(projectId: string, onChunk: (block: SSEDraftEvent) => void) {
  useEffect(() => {
    const es = new EventSource(`/api/v1/projects/${projectId}/stream-draft`);
    es.addEventListener("section_chunk", (e) => {
      const block = JSON.parse(e.data);
      onChunk(block);  // 逐块插入 Tiptap 编辑器
    });
    es.addEventListener("draft_complete", () => es.close());
    return () => es.close();
  }, [projectId]);
}
```

### 8.13 `lib/api.ts` — API 服务层

```tsx
const projectsApi = {
  create: (topic: string) =>
    api.post("/projects", { topic }).then(r => r.data),
  getStatus: (id: string) =>
    api.get(`/projects/${id}/status`).then(r => r.data),
  approveOutline: (id: string, outline: string) =>
    api.post(`/projects/${id}/approve-outline`, { outline }),
  reviewSources: (id: string, selected_urls: string[]) =>
    api.post(`/projects/${id}/review-sources`, { selected_urls }),
};

const editorApi = {
  revise: (body: EditorReviseRequest) =>
    api.post("/editor/revise", body).then(r => r.data),
};
```

### 8.14 `lib/utils.ts` — 通用工具函数

日期格式化、UUID 截断、状态标签映射等 UI 辅助函数。

### 8.15 `types/` — TypeScript 类型定义

| 文件 | 作用 |
|------|------|
| `types/api.ts` | API 请求/响应类型（`ProjectCreateRequest`, `ProjectStatusResponse`, `SSEDraftEvent` 等） |
| `types/index.ts` | 通用 UI 类型（`EditorBlock`, `ProgressStep`, `LogEntry` 等） |

---

## 9. 数据模型 (backend/app/models/)

### 9.1 模型关系

```
User (1) ──< (N) Project (1) ──< (N) Task
                    │
                    ├──< (N) Document        (完整章节快照)
                    ├──< (N) DocumentBlock    (原子化编辑块)
                    └──< (N) ProjectLog       (时间轴日志)
```

### 9.2 `base.py` — 声明式基类

```python
class Base(DeclarativeBase):
    pass

def orm_to_dict(obj: Base) -> dict:
    """ORM 实例 → 纯字典。自动处理 UUID → str, enum → value, datetime → ISO"""
    result = {}
    for col in obj.__table__.columns:
        value = getattr(obj, col.key)
        if hasattr(value, "value"):       # enum
            result[col.key] = value.value
        elif isinstance(value, uuid.UUID): # UUID
            result[col.key] = str(value)
        elif isinstance(value, datetime):  # datetime
            result[col.key] = value.isoformat()
        else:
            result[col.key] = value
    return result
```

### 9.3 `user.py` — 用户

```python
class User(Base):
    __tablename__ = "users"
    id        = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    username  = mapped_column(String(100), unique=True, nullable=False)
    email     = mapped_column(String(255), unique=True, nullable=True)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())
```

> 当前为简化版，仅作为 Project 的外键引用，不涉及完整的认证/授权流程。

### 9.4 `project.py` — 项目 + 状态枚举

```python
class ProjectStatus(str, enum.Enum):
    PREPARING_DATA        = "preparing_data"          # 初始
    WAITING_FOR_SOURCES   = "waiting_for_sources"     # 🛑 等用户审核资料
    PREPARING_OUTLINE     = "preparing_outline"       # 自动生成大纲
    WAITING_FOR_OUTLINE   = "waiting_for_outline"     # 🛑 等用户确认大纲
    DRAFTING              = "drafting"                # 自动逐章撰写
    COMPLETED             = "completed"               # ✅ 完成
    FAILED                = "failed"                  # ❌ 失败

class Project(Base):
    __tablename__ = "projects"
    id              = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    owner_id        = mapped_column(UUIDType, ForeignKey("users.id"))
    topic           = mapped_column(String(500))
    status          = mapped_column(Enum(ProjectStatus, ...), index=True)
    outline_content = mapped_column(Text, nullable=True)
    pdf_path        = mapped_column(String(500), nullable=True)
    md_path         = mapped_column(String(500), nullable=True)
    error_message   = mapped_column(Text, nullable=True)
    created_at      = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at      = mapped_column(DateTime(timezone=True), nullable=True)
```

### 9.5 `task.py` — 任务

```python
class TaskType(str, enum.Enum):
    SEARCH                = "search"
    BUILD_KNOWLEDGE_BASE  = "build_knowledge_base"
    GENERATE_OUTLINE      = "generate_outline"
    WRITE_SECTION         = "write_section"
    BUILD_REPORT          = "build_report"
    GENERATE_PDF          = "generate_pdf"
    IMAGE_GENERATION      = "image_generation"

class TaskStatus(str, enum.Enum):
    PENDING    = "pending"
    PROCESSING = "processing"
    COMPLETED  = "completed"
    FAILED     = "failed"

class Task(Base):
    __tablename__ = "tasks"
    id             = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    project_id     = mapped_column(UUIDType, ForeignKey("projects.id"), index=True)
    task_type      = mapped_column(Enum(TaskType, ...))
    status         = mapped_column(Enum(TaskStatus, ...), default=TaskStatus.PENDING)
    sequence_order = mapped_column(Integer, default=0)
    section_title  = mapped_column(String(500), nullable=True)  # WRITE_SECTION 任务专属
    started_at     = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at   = mapped_column(DateTime(timezone=True), nullable=True)
    error_message  = mapped_column(Text, nullable=True)
```

### 9.6 `document_block.py` — 原子化内容块

```python
class DocumentBlock(Base):
    __tablename__ = "document_blocks"
    id            = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    project_id    = mapped_column(UUIDType, ForeignKey("projects.id"), index=True)
    section_title = mapped_column(String(500))
    order_index   = mapped_column(Integer, default=0)  # 排序
    content       = mapped_column(Text, default="")    # Markdown 正文
    citations     = mapped_column(Text, nullable=True)  # JSON: {ref_num: {title,url}}
    created_at    = mapped_column(DateTime(timezone=True), server_default=func.now())
```

### 9.7 `document.py` — 章节文档快照

```python
class Document(Base):
    """报告章节文档 —— 每个 section 对应一条完整记录"""
    __tablename__ = "documents"
    id            = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    project_id    = mapped_column(UUIDType, ForeignKey("projects.id"), index=True)
    section_title = mapped_column(String(500))
    section_order = mapped_column(Integer, default=0)
    content       = mapped_column(Text, default="")
    source_urls   = mapped_column(Text, nullable=True)  # JSON 格式的引用源 URL 列表
    created_at    = mapped_column(DateTime(timezone=True), server_default=func.now())
```

> **Document vs DocumentBlock**: Document 是完整章节的一次性快照（用于报告全文组装），DocumentBlock 是流式撰写的原子化编辑块（SSE 逐块推送，Tiptap 实时渲染）。

### 9.8 `project_log.py` — 项目时间轴日志

```python
class LogLevel(str, enum.Enum):
    INFO = "info"
    WARN = "warn"
    ERROR = "error"
    MILESTONE = "milestone"

class ProjectLog(Base):
    """项目执行时间轴日志 —— 前端渲染为终端控制台风格的实时日志流"""
    __tablename__ = "project_logs"
    id         = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    project_id = mapped_column(UUIDType, nullable=False, index=True)
    sequence   = mapped_column(Integer, nullable=False, default=0)
    level      = mapped_column(Enum(LogLevel, ...), default=LogLevel.INFO)
    step       = mapped_column(String(200), nullable=False)
    message    = mapped_column(Text, nullable=False)
    icon       = mapped_column(String(10), nullable=True)  # emoji 图标
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())
```

---

## 10. 状态机流转全景

```
用户创建项目
    │
    ▼
PREPARING_DATA ──(Celery: 搜索+抓取)──▶ WAITING_FOR_SOURCES  🛑
                                               │
                              POST /review-sources  (用户审核资料)
                                               │
                                               ▼
                                    PREPARING_OUTLINE ──(Celery: 知识库+大纲)──▶ WAITING_FOR_OUTLINE  🛑
                                                                                       │
                                                                      POST /approve-outline  (用户确认大纲)
                                                                                       │
                                                                                       ▼
                                                                              DRAFTING ──(Celery: 逐章撰写+组装+PDF)──▶ COMPLETED ✅
                                                                                 │
                                                                                 │ SSE stream-draft
                                                                                 ▼
                                                                         [前端 Tiptap 流式渲染]
```

### 关键设计决策

| 决策 | 原因 |
|------|------|
| Celery `--pool=threads` | Windows Python 3.14 `spawn` 多进程导致 `trace._localized` 崩溃 |
| SQLite NullPool + WAL | 单文件开发库，WAL 提升并发读写，NullPool 避免连接池冲突 |
| SSE 轮询而非 WebSocket | 简化部署（无需额外 WS 服务器），2 秒间隔可接受 |
| `orm_to_dict()` 手动转换 | 避免 Pydantic `from_attributes=True` 的嵌套序列化陷阱 |
| Chroma + BM25 双引擎 + RRF | 向量检索覆盖语义，BM25 覆盖关键词精确匹配，RRF 融合最优排序 |
| Per-project 向量库子目录 | 杜绝多项目并发时的数据互相覆盖 |
| Query Planning + Baseline 对比 | LLM 拆解宽泛标题为高密度关键词，召回质量显著优于直接检索 |
| 16:9 横版 PDF | WeasyPrint + CSS `@page size: 1440px 810px` 精确控制输出 |
| Redis 容器化部署 | 避免 WSL sudo 权限问题，`--restart unless-stopped` 保活 |
| 状态感知轮询停止 | 交互节点/终态自动停轮询，减少不必要的网络请求 |
| ProjectRepo 同步仓库 | 消除任务中散落的 raw SQL 和 `asyncio.run()`，统一 Celery 数据访问 |
| Document vs DocumentBlock 双模型 | Document 完整快照用于报告组装，DocumentBlock 原子化块用于流式编辑 |
| ProjectLog 时间轴 | 结构化日志持久化到 DB，前端渲染为终端控制台实时流 |
| `utcnow()` 统一时间戳 | 杜绝散落的 naive `datetime.now()`，确保全项目 UTC 一致性 |
| `main.py` 双路径注入 (`sys.path`) | 同时加入 `backend/` 和项目根目录，桥接 `backend/app/` 与项目根 `app/` 两套包体系，使 RAG/搜索/爬虫等研究引擎模块可从后端代码直接 import |
| `/editor/chat` RAG 上下文注入 | work 模式自动调用 `retrieve_context()` 从 Chroma + BM25 召回 Top-5 切片注入 LLM 上下文，打通"上传 PDF → 切片入库 → 对话检索"完整链路 |

---

## 11. 测试与评测

### 11.1 `tests/eval_retrieval.py` — 检索质量评测

评测混合检索引擎（Chroma + BM25 + RRF）在不同查询类型下的召回率、精确率和 MRR。

### 11.2 `tests/eval_ranking.py` — 排序质量评测

评测 Query Planning vs 原始检索的排序效果对比，验证 RRF 融合权重和 Query Planning 的收益。

### 11.3 `tests/eval_citation.py` — 引用质量评测

评测引用溯源引擎的准确率：生成的 `[^n]` 脚注是否正确关联到对应的来源 URL 和内容片段。

---

> 完整源码：`https://github.com/CaroVon/QX_Product_Research`
