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
import {
  ArrowLeft, Loader2, AlertCircle, Search, FileText, Download,
  Quote, Bot, Terminal, Send, ExternalLink, Upload, ChevronDown,
  Check, FileUp, X, Paperclip,
} from 'lucide-react'
import { Button } from '@/components/common/button'
import { ProgressTracker } from '@/components/projects/ProgressTracker'
import { SourcesReview } from '@/components/projects/SourcesReview'
import { OutlineApproval } from '@/components/projects/OutlineApproval'
import { ThreePaneLayout, useThreePane } from '@/components/layout/ThreePaneLayout'
import { BlockEditor } from '@/components/editor/BlockEditor'
import { cn } from '@/lib/utils'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/common/dialog'
import {
  Popover,
  PopoverTrigger,
  PopoverContent,
} from '@/components/common/popover'
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
import { editorApi, projectsApi } from '@/lib/api'
import type { EditorChatMessage, EditorChatRequest } from '@/types/api'
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

// ─── 对话模式常量 ───────────────────────────────────────────
const CHAT_MODES = [
  { value: 'work' as const, label: '工作模式', desc: '带 RAG 知识库检索' },
  { value: 'chat' as const, label: '自由闲聊', desc: '通用对话' },
]

interface AgentChatPanelProps {
  activeSectionTitle: string | null
  projectId: string
}

