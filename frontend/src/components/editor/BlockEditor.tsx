/**
 * ============================================================
 * BlockEditor —— Tiptap 块级富文本编辑器 (Phase 3)
 *
 * 核心能力：
 * 1. 接收 DocumentBlock[] 数组，转换为 Tiptap JSON 内容
 * 2. 使用 @tailwindcss/typography（prose 类）处理排版
 * 3. 使用 CitationMark（[^数字] 格式）渲染引用角标
 * 4. 集成 InlineAIBubble：选中文字 → AI 改写/扩写/精简
 * 5. 集成 DiffViewNode：AI 改写结果预览与确认
 *
 * 技术选型：
 * - @tiptap/react + StarterKit
 * - @tiptap/extension-underline
 * - @tiptap/extension-placeholder
 * - CitationMark（自定义 Mark，渲染 <sup> 角标）
 * - InlineAIBubble（BubbleMenu 扩展，调用 /api/v1/editor/revise）
 *
 * 内容转换流程：
 *   DocumentBlock[].content (Markdown)
 *     → extractCitations() 提取 [^N] 引用
 *       → convertToHtml() 将 Markdown 转 HTML
 *         → Tiptap 解析为 ProseMirror 文档
 *
 * 引用角标交互：
 *   点击 <sup.citation-badge> → useCitationStore.activeCitationId
 *     → 右侧 CitationsPanel 自动展示对应引用详情
 * ============================================================
 */

import { useMemo, useCallback, useEffect, useRef } from 'react'
import { useEditor, EditorContent, type Editor } from '@tiptap/react'
import type { Node } from '@tiptap/pm/model'
import StarterKit from '@tiptap/starter-kit'
import Underline from '@tiptap/extension-underline'
import Placeholder from '@tiptap/extension-placeholder'
import { CitationMark } from './extensions/CitationMark'
import { InlineAIBubble } from './InlineAIBubble'
import { useCitationStore } from '@/hooks/useCitationStore'
import type { DocumentBlockResponse } from '@/types/api'
import type { EditorBlock } from '@/types/index'
import { cn } from '@/lib/utils'

// ─── 常量 ──────────────────────────────────────────────────────

/** 默认 Tiptap 配置 */
const DEFAULT_EDITOR_CONFIG = {
  extensions: [
    StarterKit.configure({
      codeBlock: false,
      heading: { levels: [1, 2, 3] },
    }),
    Underline,
    Placeholder.configure({ placeholder: '在此输入内容...' }),
    CitationMark.configure({ citationMap: {} }),
  ],
  editorProps: {
    attributes: {
      class:
        'prose prose-sm prose-stone max-w-none focus:outline-none min-h-[200px] px-8 py-6',
    },
  },
}

// ─── 辅助函数 ──────────────────────────────────────────────────

/**
 * 从 Markdown 内容中提取引用角标 [^N] 信息
 * 例如 "市场规膜达1000亿[^1]，增长率15%[^2]。"
 * → { "1": null, "2": null }
 */
function extractCitations(content: string): Record<string, string | null> {
  const citationMap: Record<string, string | null> = {}
  const regex = /\[\^(\d+)\]/g
  let match: RegExpExecArray | null
  while ((match = regex.exec(content)) !== null) {
    citationMap[match[1]] = null
  }
  return citationMap
}

/**
 * 将 Markdown 文本转换为 Tiptap 可接受的 HTML 内容
 *
 * 转换规则：
 * - ## 标题 → <h2>
 * - **粗体** → <strong>
 * - [^N] → <sup data-citation-id="N" class="citation-badge">N</sup>
 * - 普通段落 → <p>
 */
function convertToHtml(content: string): string {
  let html = content
    .replace(/&/g, '&')
    .replace(/</g, '<')
    .replace(/>/g, '>')

  // ## 标题
  html = html.replace(/^##\s+(.+)$/gm, '<h2>$1</h2>')

  // **粗体**
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')

  // *斜体*
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>')

  // [^N] 引用角标 → <sup class="citation-badge">
  html = html.replace(
    /\[\^(\d+)\]/g,
    '<sup data-citation-id="$1" class="citation-badge">$1</sup>',
  )

  // 按行包裹 <p>（非标题行）
  html = html
    .split('\n')
    .map((line) => {
      if (line.startsWith('<h') || line.trim() === '') return line
      return `<p>${line}</p>`
    })
    .join('\n')

  return html
}

/**
 * 将 DocumentBlock[] 合并为单个 Markdown 字符串
 * 保持 order_index 排序
 */
function blocksToMarkdown(blocks: DocumentBlockResponse[]): string {
  return blocks
    .sort((a, b) => a.order_index - b.order_index)
    .map((b) => b.content)
    .join('\n\n')
}

// ─── 工具栏按钮 ────────────────────────────────────────────────

interface ToolbarButtonProps {
  onClick: () => void
  isActive?: boolean
  label: string
  title: string
}

function ToolbarButton({ onClick, isActive, label, title }: ToolbarButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      className={cn(
        'inline-flex h-8 w-8 items-center justify-center rounded text-sm font-medium transition-colors',
        isActive
          ? 'bg-primary/10 text-primary'
          : 'text-muted-foreground hover:bg-muted hover:text-foreground',
      )}
    >
      {label}
    </button>
  )
}

