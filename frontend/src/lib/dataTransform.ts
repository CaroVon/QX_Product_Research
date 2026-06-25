/**
 * ============================================================
 * dataTransform —— 数据转换层 (Phase 3 v5)
 *
 * v5 重构（商业风格 + 内容密度优化）：
 * - 商业风格 slide 模板：左侧品牌色条 + 页眉(Logo/标题/页码) + 页脚
 * - 章节级渲染：配合后端 section-level DocumentBlock，减少碎片页
 * - 引用页尾优化：分隔线 + 紧凑排版 + 溢出检测
 * - 目录页：封面后自动插入 TOC 页
 * - 全局引用编号：跨章节 URL 去重 reconcile
 * - 双宽度高度估算：CJK/拉丁分别计算，减少提前分页
 * - 页码渲染：页眉右侧显示 Page N / M
 * - 移除冗余续页后缀：(续N) → 仅保持原标题
 * ============================================================
 */

import { marked } from 'marked'
import type { DocumentBlockResponse } from '@/types/api'
import type { CanvasElement } from '@/store/useCanvasStore'

// ══════════════════════════════════════════════════════════════
// 类型定义
// ══════════════════════════════════════════════════════════════

export interface KonvaSlide {
  pageNumber: number
  sectionTitle: string
  elements: CanvasElement[]
}

// ══════════════════════════════════════════════════════════════
// 画布物理常量（16:9）
// ══════════════════════════════════════════════════════════════

export const CANVAS_WIDTH = 1280
export const CANVAS_HEIGHT = 720

/** 品牌色系 */
const BRAND = {
  primary: '#2d7cf6',    // 主品牌色（科技蓝）
  primaryLight: '#6366f1', // 前端 accent（indigo，保持兼容）
  dark: '#0f1117',       // 深色背景
  heading: '#0f172a',    // 标题色
  body: '#334155',       // 正文色
  muted: '#94a3b8',      // 次要文字
  mutedLight: '#cbd5e1', // 最淡次要
  divider: '#e2e8f0',    // 细分割线
  footerBg: '#f1f5f9',   // 页脚背景
  white: '#ffffff',
}

// ══════════════════════════════════════════════════════════════
// 布局常量（v5 商业风格）
// ══════════════════════════════════════════════════════════════

const SIDEBAR_WIDTH = 6          // 左侧品牌色条宽度
const HEADER_HEIGHT = 56         // 页眉区域高度
const FOOTER_HEIGHT = 24         // 页脚区域高度
const CONTENT_START_Y = 68       // 正文起始 Y（页眉分隔线下方）
const CONTENT_END_Y = 694        // 正文截止 Y（页脚区域上方）
const CITATION_ZONE_Y = 648      // 引用区起始 Y
const CONTENT_WIDTH = 1140       // 正文内容宽度（1280 - 左侧边距60 - 右侧边距80）
const BODY_FONT_SIZE = 18
const HEADING_FONT_SIZE = 24
const CITATION_FONT_SIZE = 12
const IMAGE_RENDER_WIDTH = 800
const IMAGE_RENDER_HEIGHT = 450
const BLOCKQUOTE_BAR_WIDTH = 4

/** 内容 X 坐标（sidebar 右侧留白后） */
const CONTENT_X = 60
/** 列表缩进 X 坐标 */
const LIST_X = 80

// ══════════════════════════════════════════════════════════════
// 工具函数
// ══════════════════════════════════════════════════════════════

let _elementIdCounter = 0

function genId(): string {
  _elementIdCounter += 1
  return `el_${Date.now()}_${_elementIdCounter}_${Math.random().toString(36).substring(2, 6)}`
}

/**
 * 估算文本在 Canvas 中占据的高度（v5 双宽度字符计数版）。
 *
 * 对 CJK 字符和拉丁/数字分别计算宽度，比之前的全中文假设
 * 更准确，减少对中英混排段落的过高估算和提前分页。
 */
function estimateTextHeight(text: string, fontSize: number, width: number): number {
  let totalCharWidth = 0
  for (const ch of text) {
    if (/\s/.test(ch)) {
      totalCharWidth += fontSize * 0.3
    } else if (/[一-鿿　-〿＀-￯⺀-⻿㐀-䶿]/.test(ch)) {
      totalCharWidth += fontSize * 0.95 // CJK 全角字符
    } else {
      totalCharWidth += fontSize * 0.55 // 拉丁/数字/标点半角
    }
  }
  const lines = Math.max(Math.ceil(totalCharWidth / width), 1)
  return lines * (fontSize * 1.35)
}

/**
 * 预处理：从 Markdown 中提取所有脚注定义 `[^n]: URL`，
 * 存入字典并从原文中删除。同时截断 LLM 自动附加的参考资料区域。
 */
