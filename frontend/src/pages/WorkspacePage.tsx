/**
 * ============================================================
 * WorkspacePage —— 交互式工作台页面
 *
 * 🌟 本次重构核心页面，替代原有的静态 ReportPage
 *
 * 页面组成：
 * ┌─────────────────────────────────────────────────────────────┐
 * │  ThreePaneLayout                                           │
 * │  ┌──────────┬──────────────────────────┬────────────┐      │
 * │  │ 左栏     │      中栏                │  右栏       │      │
 * │  │ (w-64)   │     (flex-1)             │  (w-80)    │      │
 * │  │          │                          │            │      │
 * │  │ 大纲目录 │ [ProgressTracker]        │ 引用溯源    │      │
 * │  │ 树      │ [OutlineApproval]  ← 状态拦截│  或        │      │
 * │  │          │ [BlockEditor]            │ Agent对话  │      │
 * │  └──────────┴──────────────────────────┴────────────┘      │
 * │                                                             │
 * └─────────────────────────────────────────────────────────────┘
 *
 * 状态机渲染逻辑：
 * - preparing_data → 显示 ProgressTracker + 编辑器骨架
 * - waiting_outline_approval → 🎯 显示 OutlineApproval 横幅
 * - drafting → 显示 ProgressTracker + BlockEditor（流式接收）
 * - completed → 显示 BlockEditor（只读）+ 完成状态
 * - failed → 显示错误详情
 * ============================================================
 */

import { useState, useCallback, useMemo, useEffect, useRef } from 'react'
import { useParams, Link } from 'react-router-dom'
import type { Editor } from '@tiptap/react'
import { ArrowLeft, Loader2, AlertCircle, Search, FileText, Download, Quote, Bot, Terminal, Send, ExternalLink } from 'lucide-react'
import { Button } from '@/components/common/button'
import { ProgressTracker } from '@/components/projects/ProgressTracker'
import { SourcesReview } from '@/components/projects/SourcesReview'
import { OutlineApproval } from '@/components/projects/OutlineApproval'
import { ThreePaneLayout, useThreePane } from '@/components/layout/ThreePaneLayout'
import { BlockEditor } from '@/components/editor/BlockEditor'
import { cn } from '@/lib/utils'
import {
  useProjectStatus,
  useProjectBlocks,
  useSources,
  useReviewSources,
  useApproveOutline,
  getStatusFlags,
} from '@/hooks/useProjectStatus'
import { useEditorSync } from '@/hooks/useEditorSync'
import { useDraftStream } from '@/hooks/useDraftStream'
import { useCitationStore } from '@/hooks/useCitationStore'
import { useProjectLogs } from '@/hooks/useProjectLogs'
import { TerminalTimeline } from '@/components/projects/TerminalTimeline'
import { editorApi } from '@/lib/api'
import type { OutlineSection, RightPanelView } from '@/types/index'

// ================================================================
// 左栏：大纲目录树
// ================================================================

interface OutlineTreeProps {
  sections: OutlineSection[]
  activeSectionTitle: string | null
  onSectionClick: (title: string) => void
  isStreaming: boolean
}

function OutlineTree({ sections, activeSectionTitle, onSectionClick, isStreaming }: OutlineTreeProps) {
  return (
    <div className="flex h-full flex-col">
      {/* ─── 头部 ───────────────────────────────────────────── */}
      <div className="flex items-center gap-2 border-b border-border px-4 py-3">
        <FileText className="h-4 w-4 text-muted-foreground" />
        <span className="text-sm font-medium">大纲目录</span>
        {isStreaming && (
          <span className="ml-auto flex h-2 w-2">
            <span className="absolute inline-flex h-2 w-2 animate-ping rounded-full bg-blue-400 opacity-75" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-blue-500" />
          </span>
        )}
      </div>

      {/* ─── 章节列表 ─────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto p-2">
        {sections.length === 0 ? (
          <div className="px-3 py-8 text-center">
            <p className="text-xs text-muted-foreground">暂无章节</p>
            <p className="mt-1 text-[10px] text-muted-foreground/60">等待 AI 生成大纲...</p>
          </div>
        ) : (
          <nav className="space-y-0.5">
            {sections.map((section) => (
              <button
                key={section.index}
                type="button"
                onClick={() => onSectionClick(section.title)}
                className={cn(
                  'w-full rounded-md px-3 py-2 text-left text-xs transition-colors',
                  activeSectionTitle === section.title
                    ? 'bg-primary/10 font-medium text-primary'
                    : 'text-muted-foreground hover:bg-muted hover:text-foreground',
                )}
              >
                <span className="line-clamp-2">{section.title}</span>
              </button>
            ))}
          </nav>
        )}
      </div>

      {/* ─── 底部统计 ─────────────────────────────────────────── */}
      <div className="border-t border-border px-4 py-2">
        <p className="text-[10px] text-muted-foreground/60">
          {sections.length} 个章节
        </p>
      </div>
    </div>
  )
}

