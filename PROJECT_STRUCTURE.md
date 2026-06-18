# QX Product Research Agent — 项目脚本架构文档

> **版本**: v0.1 | **更新**: 2026-06-18
>
> 本文档描述项目的完整脚本结构、每段脚本的核心代码片段及其在系统中的作用。

---

## 目录

1. [总览：三层架构](#1-总览三层架构)
2. [启动与运维脚本](#2-启动与运维脚本)
3. [后端应用层 (backend/app/)](#3-后端应用层-backendapp)
4. [异步任务引擎 (backend/app/tasks/)](#4-异步任务引擎-backendapptasks)
5. [研究引擎 (app/)](#5-研究引擎-app)
6. [前端架构 (frontend/src/)](#6-前端架构-frontendsrc)
7. [数据模型 (backend/app/models/)](#7-数据模型-backendappmodels)
8. [状态机流转全景](#8-状态机流转全景)

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
│    搜索 → 抓取 → 向量库 → RAG 检索 → 大纲 → 撰写 → PDF  │
└─────────────────────────────────────────────────────────┘
```

---

## 2. 启动与运维脚本

### 2.1 `start_all.sh` — 全模块一键启动 (WSL)

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

# 核心片段：启动 FastAPI（后台 + 日志重定向）
nohup uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload \
    > backend/api.log 2>&1 &

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

### 2.2 `stop_all.sh` — 全模块停止

```bash
# 核心片段：按端口精准杀进程
PID=$(ss -tlnp | grep ':8000' | grep -oP 'pid=\K[0-9]+' | head -1)
[ -n "$PID" ] && kill "$PID"
pkill -f "celery.*worker"
PID=$(ss -tlnp | grep ':5173' | grep -oP 'pid=\K[0-9]+' | head -1)
[ -n "$PID" ] && kill "$PID"
```

### 2.3 `start_project.bat` — Windows 入口

```batch
@echo off
chcp 65001 >nul 2>&1
:: 通过 WSL 调用 bash 启动脚本
wsl -e bash /mnt/d/DEV/agents/QX_product_agent/start_all.sh
pause
```

**设计意图**: Windows 用户双击 bat → 内部委托 WSL 执行 bash 脚本。所有环境（Python、Node、Redis）均在 WSL 内运行，数据统一落在 D 盘。

---

## 3. 后端应用层 (backend/app/)

### 3.1 `backend/app/main.py` — FastAPI 应用工厂

这是整个后端的**唯一入口**。

```python
# 核心片段：sys.path 修正 —— 确保 backend/app/ 优先加载
_backend_dir = Path(__file__).resolve().parent.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

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

### 3.2 `backend/app/core/config.py` — 配置中心

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

### 3.3 `backend/app/core/database.py` — 异步数据库引擎

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

### 3.4 `backend/app/core/celery_app.py` — Celery 应用实例

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

### 3.5 `backend/app/core/celery_db.py` — Celery Worker 数据库层

```python
# 核心片段：提供同步引擎（Celery worker 在同步上下文中运行）
@lru_cache()
def get_sync_engine():
    return create_engine(settings.DATABASE_URL_SYNC, echo=settings.DEBUG)

# 核心片段：爬取数据的临时文件路径
def get_crawled_data_path(project_id: str) -> str:
    return os.path.join(settings.OUTPUT_DIR, f"crawled_data_{project_id}.json")
```

### 3.6 `backend/app/api/v1/router.py` — 路由聚合

```python
router = APIRouter()
router.include_router(projects.router)   # /api/v1/projects
router.include_router(editor.router)     # /api/v1/editor
```

### 3.7 `backend/app/api/v1/endpoints/projects.py` — 核心业务 API（约 950 行）

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

### 3.8 `backend/app/api/v1/endpoints/editor.py` — Inline AI 编辑器

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

### 3.9 `backend/app/schemas/__init__.py` — Pydantic 数据契约

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

### 3.10 `backend/app/shared/outline_parser.py` — Markdown 大纲解析

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

---

## 4. 异步任务引擎 (backend/app/tasks/)

### 4.1 `report_workflow.py` — 三阶段状态机编排器

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

### 4.2 `search_tasks.py` — 搜索 + 抓取

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

### 4.3 `knowledge_tasks.py` — 知识库构建

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

### 4.4 `writing_tasks.py` — 大纲生成 + 章节撰写

```python
@celery_app.task(bind=True, max_retries=2)
def generate_outline_task(self, topic: str) -> str:
    return generate_outline(topic)

@celery_app.task(bind=True, max_retries=2, default_retry_delay=60)
def write_section_task(self, project_id: str, section_title: str) -> str:
    return write_section(project_id, section_title)
```

### 4.5 `render_tasks.py` — Markdown 组装 + PDF 渲染

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

## 5. 研究引擎 (app/)

> 这是项目的**算法核心**，独立于 FastAPI 后端，可单独作为 Python 模块运行。

### 5.1 `app/llm/client.py` — LLM 客户端工厂

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

### 5.2 `app/rag/retriever.py` — 混合检索引擎

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

### 5.3 `app/rag/citation_utils.py` — 引用溯源引擎

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

### 5.4 `app/planner/outline_generator.py` — 大纲生成

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

### 5.5 `app/report/section_writer.py` — 章节撰写（含引用）

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

### 5.6 `app/report/pdf_generator.py` — 16:9 横版 PDF

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

### 5.7 `app/orchestrator/workflow.py` — 端到端流程

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

---

## 6. 前端架构 (frontend/src/)

### 6.1 `main.tsx` — React 入口

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

### 6.2 `App.tsx` — 路由定义

```tsx
<Routes>
  <Route path="/" element={<Layout />}>
    <Route index element={<DashboardPage />} />
    <Route path="projects/:id/workspace" element={<WorkspacePage />} />
    <Route path="projects/:id/report" element={<ReportPage />} />
  </Route>
</Routes>
```

### 6.3 `pages/WorkspacePage.tsx` — 三栏工作台（核心页面）

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

### 6.4 `hooks/useProjectStatus.ts` — 状态感知轮询

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

### 6.5 `hooks/useDraftStream.ts` — SSE 流式接收

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

### 6.6 `components/editor/BlockEditor.tsx` — Tiptap 块级编辑器

```tsx
function BlockEditor({ blocks }: { blocks: EditorBlock[] }) {
  const editor = useEditor({
    extensions: [StarterKit, Underline, Placeholder, CitationMark, InlineAIBubble],
    content: blocksToContent(blocks),  // DocumentBlock[] → ProseMirror JSON
    editable: true,
  });

  // 注册 BubbleMenu 扩展（Inline AI 悬浮菜单）
  // 注册 CitationMark 扩展（[^n] 角标 → 可点击徽章）
  return <EditorContent editor={editor} />;
}
```

### 6.7 `components/editor/InlineAIBubble.tsx` — 悬浮 AI 菜单

```tsx
function InlineAIBubble({ editor, projectId }: Props) {
  const handleRevise = async (instruction: string) => {
    const { from, to } = editor.state.selection;
    const selectedText = editor.state.doc.textBetween(from, to);
    const result = await editorApi.revise({
      project_id: projectId,
      block_id: blockId,
      selected_text: selectedText,
      instruction,
    });
    // 打开 DiffView 展示修改前后对比
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

### 6.8 `lib/api.ts` — API 服务层

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

---

## 7. 数据模型 (backend/app/models/)

### 7.1 模型关系

```
User (1) ──< (N) Project (1) ──< (N) Task
                    │
                    ├──< (N) Document        (完整章节)
                    ├──< (N) DocumentBlock    (原子化编辑块)
                    └──< (N) ProjectLog       (时间轴日志)
```

### 7.2 `base.py` — 声明式基类

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

### 7.3 `project.py` — 项目 + 状态枚举

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
    error_message   = mapped_column(Text, nullable=True)
    created_at      = mapped_column(DateTime(timezone=True), server_default=func.now())
```

### 7.4 `task.py` — 任务

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
```

### 7.5 `document_block.py` — 原子化内容块

```python
class DocumentBlock(Base):
    __tablename__ = "document_blocks"
    id            = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    project_id    = mapped_column(UUIDType, ForeignKey("projects.id"), index=True)
    section_title = mapped_column(String(500))
    order_index   = mapped_column(Integer, default=0)  # 排序
    content       = mapped_column(Text, default="")    # Markdown 正文
    citations     = mapped_column(Text, nullable=True)  # JSON: {ref_num: {title,url}}
```

---

## 8. 状态机流转全景

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
| Chroma + BM25 双引擎 | 向量检索覆盖语义，BM25 覆盖关键词精确匹配 |
| 16:9 横版 PDF | WeasyPrint + CSS `@page size: 1440px 810px` 精确控制输出 |
| Redis 容器化部署 | 避免 WSL sudo 权限问题，`--restart unless-stopped` 保活 |
| 状态感知轮询停止 | 交互节点/终态自动停轮询，减少不必要的网络请求 |

---

> 完整源码：`https://github.com/CaroVon/QX_Product_Research`