function extractCitations(markdown: string): {
  cleanedMarkdown: string
  citationsDict: Record<string, string>
} {
  const citationsDict: Record<string, string> = {}

  // Step 1: 优先提取脚注定义 [^n]: text → 存入字典
  const regex = /(?:^|\n)\[\^(\d+)\]:\s*(.+)/g
  const fragments: Array<{ full: string; id: string; text: string }> = []
  let match: RegExpExecArray | null
  while ((match = regex.exec(markdown)) !== null) {
    fragments.push({ full: match[0], id: match[1], text: match[2].trim() })
  }

  for (const f of fragments) {
    citationsDict[f.id] = f.text
  }

  // Step 2: 清理脚注行 — 从原文中删除提取出来的独立脚注定义行
  let cleaned = markdown
  for (const f of fragments) {
    cleaned = cleaned.replace(f.full, '')
  }

  // Step 3: 幽灵页截断 — 截断 LLM 自作主张生成的尾部参考资料区域
  // 增强版：同时匹配带和不带 emoji 的变体
  cleaned = cleaned.replace(
    /(?:^|\n)#{1,6}\s*[\s📚📖]*[\s]*(参考资料|参考来源|参考文献|资料来源|References|Bibliography)[\s\S]*$/i,
    '',
  )
  // 截断末尾残留的 --- 分隔线
  cleaned = cleaned.replace(/\n---\n\s*$/, '')
  cleaned = cleaned.replace(/\n---\s*$/, '')

  return { cleanedMarkdown: cleaned.trim(), citationsDict }
}

function scanCitations(text: string): Set<string> {
  const active = new Set<string>()
  const regex = /\[\^(\d+)\]/g
  let match: RegExpExecArray | null
  while ((match = regex.exec(text)) !== null) {
    active.add(match[1])
  }
  return active
}

function buildCitationText(
  activeCitations: Set<string>,
  citationsDict: Record<string, string>,
): string {
  if (activeCitations.size === 0) return ''
  const lines: string[] = []
  const sorted = [...activeCitations].sort((a, b) => Number(a) - Number(b))
  for (const id of sorted) {
    const text = citationsDict[id]
    if (text) {
      lines.push(`[${id}] ${text}`)
    }
  }
  return lines.join('  ')
}

// ══════════════════════════════════════════════════════════════
// 旧版兼容：stripMarkdown
// ══════════════════════════════════════════════════════════════

export function stripMarkdown(md: string): string {
  return md
    .replace(/```[\s\S]*?```/g, '')
    .replace(/`([^`]*)`/g, '$1')
    .replace(/!\[.*?\]\(.*?\)/g, '')
    .replace(/\[([^\]]*?)\]\(.*?\)/g, '$1')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/\*{1,3}([^*]+)\*{1,3}/g, '$1')
    .replace(/^[\s]*[-*+]\s+/gm, '• ')
    .replace(/^[\s]*\d+\.\s+/gm, '')
    .replace(/^>\s?/gm, '')
    .replace(/^[-*_]{3,}\s*$/gm, '')
    .replace(/\n{3,}/g, '\n\n')
    .replace(/\[\^(\d+)\]/g, '[$1]')
    .trim()
}

// ══════════════════════════════════════════════════════════════
// 图片 URL 解析
// ══════════════════════════════════════════════════════════════

/** 将相对图片路径补全为可访问的完整 URL，并编码非 ASCII 字符 */
function resolveImageUrl(href: string): string {
  const trimmed = href.trim()
  let resolved: string

  if (trimmed.startsWith('http://') || trimmed.startsWith('https://')) {
    resolved = trimmed
  } else {
    // 去除可能的前导 ../
    let normalized = trimmed
    while (normalized.startsWith('../')) {
      normalized = normalized.slice(3)
    }
    if (normalized.startsWith('outputs/images/')) {
      resolved = `http://localhost:8000/${normalized}`
    } else if (!normalized.startsWith('/') && !normalized.startsWith('http')) {
      resolved = `http://localhost:8000/${normalized}`
    } else {
      resolved = normalized
    }
  }

  try {
    const decoded = decodeURI(resolved)
    return encodeURI(decoded)
  } catch {
    return encodeURI(resolved)
  }
}

// ══════════════════════════════════════════════════════════════
// v5 商业风格 slide 装饰构建
// ══════════════════════════════════════════════════════════════

interface SlideDecorParams {
  sectionTitle: string
  logoUrl?: string
  pageNumber?: number
  totalPages?: number
}