// ─── 编辑器工具栏 ──────────────────────────────────────────────

interface EditorToolbarProps {
  editor: Editor | null
}

function EditorToolbar({ editor }: EditorToolbarProps) {
  if (!editor) return null

  return (
    <div className="flex items-center gap-0.5 border-b border-border px-4 py-2">
      <ToolbarButton
        onClick={() => editor.chain().focus().toggleBold().run()}
        isActive={editor.isActive('bold')}
        label="B"
        title="粗体"
      />
      <ToolbarButton
        onClick={() => editor.chain().focus().toggleItalic().run()}
        isActive={editor.isActive('italic')}
        label="I"
        title="斜体"
      />
      <ToolbarButton
        onClick={() => editor.chain().focus().toggleUnderline().run()}
        isActive={editor.isActive('underline')}
        label="U"
        title="下划线"
      />

      <span className="mx-1 h-5 w-px bg-border" />

      <ToolbarButton
        onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}
        isActive={editor.isActive('heading', { level: 2 })}
        label="H2"
        title="二级标题"
      />
      <ToolbarButton
        onClick={() => editor.chain().focus().toggleHeading({ level: 3 }).run()}
        isActive={editor.isActive('heading', { level: 3 })}
        label="H3"
        title="三级标题"
      />

      <span className="mx-1 h-5 w-px bg-border" />

      <ToolbarButton
        onClick={() => editor.chain().focus().toggleBulletList().run()}
        isActive={editor.isActive('bulletList')}
        label="•"
        title="无序列表"
      />
      <ToolbarButton
        onClick={() => editor.chain().focus().toggleOrderedList().run()}
        isActive={editor.isActive('orderedList')}
        label="1."
        title="有序列表"
      />
      <ToolbarButton
        onClick={() => editor.chain().focus().toggleBlockquote().run()}
        isActive={editor.isActive('blockquote')}
        label='"'
        title="引用"
      />

      <div className="ml-auto flex items-center gap-2">
        <span className="text-xs text-muted-foreground">
          {editor.storage.characterCount?.characters?.() || 0} 字
        </span>
      </div>
    </div>
  )
}

// ─── 编辑器组件 ────────────────────────────────────────────────

interface BlockEditorProps {
  /** 文档块列表（从后端 /blocks 获取） */
  blocks: EditorBlock[]
  /** 是否正在流式接收中 */
  isStreaming?: boolean
  /** 已流式接收的块数 */
  streamedCount?: number
  /** 编辑器是否只读（completed 阶段只读） */
  readOnly?: boolean
  /** 当前选中的章节标题 */
  activeSectionTitle?: string | null
  /** 选中章节变更回调 */
  onSectionTitleChange?: (title: string | null) => void
  /** 编辑器实例就绪回调 */
  onEditorReady?: (editor: Editor) => void
}

/**
 * BlockEditor 组件
 *
 * 使用方式：
 * ```tsx
 * <BlockEditor
 *   blocks={editorBlocks}
 *   isStreaming={isStreaming}
 *   readOnly={projectStatus === 'completed'}
 *   onEditorReady={(editor) => console.log('编辑器就绪')}
 * />
 * ```
 */