function AgentChatPanel({ activeSectionTitle, projectId }: AgentChatPanelProps) {
  const [messages, setMessages] = useState<Array<{ role: 'user' | 'assistant'; text: string }>>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [chatMode, setChatMode] = useState<'work' | 'chat'>('work')
  const [streamingText, setStreamingText] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streamingText])

  const handleSend = useCallback(async () => {
    const trimmed = input.trim()
    if (!trimmed || loading) return

    const userMsg = { role: 'user' as const, text: trimmed }
    setMessages((prev) => [...prev, userMsg])
    setInput('')
    setLoading(true)
    setStreamingText('')

    // 构建历史消息（不含最新用户消息）
    const history: EditorChatMessage[] = messages.map((m) => ({
      role: m.role,
      content: m.text,
    }))

    const chatRequest: EditorChatRequest = {
      project_id: projectId,
      chat_mode: chatMode,
      message: trimmed,
      selected_text: activeSectionTitle ?? null,
      history,
    }

    abortRef.current = new AbortController()

    try {
      const response = await editorApi.chat(chatRequest)
      const reader = response.body?.getReader()
      if (!reader) throw new Error('No response body')

      const decoder = new TextDecoder()
      let buffer = ''
      let currentEventType = ''
      let fullText = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        // 按行解析 SSE
        while (buffer.includes('\n')) {
          const idx = buffer.indexOf('\n')
          const line = buffer.slice(0, idx).trimEnd()
          buffer = buffer.slice(idx + 1)

          if (line.startsWith('event: ')) {
            currentEventType = line.slice(7).trim()
          } else if (line.startsWith('data: ')) {
            try {
              const payload = JSON.parse(line.slice(6))
              if (currentEventType === 'content' && payload.text) {
                fullText += payload.text
                setStreamingText(fullText)
              } else if (currentEventType === 'error') {
                fullText += `\n\n⚠️ ${payload.error || '流式输出中断'}`
                setStreamingText(fullText)
              }
              // 'done' event — just complete naturally
            } catch {
              // JSON 解析失败，跳过
            }
          }

          // 空行 = 事件块结束，重置事件类型
          if (line === '') {
            currentEventType = ''
          }
        }
      }

      // 流结束，将累积文本写入消息列表
      setMessages((prev) => [...prev, { role: 'assistant', text: fullText }])
      setStreamingText('')
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        // 用户取消，不显示错误
      } else {
        setMessages((prev) => [
          ...prev,
          { role: 'assistant', text: '⚠️ 请求失败，请检查网络或 API 配置。' },
        ])
      }
      setStreamingText('')
    } finally {
      setLoading(false)
      abortRef.current = null
    }
  }, [input, loading, chatMode, messages, projectId, activeSectionTitle])

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        handleSend()
      }
    },
    [handleSend],
  )

  const handleStopStreaming = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort()
      abortRef.current = null
    }
    // 保存已生成的内容
    if (streamingText) {
      setMessages((prev) => [...prev, { role: 'assistant', text: streamingText + '\n\n⏸️ 已中止生成' }])
    }
    setStreamingText('')
    setLoading(false)
  }, [streamingText])

  // 清理 abort controller
  useEffect(() => {
    return () => {
      abortRef.current?.abort()
    }
  }, [])

  const hasContent = messages.length > 0 || streamingText

  return (
    <div className="flex h-full flex-col">
      {/* ─── 顶部：对话模式切换 + 清空 ────────────────────────── */}
      <div className="flex items-center gap-2 border-b border-border px-3 py-2">
        <div className="flex flex-1 rounded-md bg-muted p-0.5">
          {CHAT_MODES.map((m) => (
            <button
              key={m.value}
              type="button"
              onClick={() => setChatMode(m.value)}
              className={cn(
                'flex-1 rounded-sm px-2 py-1 text-[11px] font-medium transition-colors',
                chatMode === m.value
                  ? 'bg-background text-foreground shadow-sm'
                  : 'text-muted-foreground hover:text-foreground',
              )}
            >
              {m.label}
            </button>
          ))}
        </div>
        {messages.length > 0 && !loading && (
          <button
            type="button"
            onClick={() => setMessages([])}
            className="shrink-0 rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
            title="清空对话"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </div>

      {/* ─── 消息列表 ──────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {!hasContent ? (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <Bot className="mb-2 h-8 w-8 text-muted-foreground/40" />
            <p className="text-xs text-muted-foreground">
              {chatMode === 'work'
                ? '基于项目知识库进行专业对话，辅助报告撰写。'
                : '自由聊天模式，与 AI 交流产品分析相关话题。'}
            </p>
            {activeSectionTitle && (
              <p className="mt-1 text-[11px] text-muted-foreground/60">
                当前章节：{activeSectionTitle}
              </p>
            )}
          </div>
        ) : (
          <>
            {messages.map((msg, i) => (
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
            ))}
          </>
        )}

        {/* ─── 流式输出中的消息 ─────────────────────────────── */}
        {streamingText && (
          <div className="mr-6 rounded-lg bg-muted px-3 py-2">
            <p className="mb-1 text-[10px] font-medium text-muted-foreground">AI 助手</p>
            <p className="whitespace-pre-wrap text-xs leading-relaxed">
              {streamingText}
              <span className="ml-0.5 inline-block h-3.5 w-0.5 animate-pulse bg-primary align-middle" />
            </p>
          </div>
        )}

        {/* ─── 等待首字时的加载动画 ──────────────────────────── */}
        {loading && !streamingText && (
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

      {/* ─── 输入框 ────────────────────────────────────────── */}
      <div className="border-t border-border p-3">
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              chatMode === 'work'
                ? activeSectionTitle
                  ? `针对「${activeSectionTitle}」提问（Enter 发送）`
                  : '基于知识库提问（Enter 发送）'
                : '输入消息（Enter 发送）'
            }
            disabled={loading}
            rows={2}
            className="flex-1 resize-none rounded-lg border border-border bg-background px-3 py-2 text-xs placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-50"
          />
          {loading ? (
            <button
              type="button"
              onClick={handleStopStreaming}
              className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-destructive text-destructive-foreground hover:bg-destructive/90 transition-colors"
              title="停止生成"
            >
              <span className="h-3 w-3 rounded-sm bg-current" />
            </button>
          ) : (
            <button
              type="button"
              onClick={handleSend}
              disabled={!input.trim()}
              className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-colors"
            >
              <Send className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

// ================================================================
// 本地上传文档弹窗 (Task 2)
// ================================================================

interface UploadDocsDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  projectId: string
}

function UploadDocsDialog({ open, onOpenChange, projectId }: UploadDocsDialogProps) {
  const [selectedFiles, setSelectedFiles] = useState<File[]>([])
  const [uploading, setUploading] = useState(false)
  const [uploadResult, setUploadResult] = useState<{ chunk_count: number; message: string } | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // 重置状态
  useEffect(() => {
    if (!open) {
      // 延迟重置，避免关闭动画时看到状态跳变
      const timer = setTimeout(() => {
        setSelectedFiles([])
        setUploadResult(null)
      }, 200)
      return () => clearTimeout(timer)
    }
  }, [open])

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (files && files.length > 0) {
      setSelectedFiles((prev) => [...prev, ...Array.from(files)])
    }
    // 重置 input 以便重复选择同名文件
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  const handleRemoveFile = (index: number) => {
    setSelectedFiles((prev) => prev.filter((_, i) => i !== index))
    setUploadResult(null)
  }

  const handleUpload = async () => {
    if (selectedFiles.length === 0 || uploading) return

    setUploading(true)
    setUploadResult(null)

    const total = selectedFiles.length
    let totalChunks = 0

    try {
      for (let i = 0; i < total; i++) {
        if (total > 1) {
          setUploadResult({ chunk_count: -1, message: `正在上传（${i + 1}/${total}）...` })
        }

        const result = await projectsApi.uploadDocs(projectId, [selectedFiles[i]])
        totalChunks += result.chunk_count

        // 最后一个文件上传完成
        if (i === total - 1) {
          setUploadResult({
            chunk_count: totalChunks,
            message: total > 1
              ? `${total} 个文件上传完成，共 ${totalChunks} 个切片已入库`
              : result.message,
          })
        }
      }
      setSelectedFiles([])
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : '上传失败'
      setUploadResult({ chunk_count: 0, message: `❌ ${message}` })
    } finally {
      setUploading(false)
    }
  }

  const totalSize = selectedFiles.reduce((sum, f) => sum + f.size, 0)
  const sizeLabel = totalSize < 1024 * 1024
    ? `${(totalSize / 1024).toFixed(1)} KB`
    : `${(totalSize / (1024 * 1024)).toFixed(1)} MB`

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileUp className="h-5 w-5" />
            上传参考文件
          </DialogTitle>
          <DialogDescription>
            支持 PDF、DOCX、TXT 格式。上传后的文档将自动解析并加入项目知识库，供 AI 撰写时参考。
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* 拖拽/点击上传区域 */}
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
            className="flex w-full flex-col items-center gap-2 rounded-lg border-2 border-dashed border-border bg-muted/30 px-4 py-6 transition-colors hover:border-primary/50 hover:bg-muted/50 disabled:opacity-50"
          >
            <Upload className="h-6 w-6 text-muted-foreground" />
            <p className="text-xs text-muted-foreground">点击选择文件</p>
            <p className="text-[10px] text-muted-foreground/60">.pdf .docx .txt</p>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept=".pdf,.docx,.txt"
              onChange={handleFileChange}
              className="hidden"
            />
          </button>

          {/* 已选文件列表 */}
          {selectedFiles.length > 0 && (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <p className="text-xs font-medium text-muted-foreground">
                  已选 {selectedFiles.length} 个文件（{sizeLabel}）
                </p>
                <button
                  type="button"
                  onClick={() => setSelectedFiles([])}
                  className="text-[10px] text-muted-foreground hover:text-foreground"
                >
                  清空
                </button>
              </div>
              <div className="max-h-32 space-y-1 overflow-y-auto">
                {selectedFiles.map((file, i) => (
                  <div
                    key={`${file.name}-${i}`}
                    className="flex items-center gap-2 rounded-md bg-muted/50 px-3 py-1.5"
                  >
                    <Paperclip className="h-3 w-3 shrink-0 text-muted-foreground" />
                    <span className="flex-1 truncate text-xs">{file.name}</span>
                    <span className="text-[10px] text-muted-foreground">
                      {(file.size / 1024).toFixed(0)} KB
                    </span>
                    <button
                      type="button"
                      onClick={() => handleRemoveFile(i)}
                      className="shrink-0 rounded p-0.5 text-muted-foreground hover:text-destructive"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 上传结果 */}
          {uploadResult && (
            <div
              className={cn(
                'rounded-lg px-3 py-2.5 text-xs',
                uploadResult.chunk_count < 0
                  ? 'bg-blue-50 text-blue-700'
                  : uploadResult.chunk_count > 0
                    ? 'bg-emerald-50 text-emerald-700'
                    : 'bg-red-50 text-red-700',
              )}
            >
              {uploadResult.chunk_count < 0 && (
                <Loader2 className="mr-1.5 inline h-3 w-3 animate-spin" />
              )}
              {uploadResult.message}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            size="sm"
            onClick={() => onOpenChange(false)}
            disabled={uploading}
          >
            关闭
          </Button>
          <Button
            size="sm"
            onClick={handleUpload}
            disabled={selectedFiles.length === 0 || uploading}
            loading={uploading}
          >
            {uploading ? '上传解析中...' : '开始上传'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ================================================================
// 模板选择下拉框 (Task 3)
// ================================================================

const TEMPLATE_OPTIONS = [
  { key: 'standard', label: '标准产品分析报告 (默认)', desc: '完整的产品分析全貌' },
  { key: 'competitive', label: '商业竞品分析', desc: '聚焦竞争对手对比' },
  { key: 'investment', label: '投资视角简报', desc: '面向投资人的精简版' },
] as const

type TemplateKey = (typeof TEMPLATE_OPTIONS)[number]['key']

interface TemplatePopoverProps {
  value: TemplateKey
  onChange: (key: TemplateKey) => void
}

function TemplatePopover({ value, onChange }: TemplatePopoverProps) {
  const [open, setOpen] = useState(false)
  const selected = TEMPLATE_OPTIONS.find((t) => t.key === value) ?? TEMPLATE_OPTIONS[0]

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" className="gap-1.5">
          <FileText className="h-3.5 w-3.5" />
          <span className="max-w-[120px] truncate text-[11px]">{selected.label}</span>
          <ChevronDown className="h-3 w-3 text-muted-foreground" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-64 p-1">
        <div className="space-y-0.5">
          {TEMPLATE_OPTIONS.map((option) => {
            const isActive = value === option.key
            return (
              <button
                key={option.key}
                type="button"
                onClick={() => {
                  onChange(option.key)
                  setOpen(false)
                }}
                className={cn(
                  'flex w-full items-start gap-2 rounded-sm px-3 py-2 text-left transition-colors',
                  isActive
                    ? 'bg-primary/10 text-primary'
                    : 'text-foreground hover:bg-muted',
                )}
              >
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-medium">{option.label}</p>
                  <p className="text-[10px] text-muted-foreground">{option.desc}</p>
                </div>
                {isActive && <Check className="mt-0.5 h-3.5 w-3.5 shrink-0" />}
              </button>
            )
          })}
        </div>
      </PopoverContent>
    </Popover>
  )
}

function RightPanel({
  view,
  onViewChange,
  logs = [],
  logsLoading = false,
  citationMap = {},
  activeSectionTitle = null,
  projectId = '',
}: {
  view: RightPanelView
  onViewChange: (v: RightPanelView) => void
  logs?: import('@/types/api').ProjectLogResponse[]
  logsLoading?: boolean
  citationMap?: Record<string, string>
  activeSectionTitle?: string | null
  projectId?: string
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
        {view === 'agent-chat' && <AgentChatPanel activeSectionTitle={activeSectionTitle} projectId={projectId} />}
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

  // ─── 🆕 UI 状态 ──────────────────────────────────────────────
  const [uploadDialogOpen, setUploadDialogOpen] = useState(false)
  const [selectedTemplate, setSelectedTemplate] = useState<TemplateKey>('standard')
  const [exportingPdf, setExportingPdf] = useState(false)

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

  // ─── 🆕 手动导出 PDF ────────────────────────────────────────
  const handleExportPdf = useCallback(async () => {
    if (!projectId || exportingPdf) return

    setExportingPdf(true)
    try {
      // 拼接所有 editorBlocks 内容为 HTML
      const blocks = displayBlocks ?? []
      const htmlParts = blocks.map((b) => {
        const title = b.section_title ? `<h2>${b.section_title}</h2>` : ''
        // 简单的 Markdown → HTML 转换（段落换行）
        const contentHtml = (b.content || '')
          .split('\n\n')
          .map((p) => `<p>${p.trim()}</p>`)
          .join('')
        return title + contentHtml
      })
      const htmlContent = `<html><body>${htmlParts.join('\n')}</body></html>`

      const result = await projectsApi.exportPdf(projectId, {
        html_content: htmlContent,
      })

      // 触发下载
      if (result.download_url) {
        const a = document.createElement('a')
        a.href = result.download_url
        a.download = result.filename || `${statusData?.topic || 'report'}.pdf`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : '导出失败'
      console.error('[ExportPdf]', message)
      alert(`PDF 导出失败: ${message}`)
    } finally {
      setExportingPdf(false)
    }
  }, [projectId, exportingPdf, displayBlocks, statusData?.topic])

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
    <>
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
          <div className="flex items-center gap-2 border-b border-border px-4 py-2.5">
            <Link
              to="/"
              className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors shrink-0"
            >
              <ArrowLeft className="h-3.5 w-3.5" />
              返回
            </Link>

            <span className="h-3 w-px bg-border shrink-0" />

            <h1 className="truncate text-sm font-medium min-w-0">{topic}</h1>

            {/* 🆕 模板选择下拉框 */}
            <TemplatePopover value={selectedTemplate} onChange={setSelectedTemplate} />

            {/* 🆕 上传参考文件按钮 */}
            <Button
              size="sm"
              variant="outline"
              onClick={() => setUploadDialogOpen(true)}
              className="gap-1.5 shrink-0"
            >
              <Upload className="h-3.5 w-3.5" />
              <span className="hidden sm:inline text-[11px]">上传参考文件</span>
            </Button>

            {/* 状态指示器 + 导出/下载按钮 */}
            <div className="ml-auto flex items-center gap-2 shrink-0">
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

              {/* 🆕 手动导出 PDF（drafting / completed 状态） */}
              {(flags.isDrafting || flags.isCompleted) && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={handleExportPdf}
                  disabled={exportingPdf}
                  loading={exportingPdf}
                  className="gap-1"
                >
                  <Download className="h-3 w-3" />
                  <span className="hidden sm:inline text-[11px]">
                    {exportingPdf ? '导出中...' : '导出 PDF'}
                  </span>
                </Button>
              )}

              {/* 原有的自动生成 PDF 下载链接（completed 且 pdf_path 存在时） */}
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
          projectId={projectId ?? ''}
        />
      }
    />

    {/* 🆕 上传文件弹窗（独立于三栏布局，全局面板） */}
    <UploadDocsDialog
      open={uploadDialogOpen}
      onOpenChange={setUploadDialogOpen}
      projectId={projectId ?? ''}
    />
    </>
  )
}