function buildSlideDecor(params: SlideDecorParams): CanvasElement[] {
  const { sectionTitle, logoUrl, pageNumber, totalPages } = params
  const elements: CanvasElement[] = []

  // 白色背景
  elements.push({
    id: genId(), type: 'rect', name: 'decor',
    x: 0, y: 0,
    width: CANVAS_WIDTH, height: CANVAS_HEIGHT,
    fill: BRAND.white,
  })

  // 左侧品牌色竖条（全高）
  elements.push({
    id: genId(), type: 'rect', name: 'decor',
    x: 0, y: 0,
    width: SIDEBAR_WIDTH, height: CANVAS_HEIGHT,
    fill: BRAND.primary,
  })

  // ── 页眉区域 ──

  // Logo（如果有）
  if (logoUrl) {
    elements.push({
      id: genId(), type: 'image', name: 'decor',
      src: resolveImageUrl(logoUrl),
      x: 24, y: 8,
      width: 40, height: 40,
    })
  }

  // 章节标题
  const titleX = logoUrl ? 80 : CONTENT_X
  elements.push({
    id: genId(), type: 'text', name: 'decor',
    x: titleX, y: 14,
    width: CANVAS_WIDTH - titleX - 160, height: 36,
    text: sectionTitle,
    fontSize: 20,
    fontWeight: 'bold',
    fill: BRAND.heading,
  })

  // 页码（右侧）
  if (pageNumber !== undefined) {
    const pageText = totalPages ? `${pageNumber} / ${totalPages}` : `${pageNumber}`
    elements.push({
      id: genId(), type: 'text', name: 'decor',
      x: CANVAS_WIDTH - 140, y: 18,
      width: 120, height: 24,
      text: pageText,
      fontSize: 12,
      fill: BRAND.muted,
      align: 'right',
    })
  }

  // 页眉分隔线（品牌色，全宽）
  elements.push({
    id: genId(), type: 'rect', name: 'decor',
    x: SIDEBAR_WIDTH, y: HEADER_HEIGHT,
    width: CANVAS_WIDTH - SIDEBAR_WIDTH, height: 2,
    fill: BRAND.primary,
  })

  // ── 页脚区域 ──
  const footerY = CANVAS_HEIGHT - FOOTER_HEIGHT

  // 页脚背景
  elements.push({
    id: genId(), type: 'rect', name: 'decor',
    x: SIDEBAR_WIDTH, y: footerY,
    width: CANVAS_WIDTH - SIDEBAR_WIDTH, height: FOOTER_HEIGHT,
    fill: BRAND.footerBg,
  })

  // 页脚左侧文字
  elements.push({
    id: genId(), type: 'text', name: 'decor',
    x: CONTENT_X, y: footerY + 4,
    width: 400, height: 16,
    text: 'CONFIDENTIAL · 产品深度研究',
    fontSize: 9,
    fill: BRAND.muted,
  })

  // 页脚右侧品牌色点
  elements.push({
    id: genId(), type: 'circle', name: 'decor',
    x: CANVAS_WIDTH - 80, y: footerY + 8,
    width: 8, height: 8,
    radius: 4,
    fill: BRAND.primary,
  })

  return elements
}

// ══════════════════════════════════════════════════════════════
// 封面页构建（v5 增强版）
// ══════════════════════════════════════════════════════════════

function buildCoverSlide(topic: string): CanvasElement[] {
  const elements: CanvasElement[] = []

  // 深色背景
  elements.push({
    id: genId(), type: 'rect', name: 'decor',
    x: 0, y: 0,
    width: CANVAS_WIDTH, height: CANVAS_HEIGHT,
    fill: BRAND.dark,
  })

  // 左侧品牌色竖条
  elements.push({
    id: genId(), type: 'rect', name: 'decor',
    x: 80, y: 200,
    width: 6, height: 280,
    fill: BRAND.primary,
  })

  // 标签行（带边框）
  elements.push({
    id: genId(), type: 'text', name: 'decor',
    x: 120, y: 160,
    width: 300, height: 28,
    text: 'PRODUCT DEEP RESEARCH',
    fontSize: 10,
    fontWeight: '600',
    fill: BRAND.primary,
  })

  // 主标题
  elements.push({
    id: genId(), type: 'text', name: 'decor',
    x: 120, y: 210,
    width: CANVAS_WIDTH - 240, height: 80,
    text: topic,
    fontSize: 38, fontWeight: 'bold',
    fill: BRAND.white,
  })

  // 品牌色分割线
  elements.push({
    id: genId(), type: 'rect', name: 'decor',
    x: 120, y: 320,
    width: 200, height: 4,
    fill: BRAND.primary,
  })

  // 副标题
  elements.push({
    id: genId(), type: 'text', name: 'decor',
    x: 120, y: 350,
    width: CANVAS_WIDTH - 240, height: 40,
    text: '产品深度研究路演方案',
    fontSize: 18,
    fill: '#bcc8e0',
  })

  // 日期
  elements.push({
    id: genId(), type: 'text', name: 'decor',
    x: 120, y: 420,
    width: CANVAS_WIDTH - 240, height: 30,
    text: new Date().toLocaleDateString('zh-CN', {
      year: 'numeric', month: 'long', day: 'numeric',
    }),
    fontSize: 14,
    fill: '#64748b',
  })

  // 底部出品信息
  elements.push({
    id: genId(), type: 'text', name: 'decor',
    x: 120, y: 630,
    width: CANVAS_WIDTH - 240, height: 60,
    text: '出品机构 · 产品前沿战略研究院\n核心引擎 · AI 多模态视觉管道\n数据溯源 · 混合 RAG 权威检索链路',
    fontSize: 11,
    fill: '#64748b',
  })

  return elements
}