export function BlockEditor({
  blocks,
  isStreaming = false,
  streamedCount = 0,
  readOnly = false,
  activeSectionTitle,
  onSectionTitleChange,
  onEditorReady,
}: BlockEditorProps) {
  // ─── 将 blocks 转换为 Markdown → HTML ────────────────────
  const editorContent = useMemo(() => {
    if (blocks.length === 0) return '<p class="text-muted-foreground">等待内容生成...</p>'

    const markdown = blocksToMarkdown(blocks)
    return convertToHtml(markdown)
  }, [blocks])

  // ─── 合并所有 citation map ───────────────────────────────
  const globalCitationMap = useMemo(() => {
    const map: Record<string, string> = {}
    for (const block of blocks) {
      if (block.citations) {
        try {
          const parsed = JSON.parse(block.citations) as Record<string, string>
          Object.assign(map, parsed)
        } catch {
          // ignore parse errors
        }
      }
    }
    return map
  }, [blocks])

  const editorRef = useRef<HTMLDivElement>(null)
  const { setActiveCitationId } = useCitationStore()

  // ─── 创建编辑器实例 ──────────────────────────────────────
  const editor = useEditor({
    ...DEFAULT_EDITOR_CONFIG,
    extensions: [
      StarterKit.configure({
        codeBlock: false,
        heading: { levels: [1, 2, 3] },
      }),
      Underline,
      Placeholder.configure({
        placeholder: blocks.length === 0 ? 'AI 正在生成内容...' : '在此输入内容...',
      }),
      CitationMark.configure({
        citationMap: Object.fromEntries(
          Object.entries(globalCitationMap).map(([k, v]) => [
            k,
            { url: v, title: `引用 [^${k}]` },
          ]),
        ),
        onCitationClick: (citationId: string) => setActiveCitationId(citationId),
      }),
    ],
    editable: !readOnly,
    content: editorContent,
    onUpdate: ({ editor: ed }: { editor: Editor }) => {
      // 检测当前光标所在的章节标题
      const { from } = ed.state.selection
      const doc = ed.state.doc
      let currentSection: string | null = null

      doc.nodesBetween(0, from, (node: Node) => {
        if (node.type.name === 'heading' && node.attrs.level === 2) {
          currentSection = node.textContent
        }
      })

      if (currentSection !== activeSectionTitle) {
        onSectionTitleChange?.(currentSection)
      }
    },
  })

  // ─── 编辑器就绪回调 ──────────────────────────────────────
  useMemo(() => {
    if (editor && onEditorReady) {
      onEditorReady(editor)
    }
  }, [editor, onEditorReady])

  // ─── 引用角标点击事件委托（依赖 editor DOM） ─────────────
  useEffect(() => {
    const el = editorRef.current
    if (!el) return

    const handleClick = (e: MouseEvent) => {
      const target = (e.target as HTMLElement).closest('.citation-badge')
      if (target && target instanceof HTMLElement) {
        const citationId = target.getAttribute('data-citation-id')
        if (citationId) {
          e.preventDefault()
          e.stopPropagation()
          setActiveCitationId(citationId)
        }
      }
    }

    el.addEventListener('click', handleClick)
    return () => el.removeEventListener('click', handleClick)
  }, [editor, setActiveCitationId])

  // ─── 当 blocks 变化时更新编辑器内容 ──────────────────────
  // 仅在流式接收完成或内容明显变化时更新
  useMemo(() => {
    if (editor && !isStreaming) {
      const currentHtml = editor.getHTML()
      if (currentHtml !== editorContent) {
        editor.commands.setContent(editorContent, { emitUpdate: false })
      }
    }
  }, [editor, editorContent, isStreaming])

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* ─── 工具栏 ─────────────────────────────────────────── */}
      <EditorToolbar editor={editor} />

      {/* ─── 流式接收指示器 ─────────────────────────────────── */}
      {isStreaming && (
        <div className="flex items-center gap-2 border-b border-blue-100 bg-blue-50/50 px-4 py-1.5">
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-blue-400 opacity-75" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-blue-500" />
          </span>
          <span className="text-xs text-blue-600">
            正在接收 AI 生成内容... 已接收 {streamedCount} 个块
          </span>
        </div>
      )}

      {/* ─── 编辑器区域 ─────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto" ref={editorRef}>
        {editor && (
          <>
            {/**
             * 🎯 InlineAIBubble —— 选中文字后的 AI 改写面板
             *
             * 包含：
             * - 快速操作按钮：扩写、精简、润色
             * - 自定义输入框：输入改写指令
             * - 调用 /api/v1/editor/revise 获取改写结果
             * - 以 DiffViewNode 展示差异（绿色高亮）
             * - 用户确认后才修改文档内容
             */}
            <InlineAIBubble editor={editor} />

            <EditorContent editor={editor} className="h-full" />
          </>
        )}

        {!editor && (
          <div className="flex items-center justify-center py-20 text-sm text-muted-foreground">
            编辑器加载中...
          </div>
        )}
      </div>
    </div>
  )
}
