/**
 * ============================================================
 * 后端 API 类型定义
 * —— 与 research_agent/backend/app/schemas/__init__.py 一致
 *     新增：状态机枚举、大纲审批、DocumentBlock、SSE 事件
 * ============================================================
 */

// ─── 通用 ──────────────────────────────────────────────────────

export interface MessageResponse {
  detail: string
}

// ─── 项目 (Project) ────────────────────────────────────────────

export interface ProjectCreateRequest {
  topic: string
}

export interface ProjectResponse {
  id: string
  topic: string
  status: ProjectStatusEnum
  outline_content: string | null
  pdf_path: string | null
  md_path: string | null
  error_message: string | null
  created_at: string
  updated_at: string | null
}

/**
 * 状态机枚举 —— 与后端 ProjectStatus 一一对应
 *
 * 状态流转:
 *   preparing_data
 *     → waiting_outline_approval (等待用户确认大纲)
 *       → drafting (用户确认大纲后开始撰写)
 *         → completed
 *   any → failed
 */
export type ProjectStatusEnum =
  | 'preparing_data'
  | 'waiting_outline_approval'
  | 'drafting'
  | 'completed'
  | 'failed'

export interface ProjectCreateResponse {
  project: ProjectResponse
  celery_task_id: string
  message: string
}

// ─── 大纲审批 (Outline Approval) ───────────────────────────────

export interface OutlineApproveRequest {
  outline: string
}

export interface OutlineApproveResponse {
  project_id: string
  new_status: string
  message: string
  sections_count: number
  celery_task_id: string | null
}

// ─── 任务 (Task) ───────────────────────────────────────────────

export interface TaskResponse {
  id: string
  task_type: TaskTypeEnum
  status: TaskStatusEnum
  sequence_order: number
  section_title: string | null
  retry_count: number
  error_message: string | null
  started_at: string | null
  completed_at: string | null
  created_at: string
}

export type TaskTypeEnum =
  | 'search'
  | 'build_kb'
  | 'generate_outline'
  | 'write_section'
  | 'generate_image'
  | 'build_report'
  | 'generate_pdf'

export type TaskStatusEnum =
  | 'pending'
  | 'processing'
  | 'completed'
  | 'failed'
  | 'retrying'
  | 'cancelled'

export interface ProgressInfo {
  total_tasks: number
  completed_tasks: number
  failed_tasks: number
  percentage: number
}

export interface ProjectStatusResponse {
  project_id: string
  topic: string
  project_status: ProjectStatusEnum
  outline_content: string | null
  progress: ProgressInfo
  tasks: TaskResponse[]
}

// ─── 文档块 (DocumentBlock) ────────────────────────────────────

export interface DocumentBlockResponse {
  id: string
  section_title: string
  order_index: number
  content: string
  citations: string | null
  created_at: string
  updated_at: string | null
}

export interface DocumentBlockListResponse {
  project_id: string
  blocks: DocumentBlockResponse[]
}

// ─── 文档 (Document) ───────────────────────────────────────────

export interface DocumentResponse {
  id: string
  section_title: string
  section_order: number
  version: number
  content: string
  source_urls: string | null
  created_at: string
}

// ─── 下载 ──────────────────────────────────────────────────────

export interface DownloadResponse {
  project_id: string
  topic: string
  download_url: string
  filename: string
  file_size_bytes: number | null
  report_ready: boolean
}

// ─── 编辑器 AI 改写 (Editor Revise) ────────────────────────────

/** 编辑器 AI 改写请求 */
export interface EditorReviseRequest {
  /** 选中的文本内容 */
  selected_text: string
  /** 改写指令（如 "扩写", "精简", "润色"） */
  instruction: string
  /** 上下文：选中文本前后的完整段落内容（供 AI 参考语境） */
  context?: string
}

/** 编辑器 AI 改写响应 */
export interface EditorReviseResponse {
  /** AI 改写后的新文本 */
  revised_text: string
}

// ─── 报告内容 (Report Content) ──────────────────────────────────

export interface ReportContentResponse {
  project_id: string
  topic: string
  sections: SectionContent[]
}

export interface SectionContent {
  title: string
  order: number
  content: string
  citations: Record<string, string>
}

// ─── 前端自定义类型 ────────────────────────────────────────────

/**
 * 从后端 document 的 source_urls JSON 字符串解析出的引用映射
 * { "1": "https://example.com/article1", "2": "https://example.com/article2" }
 */
export interface CitationMap {
  [key: string]: string
}

/**
 * 章节与溯源信息的组合
 */
export interface SectionWithCitations {
  section: DocumentResponse
  citationMap: CitationMap
  /** 渲染后的章节标题（如 "1. 产品设计理念"） */
  renderedTitle: string
}

/**
 * 任务步骤标签映射 —— 用于进度指示器
 */
export const TASK_STEP_LABELS: Record<TaskTypeEnum, string> = {
  search: '数据采集',
  build_kb: '构建知识库',
  generate_outline: '规划大纲',
  write_section: 'AI 撰写中',
  generate_image: '生成图表',
  build_report: '报告排版',
  generate_pdf: 'PDF 渲染',
}

/**
 * 状态机步骤标签（含交互节点标记）
 */
export const STATE_MACHINE_STEPS = [
  { status: 'preparing_data' as ProjectStatusEnum, label: '资料准备', icon: '🔍', interactive: false },
  { status: 'waiting_outline_approval' as ProjectStatusEnum, label: '大纲确认', icon: '📋', interactive: true },
  { status: 'drafting' as ProjectStatusEnum, label: 'AI 撰写中', icon: '✍️', interactive: false },
  { status: 'completed' as ProjectStatusEnum, label: '报告完成', icon: '✅', interactive: false },
] as const

/**
 * 任务进度指示器的核心步骤（按后端定义的 sequence_order）
 */
export const PROGRESS_STEPS = [
  { type: 'search' as TaskTypeEnum, label: '搜集资料', icon: '🔍' },
  { type: 'build_kb' as TaskTypeEnum, label: '知识库', icon: '📚' },
  { type: 'generate_outline' as TaskTypeEnum, label: '规划大纲', icon: '📋' },
  { type: 'write_section' as TaskTypeEnum, label: 'AI 撰写', icon: '✍️' },
  { type: 'build_report' as TaskTypeEnum, label: '报告排版', icon: '📄' },
  { type: 'generate_pdf' as TaskTypeEnum, label: 'PDF 输出', icon: '📕' },
] as const