// ══════════════════════════════════════════════════════════════
// 目录页构建
// ══════════════════════════════════════════════════════════════

function buildTOCSlide(
  sections: Array<{ title: string }>,
  logoUrl?: string,
): CanvasElement[] {
  const elements: CanvasElement[] = []

  // 白色背景
  elements.push({
    id: genId(), type: 'rect', name: 'decor',
    x: 0, y: 0,
    width: CANVAS_WIDTH, height: CANVAS_HEIGHT,
    fill: BRAND.white,
  })

  // 左侧品牌色竖条
  elements.push({
    id: genId(), type: 'rect', name: 'decor',
    x: 0, y: 0,
    width: SIDEBAR_WIDTH, height: CANVAS_HEIGHT,
    fill: BRAND.primary,
  })

  // Logo
  if (logoUrl) {
    elements.push({
      id: genId(), type: 'image', name: 'decor',
      src: resolveImageUrl(logoUrl),
      x: 24, y: 8,
      width: 40, height: 40,
    })
  }

  // "目录" 标题
  const titleX = logoUrl ? 80 : CONTENT_X
  elements.push({
    id: genId(), type: 'text', name: 'decor',
    x: titleX, y: 14,
    width: 200, height: 36,
    text: '目录',
    fontSize: 20, fontWeight: 'bold',
    fill: BRAND.heading,
  })

  // 页眉分隔线
  elements.push({
    id: genId(), type: 'rect', name: 'decor',
    x: SIDEBAR_WIDTH, y: HEADER_HEIGHT,
    width: CANVAS_WIDTH - SIDEBAR_WIDTH, height: 2,
    fill: BRAND.primary,
  })

  // 章节列表（双栏布局）
  const colWidth = 540
  const colGap = 40
  const leftColX = CONTENT_X
  const rightColX = CONTENT_X + colWidth + colGap
  const startY = 80
  const lineHeight = 36
  const maxPerCol = Math.floor((CONTENT_END_Y - startY) / lineHeight)

  sections.forEach((section, i) => {
    const col = Math.floor(i / maxPerCol)
    const row = i % maxPerCol
    const x = col === 0 ? leftColX : rightColX
    const y = startY + row * lineHeight

    if (y > CONTENT_END_Y - 20) return // 防溢出

    // 章节序号（品牌色圆点 + 数字）
    elements.push({
      id: genId(), type: 'circle', name: 'decor',
      x: x, y: y + 8,
      width: 8, height: 8,
      radius: 4,
      fill: BRAND.primary,
    })

    elements.push({
      id: genId(), type: 'text',
      x: x + 16, y: y,
      width: colWidth - 20, height: lineHeight,
      text: section.title,
      fontSize: 15,
      fill: BRAND.body,
    })
  })

  // 页脚
  const footerY = CANVAS_HEIGHT - FOOTER_HEIGHT
  elements.push({
    id: genId(), type: 'rect', name: 'decor',
    x: SIDEBAR_WIDTH, y: footerY,
    width: CANVAS_WIDTH - SIDEBAR_WIDTH, height: FOOTER_HEIGHT,
    fill: BRAND.footerBg,
  })
  elements.push({
    id: genId(), type: 'text', name: 'decor',
    x: CONTENT_X, y: footerY + 4,
    width: 400, height: 16,
    text: 'CONFIDENTIAL · 产品深度研究',
    fontSize: 9,
    fill: BRAND.muted,
  })

  return elements
}

// ══════════════════════════════════════════════════════════════
// 内部状态
// ══════════════════════════════════════════════════════════════

interface SlideBuildState {
  elements: CanvasElement[]
  currentY: number
  activeCitations: Set<string>
}

// ══════════════════════════════════════════════════════════════
// AST Token → CanvasElement 精确映射（v5 商业风格版）
// ══════════════════════════════════════════════════════════════

/**
 * 检查段落 token 中是否包含内嵌图片，如有则提取渲染。
 */