// ================================================================
// 右栏：引用溯源 / Agent 对话
// ================================================================

interface RightPanelProps {
  view: RightPanelView
  onClose: () => void
}

interface CitationsPanelProps {
  citationMap: Record<string, string>
}

function CitationsPanel({ citationMap }: CitationsPanelProps) {
  const activeCitationId = useCitationStore((s) => s.activeCitationId)
  const url = activeCitationId ? citationMap[activeCitationId] : null

  return (
    <div className="p-4">
      <h3 className="mb-3 text-sm font-semibold">引用溯源</h3>

      {activeCitationId ? (
        <div className="rounded-lg border border-violet-100 bg-violet-50/50 p-3">
          <p className="text-xs font-semibold text-violet-700">引用 [^{activeCitationId}]</p>
          {url ? (
            <>
              <p className="mt-1.5 break-all text-[11px] text-violet-600/80">{url}</p>
              <a
                href={url}
                target="_blank"
                rel="noopener noreferrer"
                className="mt-2 inline-flex items-center gap-1 rounded bg-violet-100 px-2 py-0.5 text-[11px] font-medium text-violet-700 hover:bg-violet-200 transition-colors"
              >
                <ExternalLink className="h-3 w-3" />
                打开原文
              </a>
            </>
          ) : (
            <p className="mt-1 text-[11px] text-violet-600/60">（未找到该引用的来源链接）</p>
          )}
        </div>
      ) : (
        <div className="rounded-lg border border-dashed border-border bg-muted/20 p-4 text-center">
          <Quote className="mx-auto mb-2 h-5 w-5 text-muted-foreground/50" />
          <p className="text-xs text-muted-foreground">点击报告中的引用角标，此处将展示对应的来源链接。</p>
        </div>
      )}

      {/* 引用列表 */}
      {Object.keys(citationMap).length > 0 && (
        <div className="mt-4">
          <p className="mb-2 text-xs font-medium text-muted-foreground">所有引用来源</p>
          <div className="space-y-1.5">
            {Object.entries(citationMap).map(([id, href]) => (
              <div key={id} className="flex items-start gap-2 rounded p-1.5 hover:bg-muted/50">
                <span className="mt-0.5 shrink-0 rounded bg-muted px-1 py-0.5 text-[10px] font-mono font-medium text-muted-foreground">
                  [{id}]
                </span>
                <a
                  href={href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="line-clamp-2 text-[11px] text-blue-600 hover:underline"
                >
                  {href}
                </a>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

interface AgentChatPanelProps {
  activeSectionTitle: string | null
}

function AgentChatPanel({ activeSectionTitle }: AgentChatPanelProps) {
  const [messages, setMessages] = useState<Array<{ role: 'user' | 'assistant'; text: string }>>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleSend = useCallback(async () => {
    const trimmed = input.trim()
    if (!trimmed || loading) return

    const userMsg = { role: 'user' as const, text: trimmed }
    setMessages((prev) => [...prev, userMsg])
    setInput('')
    setLoading(true)

    try {
      // 使用报告章节名作为上下文，指令是用户输入
      const placeholder = activeSectionTitle
        ? `当前正在编辑章节「${activeSectionTitle}」的产品分析报告，请根据指令提供改写建议：`
        : `这是一份产品分析报告，请根据指令提供改写建议：`
      const res = await editorApi.revise({
        selected_text: placeholder,
        instruction: trimmed,
      })
      setMessages((prev) => [...prev, { role: 'assistant', text: res.revised_text }])
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', text: '⚠️ 请求失败，请检查网络或 API 配置。' },
      ])
    } finally {
      setLoading(false)
    }
  }, [input, loading, activeSectionTitle])

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        handleSend()
      }
    },
    [handleSend],
  )

  return (
    <div className="flex h-full flex-col">
      {/* 消息列表 */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {messages.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <Bot className="mb-2 h-8 w-8 text-muted-foreground/40" />
            <p className="text-xs text-muted-foreground">向 AI 发送指令，辅助润色或扩写当前章节内容。</p>
            {activeSectionTitle && (
              <p className="mt-1 text-[11px] text-muted-foreground/60">当前章节：{activeSectionTitle}</p>
            )}
          </div>
        ) : (
          messages.map((msg, i) => (
            <div
              key={i}
              className={cn(
                'rounded-lg px-3 py-2 text-xs leading-relaxed',
                msg.role === 'user'
                  ? 'ml-6 bg-primary/10 text-foreground'
                  : 'mr-6 bg-muted text-foreground',
              )}
            >
              <p className="mb-1 text-[10px] font-medium text-muted-foreground">
                {msg.role === 'user' ? '你' : 'AI 助手'}
              </p>
              <p className="whitespace-pre-wrap">{msg.text}</p>
            </div>
          ))
        )}
        {loading && (
          <div className="mr-6 rounded-lg bg-muted px-3 py-2">
            <p className="text-[10px] font-medium text-muted-foreground mb-1">AI 助手</p>
            <div className="flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground/50 [animation-delay:0ms]" />
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground/50 [animation-delay:150ms]" />
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground/50 [animation-delay:300ms]" />
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* 输入框 */}
      <div className="border-t border-border p-3">
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={activeSectionTitle ? `针对「${activeSectionTitle}」提出修改意见...` : '输入改写指令（Enter 发送）'}
            disabled={loading}
            rows={2}
            className="flex-1 resize-none rounded-lg border border-border bg-background px-3 py-2 text-xs placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-50"
          />
          <button
            type="button"
            onClick={handleSend}
            disabled={loading || !input.trim()}
            className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-colors"
          >
            <Send className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  )
}

function RightPanel({
  view,
  onViewChange,
  logs = [],
  logsLoading = false,
  citationMap = {},
  activeSectionTitle = null,
}: {
  view: RightPanelView
  onViewChange: (v: RightPanelView) => void
  logs?: import('@/types/api').ProjectLogResponse[]
  logsLoading?: boolean
  citationMap?: Record<string, string>
  activeSectionTitle?: string | null
}) {
  return (
    <div className="flex h-full flex-col">
      {/* ─── 面板切换标签 ─────────────────────────────────────── */}
      <div className="flex items-center border-b border-border">
        <button
          type="button"
          onClick={() => onViewChange('logs')}
          className={cn(
            'flex flex-1 items-center justify-center gap-1.5 px-3 py-2.5 text-xs font-medium transition-colors',
            view === 'logs'
              ? 'border-b-2 border-emerald-500 text-emerald-600'
              : 'text-muted-foreground hover:text-foreground',
          )}
        >
          <Terminal className="h-3.5 w-3.5" />
          日志
        </button>
        <button
          type="button"
          onClick={() => onViewChange('citations')}
          className={cn(
            'flex flex-1 items-center justify-center gap-1.5 px-3 py-2.5 text-xs font-medium transition-colors',
            view === 'citations'
              ? 'border-b-2 border-violet-500 text-violet-600'
              : 'text-muted-foreground hover:text-foreground',
          )}
        >
          <Quote className="h-3.5 w-3.5" />
          引用
        </button>
        <button
          type="button"
          onClick={() => onViewChange('agent-chat')}
          className={cn(
            'flex flex-1 items-center justify-center gap-1.5 px-3 py-2.5 text-xs font-medium transition-colors',
            view === 'agent-chat'
              ? 'border-b-2 border-primary text-primary'
              : 'text-muted-foreground hover:text-foreground',
          )}
        >
          <Bot className="h-3.5 w-3.5" />
          AI 助手
        </button>
      </div>

      {/* ─── 面板内容 ─────────────────────────────────────────── */}
      <div className="flex-1 overflow-hidden">
        {view === 'logs' && (
          <div className="h-full bg-slate-900">
            <TerminalTimeline logs={logs} isLoading={logsLoading} />
          </div>
        )}
        {view === 'citations' && (
          <div className="h-full overflow-y-auto">
            <CitationsPanel citationMap={citationMap} />
          </div>
        )}
        {view === 'agent-chat' && <AgentChatPanel activeSectionTitle={activeSectionTitle} />}
      </div>
    </div>
  )
}

// ================================================================
// 主页面组件
// ================================================================

export function WorkspacePage() {
  const { projectId } = useParams<{ projectId: string }>()
  const [activeSectionTitle, setActiveSectionTitle] = useState<string | null>(null)
  const [rightPanelView, setRightPanelView] = useState<RightPanelView>('logs')
  const [citationMap, setCitationMap] = useState<Record<string, string>>({})

  // ─── 状态轮询 ──────────────────────────────────────────────
  const {
    data: statusData,
    isLoading: statusLoading,
    isError: statusError,
    error: statusErrorObj,
  } = useProjectStatus({ projectId, enabled: true })

  const flags = getStatusFlags(statusData?.project_status)

  // ─── 🆕 实时运行日志 ──────────────────────────────────────
  const { logs, isLoading: logsLoading } = useProjectLogs({
    projectId,
    status: statusData?.project_status,
    enabled: true,
  })

  // ─── 资料审核（waiting_for_sources 阶段启用） ──────────────
  const sourcesEnabled = flags.isWaitingSources
  const {
    data: sourcesData,
    isLoading: sourcesLoading,
    isError: sourcesError,
  } = useSources(projectId, sourcesEnabled)

  // ─── 资料审核 Mutation ─────────────────────────────────────
  const reviewSourcesMutation = useReviewSources()

  // ─── 文档块查询（drafting / completed 阶段启用） ────────────
  const blocksEnabled = flags.isDrafting || flags.isCompleted
  const {
    data: blocksData,
    isLoading: blocksLoading,
  } = useProjectBlocks(projectId, blocksEnabled)

  // ─── 大纲确认 Mutation ─────────────────────────────────────
  const approveMutation = useApproveOutline()

  // ─── Editor Sync（drafting 阶段启用 SSE） ──────────────────
  const {
    blocks: editorBlocks,
    isStreaming,
    streamedCount,
  } = useEditorSync({
    projectId,
    enabled: flags.isDrafting,
    initialBlocks: blocksData?.blocks ?? [],
  })

  // ─── 已完成项目：直接用 blocksData（无需 SSE） ──────────
  const displayBlocks = flags.isCompleted
    ? (blocksData?.blocks ?? []).map((b) => ({ ...b, isStreaming: false }))
    : editorBlocks
  const displayIsStreaming = flags.isCompleted ? false : isStreaming
  const displayStreamedCount = flags.isCompleted ? 0 : streamedCount

  // ─── 解析大纲章节 ──────────────────────────────────────────
  const outlineSections = useMemo<OutlineSection[]>(() => {
    const content = statusData?.outline_content
    if (!content) return []

    const lines = content.split('\n')
    const sections: OutlineSection[] = []
    let index = 0

    for (const line of lines) {
      const trimmed = line.trim()
      if (trimmed.startsWith('## ')) {
        const title = trimmed.replace(/^##\s*/, '')
        sections.push({ title, raw: trimmed, index })
        index++
      }
    }

    return sections
  }, [statusData?.outline_content])

  // ─── 编辑器引用 ─────────────────────────────────────────────
  const editorRef = useRef<Editor | null>(null)
  const handleEditorReady = useCallback((editor: Editor) => {
    editorRef.current = editor
  }, [])

  // ─── 引用点击：自动切换到引用面板 ────────────────────────
  const { setActiveCitationId } = useCitationStore()
  const handleCitationClick = useCallback((id: string) => {
    setActiveCitationId(id)
    setRightPanelView('citations')
  }, [setActiveCitationId])

  // ─── 🌊 SSE 流式渲染 ──────────────────────────────────────
  useDraftStream({
    editor: editorRef.current,
    projectId,
    enabled: flags.isDrafting,
    onSectionStart: (title) => {
      setActiveSectionTitle(title)
    },
    onDraftComplete: () => {
      console.log('[WorkspacePage] 草稿流完成')
    },
  })

  // ─── 资料审核回调 ──────────────────────────────────────────
  const handleReviewSources = useCallback(async (selectedUrls: string[]) => {
    if (!projectId) return
    await reviewSourcesMutation.mutateAsync({
      projectId,
      data: { selected_urls: selectedUrls },
    })
  }, [projectId, reviewSourcesMutation])

  // ─── 大纲确认回调 ──────────────────────────────────────────
  const handleConfirmOutline = useCallback(async (outline: string) => {
    if (!projectId) return
    await approveMutation.mutateAsync({
      projectId,
      data: { outline },
    })
  }, [projectId, approveMutation])

  // ─── 章节点击 ──────────────────────────────────────────────
  const handleSectionClick = useCallback((title: string) => {
    setActiveSectionTitle(title)
  }, [])

  // ─── 加载中状态 ────────────────────────────────────────────
  if (statusLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
          <p className="text-sm text-muted-foreground">加载工作台...</p>
        </div>
      </div>
    )
  }

  // ─── 错误状态 ──────────────────────────────────────────────
  if (statusError || !statusData) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="flex flex-col items-center gap-4 text-destructive">
          <AlertCircle className="h-10 w-10" />
          <p className="font-medium">加载失败</p>
          <p className="text-sm text-muted-foreground">
            {(statusErrorObj as Error)?.message ?? '项目不存在或网络错误'}
          </p>
          <Link to="/">
            <Button variant="outline" size="sm">
              返回控制台
            </Button>
          </Link>
        </div>
      </div>
    )
  }

  const topic = statusData.topic
  const tasks = statusData.tasks
  const percentage = statusData.progress?.percentage ?? 0

  // ─── 渲染三栏布局 ──────────────────────────────────────────

  return (
    <ThreePaneLayout
      // ── 左栏：大纲目录 ───────────────────────────────────
      leftPane={
        <OutlineTree
          sections={outlineSections}
          activeSectionTitle={activeSectionTitle}
          onSectionClick={handleSectionClick}
          isStreaming={isStreaming}
        />
      }

      // ── 中栏：编辑器 ─────────────────────────────────────
      centerPane={
        <div className="flex h-full flex-col">
          {/* ─── 顶部导航条 ──────────────────────────────────── */}
          <div className="flex items-center gap-3 border-b border-border px-4 py-2.5">
            <Link
              to="/"
              className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              <ArrowLeft className="h-3.5 w-3.5" />
              返回
            </Link>

            <span className="h-3 w-px bg-border" />

            <h1 className="truncate text-sm font-medium">{topic}</h1>

            {/* 状态指示器 + 下载按钮 */}
            <div className="ml-auto flex items-center gap-2">
              <span
                className={cn(
                  'inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium',
                  flags.isCompleted && 'bg-emerald-50 text-emerald-600',
                  flags.isFailed && 'bg-red-50 text-red-600',
                  flags.isPreparing && 'bg-blue-50 text-blue-600',
                  flags.isWaitingSources && 'bg-blue-50 text-blue-600',
                  flags.isPreparingOutline && 'bg-blue-50 text-blue-600',
                  flags.isWaitingApproval && 'bg-amber-50 text-amber-600',
                  flags.isDrafting && 'bg-violet-50 text-violet-600',
                )}
              >
                {flags.isCompleted && '已完成'}
                {flags.isFailed && '失败'}
                {flags.isPreparing && '资料搜索中'}
                {flags.isWaitingSources && '待审核资料'}
                {flags.isPreparingOutline && '大纲生成中'}
                {flags.isWaitingApproval && '待确认大纲'}
                {flags.isDrafting && 'AI 撰写中'}
              </span>
              {flags.isCompleted && statusData.pdf_path && (
                <a
                  href={`/api/v1/files/${statusData.pdf_path}`}
                  download
                  className="inline-flex items-center gap-1 rounded-md bg-emerald-600 px-2.5 py-1 text-[11px] font-medium text-white hover:bg-emerald-700 transition-colors"
                >
                  <Download className="h-3 w-3" />
                  下载 PDF
                </a>
              )}
            </div>
          </div>

          {/* ─── ProgressTracker ───────────────────────────── */}
          {tasks.length > 0 && (flags.isPreparing || flags.isPreparingOutline || flags.isDrafting) && (
            <div className="border-b border-border px-4 py-3">
              <ProgressTracker
                tasks={tasks}
                percentage={percentage}
                projectStatus={statusData.project_status}
                currentStep={statusData.current_step}
              />
            </div>
          )}

          {/* ─── 🎯 资料审核面板（WAITING_FOR_SOURCES） ── */}
          {flags.isWaitingSources && (
            <div className="p-4">
              {sourcesLoading ? (
                <div className="flex items-center justify-center rounded-xl border border-blue-200 bg-blue-50/40 p-8">
                  <div className="flex flex-col items-center gap-3">
                    <Loader2 className="h-6 w-6 animate-spin text-blue-500" />
                    <p className="text-sm text-blue-600">加载资料来源...</p>
                  </div>
                </div>
              ) : sourcesError || !sourcesData ? (
                <div className="flex items-center justify-center rounded-xl border border-red-200 bg-red-50/40 p-8">
                  <div className="flex flex-col items-center gap-3">
                    <AlertCircle className="h-6 w-6 text-red-500" />
                    <p className="text-sm text-red-600">加载资料来源失败</p>
                    <p className="text-xs text-muted-foreground">请刷新页面重试</p>
                  </div>
                </div>
              ) : sourcesData.sources.length === 0 ? (
                <div className="flex items-center justify-center rounded-xl border border-dashed border-blue-200 bg-blue-50/20 p-8">
                  <div className="flex flex-col items-center gap-3">
                    <Search className="h-6 w-6 text-blue-400" />
                    <p className="text-sm text-blue-600">暂无搜索到的资料</p>
                    <p className="text-xs text-muted-foreground">请确认搜索是否已完成，或直接进入下一阶段</p>
                  </div>
                </div>
              ) : (
                <SourcesReview
                  projectId={projectId!}
                  sources={sourcesData.sources}
                  topic={statusData.topic}
                  onConfirm={handleReviewSources}
                  isConfirming={reviewSourcesMutation.isPending}
                  confirmError={reviewSourcesMutation.error?.message ?? null}
                />
              )}
            </div>
          )}

          {/* ─── 🎯 大纲确认横幅（WAITING_FOR_OUTLINE） ── */}
          {flags.isWaitingApproval && (
            <div className="p-4">
              <OutlineApproval
                projectId={projectId!}
                outlineContent={statusData.outline_content}
                sections={outlineSections}
                onConfirm={handleConfirmOutline}
                isConfirming={approveMutation.isPending}
                confirmError={approveMutation.error?.message ?? null}
              />
            </div>
          )}

          {/* ─── BlockEditor（drafting / completed 阶段） ────── */}
          {(flags.isDrafting || flags.isCompleted) && (
            <div className="flex-1 overflow-hidden">
              <BlockEditor
                blocks={displayBlocks}
                isStreaming={displayIsStreaming}
                streamedCount={displayStreamedCount}
                readOnly={flags.isCompleted}
                activeSectionTitle={activeSectionTitle}
                onSectionTitleChange={setActiveSectionTitle}
                onEditorReady={handleEditorReady}
                onCitationMapUpdate={setCitationMap}
                onCitationClick={handleCitationClick}
              />
            </div>
          )}

          {/* ─── preparing_data / preparing_outline 时的编辑器骨架 ── */}
          {(flags.isPreparing || flags.isPreparingOutline) && (
            <div className="flex flex-1 items-center justify-center">
              <div className="flex flex-col items-center gap-3 text-center">
                <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
                <div className="space-y-1">
                  <p className="text-sm font-medium text-muted-foreground">
                    AI 正在搜集资料并生成大纲
                  </p>
                  <p className="text-xs text-muted-foreground/60">
                    完成后将自动展示大纲供您审阅确认
                  </p>
                </div>
              </div>
            </div>
          )}
        </div>
      }

      // ── 右栏：日志/引用/对话 ─────────────────────────
      rightPane={
        <RightPanel
          view={rightPanelView}
          onViewChange={setRightPanelView}
          logs={logs}
          logsLoading={logsLoading}
          citationMap={citationMap}
          activeSectionTitle={activeSectionTitle}
        />
      }
    />
  )
}
