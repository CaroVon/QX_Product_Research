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
import { ArrowLeft, Loader2, AlertCircle, FileText, BookOpen, Quote, Bot } from 'lucide-react'
import { Button } from '@/components/common/button'
import { ProgressTracker } from '@/components/projects/ProgressTracker'
import { OutlineApproval } from '@/components/projects/OutlineApproval'
import { ThreePaneLayout, useThreePane } from '@/components/layout/ThreePaneLayout'
import { BlockEditor } from '@/components/editor/BlockEditor'
import { cn } from '@/lib/utils'
import {
  useProjectStatus,
  useProjectBlocks,
  useApproveOutline,
  getStatusFlags,
} from '@/hooks/useProjectStatus'
import { useEditorSync } from '@/hooks/useEditorSync'
import { useDraftStream } from '@/hooks/useDraftStream'
import { useCitationStore } from '@/hooks/useCitationStore'
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

function CitationsPanel() {
  const activeCitationId = useCitationStore((s) => s.activeCitationId)

  return (
    <div className="p-4">
      <h3 className="text-sm font-medium">引用溯源</h3>

      {activeCitationId ? (
        <div className="mt-3 rounded-lg border border-violet-100 bg-violet-50/50 p-3">
          <p className="text-xs font-medium text-violet-700">
            引用 [^{activeCitationId}]
          </p>
          <p className="mt-1 text-[11px] text-violet-600/70">
            来源 URL 待后端返回
          </p>
          {/* TODO: 从 globalCitationMap 中查找对应 URL 展示 */}
        </div>
      ) : (
        <p className="mt-2 text-xs text-muted-foreground">
          点击编辑器中的引用角标可查看来源详情。
        </p>
      )}
    </div>
  )
}

function AgentChatPanel() {
  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-border px-4 py-3">
        <h3 className="text-sm font-medium">AI 助手</h3>
      </div>
      <div className="flex-1 p-4">
        <p className="text-xs text-muted-foreground">
          TODO: 与 AI Agent 对话，修改大纲或调整内容。
        </p>
      </div>
    </div>
  )
}

function RightPanel({ view, onClose }: RightPanelProps) {
  return (
    <div className="flex h-full flex-col">
      {/* ─── 面板切换标签 ─────────────────────────────────────── */}
      <div className="flex items-center border-b border-border">
        <button
          type="button"
          onClick={() => {}}
          className={cn(
            'flex flex-1 items-center justify-center gap-1.5 px-3 py-2.5 text-xs font-medium transition-colors',
            view === 'citations'
              ? 'border-b-2 border-primary text-primary'
              : 'text-muted-foreground hover:text-foreground',
          )}
        >
          <Quote className="h-3.5 w-3.5" />
          引用
        </button>
        <button
          type="button"
          onClick={() => {}}
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
      <div className="flex-1 overflow-y-auto">
        {view === 'citations' && <CitationsPanel />}
        {view === 'agent-chat' && <AgentChatPanel />}
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

  // ─── 状态轮询 ──────────────────────────────────────────────
  const {
    data: statusData,
    isLoading: statusLoading,
    isError: statusError,
    error: statusErrorObj,
  } = useProjectStatus({ projectId, enabled: true })

  const flags = getStatusFlags(statusData?.project_status)

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

            {/* 状态指示器 */}
            <span
              className={cn(
                'ml-auto inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium',
                flags.isCompleted && 'bg-emerald-50 text-emerald-600',
                flags.isFailed && 'bg-red-50 text-red-600',
                flags.isPreparing && 'bg-blue-50 text-blue-600',
                flags.isWaitingApproval && 'bg-amber-50 text-amber-600',
                flags.isDrafting && 'bg-violet-50 text-violet-600',
              )}
            >
              {flags.isCompleted && '已完成'}
              {flags.isFailed && '失败'}
              {flags.isPreparing && '资料准备中'}
              {flags.isWaitingApproval && '等待确认大纲'}
              {flags.isDrafting && 'AI 撰写中'}
            </span>
          </div>

          {/* ─── ProgressTracker（progress 阶段显示） ────────── */}
          {tasks.length > 0 && (flags.isPreparing || flags.isDrafting) && (
            <div className="border-b border-border px-4 py-3">
              <ProgressTracker
                tasks={tasks}
                percentage={percentage}
                projectStatus={statusData.project_status}
              />
            </div>
          )}

          {/* ─── 🎯 大纲确认横幅（WAITING_OUTLINE_APPROVAL） ── */}
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
              />
            </div>
          )}

          {/* ─── preparing_data 时的编辑器骨架 ──────────────── */}
          {flags.isPreparing && (
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

      // ── 右栏：引用/对话（可选） ─────────────────────────
      rightPane={
        <RightPanel
          view={flags.isDrafting || flags.isCompleted ? 'citations' : 'agent-chat'}
          onClose={() => {}}
        />
      }
    />
  )
}