function tryRenderParagraphImages(
  token: marked.Tokens.Paragraph,
  state: SlideBuildState,
): boolean {
  const inlineTokens = (token as any).tokens as marked.Token[] | undefined
  if (!inlineTokens || inlineTokens.length === 0) return false

  let hasImage = false
  for (const t of inlineTokens) {
    if (t.type === 'image') {
      const imgToken = t as marked.Tokens.Image
      const href = imgToken.href
      const resolvedUrl = resolveImageUrl(href)

      state.elements.push({
        id: genId(),
        type: 'image',
        x: CONTENT_X,
        y: state.currentY,
        width: IMAGE_RENDER_WIDTH,
        height: IMAGE_RENDER_HEIGHT,
        src: resolvedUrl,
      })
      state.currentY += IMAGE_RENDER_HEIGHT + 20
      hasImage = true
    }
  }

  return hasImage
}

function processToken(
  token: marked.Token,
  state: SlideBuildState,
): void {
  switch (token.type) {
    // ── 标题 ──────────────────────────────────────────────
    case 'heading': {
      const t = token as marked.Tokens.Heading
      const text = t.text
      for (const c of scanCitations(text)) state.activeCitations.add(c)

      const h = estimateTextHeight(text, HEADING_FONT_SIZE, CONTENT_WIDTH)
      state.elements.push({
        id: genId(),
        type: 'text',
        x: CONTENT_X, y: state.currentY,
        width: CONTENT_WIDTH, height: h + 10,
        text,
        fontSize: HEADING_FONT_SIZE,
        fontWeight: 'bold',
        fill: BRAND.heading,
      })
      state.currentY += h + 16
      break
    }

    // ── 段落（含图片捕获） ──────────────────────────────
    case 'paragraph': {
      const t = token as marked.Tokens.Paragraph

      const hasImage = tryRenderParagraphImages(t, state)
      if (hasImage) {
        const text = t.text
        for (const c of scanCitations(text)) state.activeCitations.add(c)
        break
      }

      const text = t.text
      for (const c of scanCitations(text)) state.activeCitations.add(c)

      const plain = stripMarkdown(text)
      if (!plain.trim()) { state.currentY += 8; break }

      const h = estimateTextHeight(plain, BODY_FONT_SIZE, CONTENT_WIDTH)
      state.elements.push({
        id: genId(),
        type: 'text',
        x: CONTENT_X, y: state.currentY,
        width: CONTENT_WIDTH, height: h + 8,
        text: plain,
        fontSize: BODY_FONT_SIZE,
        fill: BRAND.body,
      })
      state.currentY += h + 12
      break
    }

    // ── 列表（品牌色圆点） ────────────────────────────────
    case 'list': {
      const t = token as marked.Tokens.List
      let itemIndex = 0
      for (const item of t.items) {
        const rawText = item.text || ''
        for (const c of scanCitations(rawText)) state.activeCitations.add(c)

        const plain = stripMarkdown(rawText)
        if (!plain.trim()) continue

        const h = estimateTextHeight(plain, BODY_FONT_SIZE, CONTENT_WIDTH - 20)

        if (t.ordered) {
          itemIndex++
          const displayText = `${itemIndex}. ${plain}`
          state.elements.push({
            id: genId(),
            type: 'text',
            x: LIST_X, y: state.currentY,
            width: CONTENT_WIDTH - 20, height: h + 4,
            text: displayText,
            fontSize: BODY_FONT_SIZE,
            fill: BRAND.body,
          })
        } else {
          const bulletY = state.currentY + h / 2 - 2
          state.elements.push({
            id: genId(),
            type: 'circle',
            x: LIST_X - 8, y: bulletY - 4,
            width: 8, height: 8,
            radius: 4,
            fill: BRAND.primary,
          } as CanvasElement)

          state.elements.push({
            id: genId(),
            type: 'text',
            x: LIST_X + 16, y: state.currentY,
            width: CONTENT_WIDTH - 36, height: h + 4,
            text: plain,
            fontSize: BODY_FONT_SIZE,
            fill: BRAND.body,
          })
        }

        state.currentY += h + 8
      }
      state.currentY += 4
      break
    }

    // ── 表格 ──────────────────────────────────────────────
    case 'table': {
      const t = token as marked.Tokens.Table
      const header = t.header.map((cell) => cell.text.replace(/^"|"$/g, '').trim())
      const rows = t.rows.map((row) => row.map((cell) => cell.text.replace(/^"|"$/g, '').trim()))
      const data = [header, ...rows]
      const rowH = 36
      const tableH = data.length * rowH
      const tableW = Math.min(CONTENT_WIDTH, header.length * 200)

      for (const row of data) {
        for (const cell of row) {
          for (const c of scanCitations(cell)) state.activeCitations.add(c)
        }
      }

      state.elements.push({
        id: genId(),
        type: 'table',
        x: CONTENT_X, y: state.currentY,
        width: tableW, height: tableH,
        tableData: data,
      } as CanvasElement)
      state.currentY += tableH + 16
      break
    }

    // ── 引用块 ──────────────────────────────────────────────
    case 'blockquote': {
      const t = token as marked.Tokens.Blockquote
      const text = t.text
      for (const c of scanCitations(text)) state.activeCitations.add(c)

      const plain = stripMarkdown(text)
      if (!plain.trim()) { state.currentY += 4; break }

      const h = estimateTextHeight(plain, BODY_FONT_SIZE, CONTENT_WIDTH - 20)
      const blockH = h + 16

      // 浅色背景
      state.elements.push({
        id: genId(), type: 'rect',
        x: CONTENT_X, y: state.currentY,
        width: CONTENT_WIDTH, height: blockH,
        fill: '#f8fafc',
      })

      // 左侧蓝色竖条
      state.elements.push({
        id: genId(), type: 'rect',
        x: CONTENT_X, y: state.currentY,
        width: BLOCKQUOTE_BAR_WIDTH, height: blockH,
        fill: BRAND.primary,
      })

      // 文字
      state.elements.push({
        id: genId(), type: 'text',
        x: CONTENT_X + BLOCKQUOTE_BAR_WIDTH + 12, y: state.currentY + 8,
        width: CONTENT_WIDTH - BLOCKQUOTE_BAR_WIDTH - 20, height: h + 8,
        text: plain,
        fontSize: BODY_FONT_SIZE,
        fontStyle: 'italic',
        fill: '#64748b',
      })
      state.currentY += blockH + 12
      break
    }

    // ── 空白 ──────────────────────────────────────────────
    case 'space':
      state.currentY += 6  // 略微减少空白行间距
      break

    // ── 代码块 ────────────────────────────────────────────
    case 'code': {
      const t = token as marked.Tokens.Code
      const lines = t.text.split('\n').length
      state.currentY += lines * 18 + 12
      break
    }

    default:
      state.currentY += 4
      break
  }
}

// ══════════════════════════════════════════════════════════════
// 高度预估（用于分页判断）
// ══════════════════════════════════════════════════════════════

function estimateTokenHeight(token: marked.Token): number {
  switch (token.type) {
    case 'heading': {
      const t = token as marked.Tokens.Heading
      return estimateTextHeight(t.text, HEADING_FONT_SIZE, CONTENT_WIDTH) + 16
    }
    case 'paragraph': {
      const t = token as marked.Tokens.Paragraph
      const inlineTokens = (t as any).tokens as marked.Token[] | undefined
      if (inlineTokens) {
        let imgH = 0
        for (const it of inlineTokens) {
          if (it.type === 'image') {
            imgH += IMAGE_RENDER_HEIGHT + 20
          }
        }
        if (imgH > 0) return imgH
      }
      return estimateTextHeight(stripMarkdown(t.text), BODY_FONT_SIZE, CONTENT_WIDTH) + 12
    }
    case 'list': {
      const t = token as marked.Tokens.List
      let total = 0
      for (const item of t.items) {
        const raw = item.text || ''
        total += estimateTextHeight(stripMarkdown(raw), BODY_FONT_SIZE, CONTENT_WIDTH - 20) + 8
      }
      return total + 4
    }
    case 'table': {
      const t = token as marked.Tokens.Table
      return (t.rows.length + 1) * 36 + 16
    }
    case 'blockquote': {
      const t = token as marked.Tokens.Blockquote
      return estimateTextHeight(stripMarkdown(t.text), BODY_FONT_SIZE, CONTENT_WIDTH - 20) + 16 + 12
    }
    case 'code': {
      const t = token as marked.Tokens.Code
      return t.text.split('\n').length * 18 + 12
    }
    case 'space':
      return 6
    default:
      return 4
  }
}

function hasSubstance(token: marked.Token): boolean {
  return token.type !== 'space' && token.type !== 'hr'
}

// ══════════════════════════════════════════════════════════════
// 引用页尾渲染（v5：分隔线 + 溢出检测）
// ══════════════════════════════════════════════════════════════

function appendCitationFooter(
  elements: CanvasElement[],
  activeCitations: Set<string>,
  citationsDict: Record<string, string>,
  currentY: number,
): number {
  if (activeCitations.size === 0) return currentY

  const citationText = buildCitationText(activeCitations, citationsDict)
  if (!citationText) return currentY

  // 估算引用区高度
  const citationLines = citationText.length / 80 + 1  // 粗略按 80 字符换行
  const citationHeight = Math.min(Math.ceil(citationLines) * 16 + 8, 60)

  // 分隔线 Y = 内容下方留 8px，但不低于 CITATION_ZONE_Y
  const separatorY = Math.min(currentY + 8, CITATION_ZONE_Y)

  // 检测溢出：如果引用区会与页脚重叠，则不渲染（推到下一页）
  if (separatorY + citationHeight > CANVAS_HEIGHT - FOOTER_HEIGHT - 4) {
    return currentY // 返回未渲染引用的 Y，由分页逻辑处理
  }

  // 分隔线
  elements.push({
    id: genId(), type: 'rect', name: 'decor',
    x: CONTENT_X, y: separatorY,
    width: 200, height: 1,
    fill: BRAND.divider,
  })

  // 引用文本
  elements.push({
    id: genId(), type: 'text',
    x: CONTENT_X, y: separatorY + 6,
    width: CONTENT_WIDTH, height: citationHeight,
    text: citationText,
    fontSize: CITATION_FONT_SIZE,
    fill: BRAND.muted,
  })

  return separatorY + citationHeight
}

// ══════════════════════════════════════════════════════════════
// 正文分页引擎（v5：商业风格 + 章节级渲染）
// ══════════════════════════════════════════════════════════════

function buildContentSlides(
  sectionTitle: string,
  content: string,
  citationsDict: Record<string, string>,
  logoUrl?: string,
  startPageNumber?: number,
  totalPages?: number,
): CanvasElement[][] {
  const slidesElements: CanvasElement[][] = []

  // 1. AST 解析
  const rawTokens = marked.lexer(content)
  if (rawTokens.length === 0) {
    // 空内容 → 仍输出一张装饰页
    slidesElements.push([
      ...buildSlideDecor({
        sectionTitle,
        logoUrl,
        pageNumber: startPageNumber,
        totalPages,
      }),
    ])
    return slidesElements
  }

  // Token 预处理：过滤无用节点
  let firstHeadingRemoved = false
  const tokens = rawTokens.filter((token) => {
    if (token.type === 'space') return false
    // 剔除第一个 heading（静态装饰器中已渲染了章节标题）
    if (!firstHeadingRemoved && token.type === 'heading') {
      firstHeadingRemoved = true
      return false
    }
    return true
  })

  if (tokens.length === 0) {
    slidesElements.push([
      ...buildSlideDecor({
        sectionTitle,
        logoUrl,
        pageNumber: startPageNumber,
        totalPages,
      }),
    ])
    return slidesElements
  }

  // 2. 初始化第一页
  let currentPageNum = startPageNumber || 1
  let state: SlideBuildState = {
    elements: [
      ...buildSlideDecor({
        sectionTitle,
        logoUrl,
        pageNumber: currentPageNum,
        totalPages,
      }),
    ],
    currentY: CONTENT_START_Y,
    activeCitations: new Set<string>(),
  }

  let continuationIndex = 0

  // 3. 索引循环 + 前瞻判页
  for (let i = 0; i < tokens.length; i++) {
    const token = tokens[i]
    let totalH = estimateTokenHeight(token)

    // 孤儿标题前瞻
    if (token.type === 'heading' && i + 1 < tokens.length) {
      const nextH = estimateTokenHeight(tokens[i + 1])
      totalH += nextH
    }

    // 翻页条件
    if (hasSubstance(token) && state.currentY > CONTENT_START_Y && state.currentY + totalH > CONTENT_END_Y) {
      // 当前页收尾：渲染引用页尾
      appendCitationFooter(
        state.elements,
        state.activeCitations,
        citationsDict,
        state.currentY,
      )
      slidesElements.push(state.elements)

      // 新页
      continuationIndex++
      currentPageNum++

      state = {
        elements: [
          ...buildSlideDecor({
            sectionTitle,
            logoUrl,
            pageNumber: currentPageNum,
            totalPages,
          }),
        ],
        currentY: CONTENT_START_Y,
        activeCitations: new Set<string>(),
      }
    }

    processToken(token, state)
  }

  // 最后一页收尾
  appendCitationFooter(
    state.elements,
    state.activeCitations,
    citationsDict,
    state.currentY,
  )
  slidesElements.push(state.elements)

  return slidesElements
}

// ══════════════════════════════════════════════════════════════
// 全局引用编号 reconcile
// ══════════════════════════════════════════════════════════════

/**
 * 将多个 block 的 per-section citationsDict 合并为全局引用字典。
 * 相同 URL 的引用会映射到同一个全局 ID，避免不同章节的 [^1]
 * 指向不同 URL 造成混淆。
 */
function reconcileCitationsGlobal(
  blockCitationDicts: Array<Record<string, string>>,
): {
  globalDicts: Array<Record<string, string>>  // 每个 block 重新映射后的字典
  globalDict: Record<string, string>          // 全局完整字典
} {
  const urlToGlobalId: Record<string, string> = {}
  const globalDict: Record<string, string> = {}
  let nextGlobalId = 1

  const globalDicts: Array<Record<string, string>> = []

  for (const localDict of blockCitationDicts) {
    const remapped: Record<string, string> = {}

    for (const [localId, urlOrText] of Object.entries(localDict)) {
      // 提取纯 URL（去除可能的 "来源链接: <url>" 包装）
      let cleanUrl = urlOrText
      const urlMatch = urlOrText.match(/<(https?:\/\/[^>]+)>/)
      if (urlMatch) {
        cleanUrl = urlMatch[1]
      } else if (urlOrText.startsWith('来源链接: ')) {
        cleanUrl = urlOrText.replace('来源链接: ', '').trim()
      }

      // 检查是否已注册
      const existingGlobalId = urlToGlobalId[cleanUrl]
      if (existingGlobalId) {
        remapped[localId] = cleanUrl
        // 映射 localId → existingGlobalId（渲染时替换）
      } else {
        const gid = String(nextGlobalId)
        urlToGlobalId[cleanUrl] = gid
        globalDict[gid] = cleanUrl
        remapped[localId] = cleanUrl
        nextGlobalId++
      }
    }

    globalDicts.push(remapped)
  }

  return { globalDicts, globalDict }
}

// ══════════════════════════════════════════════════════════════
// 公开 API
// ══════════════════════════════════════════════════════════════

/**
 * 将后端 DocumentBlock 数组转换为 Konva 幻灯片数组（v5 商业风格版）。
 *
 * 两遍扫描策略：
 * 1. 第一遍：生成所有 slide 元素，确定总页数
 * 2. 第二遍：将正确的页码信息注入每个 slide 的装饰元素中
 */
export function convertBlocksToKonvaSlides(
  topic: string,
  blocks: Pick<DocumentBlockResponse, 'section_title' | 'content' | 'order_index'>[],
  logoUrl?: string,
): KonvaSlide[] {
  _elementIdCounter = 0

  const sorted = [...blocks].sort((a, b) => a.order_index - b.order_index)

  // ── Step 1: 提取所有 block 的引用字典，进行全局 reconcile ──
  const blockCitationDicts: Array<Record<string, string>> = []
  const blockCleanedMarkdowns: string[] = []

  for (const block of sorted) {
    const rawContent = block.content || ''
    const { cleanedMarkdown, citationsDict } = extractCitations(rawContent)
    blockCitationDicts.push(citationsDict)
    blockCleanedMarkdowns.push(cleanedMarkdown)
  }

  const { globalDict } = reconcileCitationsGlobal(blockCitationDicts)

  // ── Step 2: 第一遍 — 生成所有 slide 元素（页码暂为占位） ──
  interface SlideInfo {
    sectionTitle: string
    elements: CanvasElement[]
  }
  const allSlideInfos: SlideInfo[] = []

  // 封面
  allSlideInfos.push({
    sectionTitle: '封面',
    elements: buildCoverSlide(topic),
  })

  // 目录
  const sectionList = sorted.map((block) => ({
    title: block.section_title || '章节',
  }))
  allSlideInfos.push({
    sectionTitle: '目录',
    elements: buildTOCSlide(sectionList, logoUrl),
  })

  // 正文
  for (let bIdx = 0; bIdx < sorted.length; bIdx++) {
    const block = sorted[bIdx]
    const title = block.section_title || '章节'
    const cleanedMarkdown = blockCleanedMarkdowns[bIdx]

    const pageElements = buildContentSlides(
      title,
      cleanedMarkdown,
      globalDict,
      logoUrl,
    )

    for (const elements of pageElements) {
      allSlideInfos.push({ sectionTitle: title, elements })
    }
  }

  // ── Step 3: 注入正确的页码 ──
  const totalPages = allSlideInfos.length
  for (let i = 0; i < allSlideInfos.length; i++) {
    const slideInfo = allSlideInfos[i]
    // 找到页码 text 元素并更新
    for (const el of slideInfo.elements) {
      if (el.name === 'decor' && el.type === 'text' && el.fontSize === 12 &&
          el.x === CANVAS_WIDTH - 140 && el.y === 18) {
        el.text = `${i} / ${totalPages - 1}`
        break
      }
    }
    // 封面和目录页不显示页码（封面无页码元素，目录页也无）
    if (i <= 1) {
      // 移除目录页可能带有的页码（如果 buildTOCSlide 没有添加则无需处理）
    }
  }

  // ── Step 4: 组装最终结果 ──
  const slides: KonvaSlide[] = allSlideInfos.map((info, i) => ({
    pageNumber: i,
    sectionTitle: info.sectionTitle,
    elements: info.elements,
  }))

  return slides
}

/**
 * 创建一个空白的新幻灯片。
 */
export function createBlankSlide(pageNumber: number): KonvaSlide {
  return {
    pageNumber,
    sectionTitle: `空白页 ${pageNumber}`,
    elements: [
      {
        id: `blank_bg_${pageNumber}`,
        type: 'rect',
        x: 0, y: 0,
        width: CANVAS_WIDTH, height: CANVAS_HEIGHT,
        fill: BRAND.white,
        name: 'decor',
      },
    ],
  }
}
