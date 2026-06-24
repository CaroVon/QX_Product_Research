/**
 * ============================================================
 * dataTransform —— 数据转换层 (Phase 3 v3)
 *
 * v3 升级：
 * - 中文精准高度估算（行宽系数 0.85，行高倍率 1.3）
 * - 幽灵页清理（截断 LLM 自动附加的「参考资料」尾部）
 * - Logo 弹性安全区（动态 safeX，无 Logo 时缩小边距）
 * - 引用框视觉升级（背景色块 + 左侧蓝色竖条）
 * - 列表子弹点视觉升级（圆形色块替代 • 文本前缀）
 * - 段落图片捕获（检测内嵌 image token，自动渲染）
 * - 前瞻式分页算法（孤儿标题保护，标题+后续内容联合判页）
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

/** 正文起始 Y（标题 + 分隔线下方） */
const START_Y = 110

/** 正文最大 Y（预留 60px 给页尾引用）；v3 改为 660 减少碎页 */
const MAX_Y = 660

/** 正文内容宽度（CANVAS_WIDTH - 左右边距） */
const CONTENT_WIDTH = 1040

/** 正文常规字号 */
const BODY_FONT_SIZE = 18

/** 标题字号 */
const HEADING_FONT_SIZE = 24

/** 引用块左侧竖条宽度 */
const BLOCKQUOTE_BAR_WIDTH = 4

/** 页尾引用字号 */
const CITATION_FONT_SIZE = 12

/** 页尾引用 Y 坐标 */
const CITATION_Y = 650

/** 图片默认渲染宽度 */
const IMAGE_RENDER_WIDTH = 800

/** 图片默认渲染高度（16:9 等比） */
const IMAGE_RENDER_HEIGHT = 450

// ══════════════════════════════════════════════════════════════
// 动态布局计算（基于 logoUrl 弹性安全区）
// ══════════════════════════════════════════════════════════════

interface LayoutParams {
  safeX: number
  contentX: number
  listX: number
}

function computeLayout(logoUrl?: string): LayoutParams {
  const safeX = logoUrl ? 220 : 60
  return {
    safeX,
    contentX: safeX + 20,
    listX: safeX + 40,
  }
}

// ══════════════════════════════════════════════════════════════
// 工具函数
// ══════════════════════════════════════════════════════════════

let _elementIdCounter = 0

function genId(): string {
  _elementIdCounter += 1
  return `el_${Date.now()}_${_elementIdCounter}_${Math.random().toString(36).substring(2, 6)}`
}

/**
 * 估算文本在 Canvas 中占据的高度（v3 中文精准版）。
 *
 * 公式：
 *   行数 ≈ ceil(字符数 × (fontSize × 0.85) / 内容宽度)
 *   高度 ≈ 行数 × (fontSize × 1.3)
 *
 * 中文字符宽约 fontSize × 0.85 px（实测修正），
 * 行高倍率 1.3 适配中文排版呼吸感。
 */
function estimateTextHeight(text: string, fontSize: number, width: number): number {
  const charCount = text.replace(/\s/g, '').length || 1
  const lines = Math.ceil((charCount * (fontSize * 0.85)) / width)
  return Math.max(lines, 1) * (fontSize * 1.3)
}

/**
 * 预处理：从 Markdown 中提取所有脚注定义 `[^n]: URL`，
 * 存入字典并从原文中删除。同时截断 LLM 自动附加的「参考资料」区域。
 */
function extractCitations(markdown: string): {
  cleanedMarkdown: string
  citationsDict: Record<string, string>
} {
  // v3 新增：截断 LLM 自动附加的参考资料尾部（幽灵页修复）
  markdown = markdown.replace(/(?:^|\n)#{1,6}\s*(参考资料|参考来源|参考文献|资料来源|References)[\s\S]*$/i, '')

  const citationsDict: Record<string, string> = {}
  const regex = /(?:^|\n)\[\^(\d+)\]:\s*(.+)/g

  const fragments: Array<{ full: string; id: string; text: string }> = []
  let match: RegExpExecArray | null
  while ((match = regex.exec(markdown)) !== null) {
    fragments.push({ full: match[0], id: match[1], text: match[2].trim() })
  }

  for (const f of fragments) {
    citationsDict[f.id] = f.text
  }

  let cleaned = markdown
  for (const f of fragments) {
    cleaned = cleaned.replace(f.full, '')
  }

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
  return lines.join('\n')
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

  // 编码 URL 中的非 ASCII 字符（如中文文件名），
  // 但保留已编码的 %xx 和协议/路径分隔符
  try {
    // 先解码再编码，避免双重编码
    const decoded = decodeURI(resolved)
    return encodeURI(decoded)
  } catch {
    return encodeURI(resolved)
  }
}

// ══════════════════════════════════════════════════════════════
// 静态装饰元素构建（v3：动态 safeX + Logo 支持）
// ══════════════════════════════════════════════════════════════

function buildSlideDecor(sectionTitle: string, layout: LayoutParams, logoUrl?: string): CanvasElement[] {
  const { safeX, contentX } = layout
  const elements: CanvasElement[] = []

  // 白色背景
  elements.push({
    id: genId(),
    type: 'rect',
    x: 0, y: 0,
    width: CANVAS_WIDTH, height: CANVAS_HEIGHT,
    fill: '#ffffff',
  })

  // 顶部品牌色装饰条（从 safeX 开始）
  elements.push({
    id: genId(),
    type: 'rect',
    x: safeX, y: 0,
    width: CANVAS_WIDTH - safeX, height: 5,
    fill: '#6366f1',
  })

  // 章节标题
  elements.push({
    id: genId(),
    type: 'text',
    x: contentX, y: 40,
    width: CANVAS_WIDTH - contentX - 80, height: 50,
    text: sectionTitle,
    fontSize: HEADING_FONT_SIZE,
    fontWeight: 'bold',
    fill: '#0f172a',
  })

  // 标题下方分隔线
  elements.push({
    id: genId(),
    type: 'rect',
    x: contentX, y: 95,
    width: 120, height: 3,
    fill: '#6366f1',
  })

  // Logo 图片（如果有，放在左上角安全区内）
  if (logoUrl) {
    elements.push({
      id: genId(),
      type: 'image',
      src: resolveImageUrl(logoUrl),
      x: 40, y: 15,
      width: 160, height: 60,
    })
  }

  return elements
}

// ══════════════════════════════════════════════════════════════
// 封面页构建
// ══════════════════════════════════════════════════════════════

function buildCoverSlide(topic: string): CanvasElement[] {
  return [
    {
      id: genId(), type: 'rect',
      x: 0, y: 0,
      width: CANVAS_WIDTH, height: CANVAS_HEIGHT,
      fill: '#0f1117',
    },
    {
      id: genId(), type: 'rect',
      x: 80, y: 220,
      width: 6, height: 280,
      fill: '#6366f1',
    },
    {
      id: genId(), type: 'text',
      x: 120, y: 200,
      width: CANVAS_WIDTH - 240, height: 80,
      text: topic,
      fontSize: 36, fontWeight: 'bold',
      fill: '#ffffff',
    },
    {
      id: genId(), type: 'text',
      x: 120, y: 340,
      width: CANVAS_WIDTH - 240, height: 40,
      text: '产品深度分析报告',
      fontSize: 20,
      fill: '#94a3b8',
    },
    {
      id: genId(), type: 'rect',
      x: 120, y: 460,
      width: 200, height: 2,
      fill: '#6366f1',
    },
    {
      id: genId(), type: 'text',
      x: 120, y: 500,
      width: CANVAS_WIDTH - 240, height: 30,
      text: new Date().toLocaleDateString('zh-CN', {
        year: 'numeric', month: 'long', day: 'numeric',
      }),
      fontSize: 16,
      fill: '#64748b',
    },
  ]
}

// ══════════════════════════════════════════════════════════════
// 内部状态
// ══════════════════════════════════════════════════════════════

interface SlideBuildState {
  elements: CanvasElement[]
  currentY: number
  activeCitations: Set<string>
  layout: LayoutParams
}

// ══════════════════════════════════════════════════════════════
// AST Token → CanvasElement 精确映射（v3 视觉升级版）
// ══════════════════════════════════════════════════════════════

/**
 * 检查段落 token 中是否包含内嵌图片，如有则提取渲染。
 * 返回 true 表示渲染了图片（已在内部累加 currentY），false 表示无图片。
 */
function tryRenderParagraphImages(
  token: marked.Tokens.Paragraph,
  state: SlideBuildState,
): boolean {
  // 检查内嵌 tokens 中是否有 image
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
        x: state.layout.contentX,
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
  const { contentX, listX } = state.layout

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
        x: contentX, y: state.currentY,
        width: CONTENT_WIDTH, height: h + 10,
        text,
        fontSize: HEADING_FONT_SIZE,
        fontWeight: 'bold',
        fill: '#0f172a',
      })
      state.currentY += h + 16
      break
    }

    // ── 段落（含图片捕获） ──────────────────────────────
    case 'paragraph': {
      const t = token as marked.Tokens.Paragraph

      // v3 新增：优先检查内嵌图片
      const hasImage = tryRenderParagraphImages(t, state)
      if (hasImage) {
        // 有图片 → 已渲染图片元素，但还需要处理文本部分的引用扫描
        const text = t.text
        for (const c of scanCitations(text)) state.activeCitations.add(c)
        break
      }

      // 无图片 → 正常文本渲染
      const text = t.text
      for (const c of scanCitations(text)) state.activeCitations.add(c)

      const plain = stripMarkdown(text)
      if (!plain.trim()) { state.currentY += 8; break }

      const h = estimateTextHeight(plain, BODY_FONT_SIZE, CONTENT_WIDTH)
      state.elements.push({
        id: genId(),
        type: 'text',
        x: contentX, y: state.currentY,
        width: CONTENT_WIDTH, height: h + 8,
        text: plain,
        fontSize: BODY_FONT_SIZE,
        fill: '#334155',
      })
      state.currentY += h + 12
      break
    }

    // ── 列表（v3 视觉升级：圆形子弹点替代 • 文本） ────
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
          // 有序列表：数字前缀文本
          itemIndex++
          const displayText = `${itemIndex}. ${plain}`
          state.elements.push({
            id: genId(),
            type: 'text',
            x: listX, y: state.currentY,
            width: CONTENT_WIDTH - 20, height: h + 4,
            text: displayText,
            fontSize: BODY_FONT_SIZE,
            fill: '#334155',
          })
        } else {
          // 无序列表：圆形子弹点 + 文本
          const bulletY = state.currentY + h / 2 - 2
          state.elements.push({
            id: genId(),
            type: 'circle',
            x: listX - 8, y: bulletY - 4,
            width: 8, height: 8,
            radius: 4,
            fill: '#6366f1',
          } as CanvasElement)

          state.elements.push({
            id: genId(),
            type: 'text',
            x: listX + 16, y: state.currentY,
            width: CONTENT_WIDTH - 36, height: h + 4,
            text: plain,
            fontSize: BODY_FONT_SIZE,
            fill: '#334155',
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
      // v3 防御性剥离：强制剥除 LLM 可能带上的双引号
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
        x: contentX, y: state.currentY,
        width: tableW, height: tableH,
        tableData: data,
      } as CanvasElement)
      state.currentY += tableH + 16
      break
    }

    // ── 引用块（v3 视觉升级：背景色块 + 左侧蓝色竖条） ──
    case 'blockquote': {
      const t = token as marked.Tokens.Blockquote
      const text = t.text
      for (const c of scanCitations(text)) state.activeCitations.add(c)

      const plain = stripMarkdown(text)
      if (!plain.trim()) { state.currentY += 4; break }

      const h = estimateTextHeight(plain, BODY_FONT_SIZE, CONTENT_WIDTH - 20)
      const blockH = h + 16

      // 背景色块
      state.elements.push({
        id: genId(),
        type: 'rect',
        x: contentX, y: state.currentY,
        width: CONTENT_WIDTH, height: blockH,
        fill: '#f8fafc',
      })

      // 左侧蓝色竖条
      state.elements.push({
        id: genId(),
        type: 'rect',
        x: contentX, y: state.currentY,
        width: BLOCKQUOTE_BAR_WIDTH, height: blockH,
        fill: '#3b82f6',
      })

      // 文字（右移 16px）
      state.elements.push({
        id: genId(),
        type: 'text',
        x: contentX + BLOCKQUOTE_BAR_WIDTH + 12, y: state.currentY + 8,
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
      state.currentY += 8
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
      // v3：检查是否有内嵌图片
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
      return 8
    default:
      return 4
  }
}

function hasSubstance(token: marked.Token): boolean {
  return token.type !== 'space' && token.type !== 'hr'
}

// ══════════════════════════════════════════════════════════════
// 页尾引用渲染
// ══════════════════════════════════════════════════════════════

function appendCitationFooter(
  elements: CanvasElement[],
  activeCitations: Set<string>,
  citationsDict: Record<string, string>,
  contentX: number,
): void {
  if (activeCitations.size === 0) return

  const citationText = buildCitationText(activeCitations, citationsDict)
  if (!citationText) return

  elements.push({
    id: genId(),
    type: 'text',
    x: contentX, y: CITATION_Y,
    width: CONTENT_WIDTH, height: 55,
    text: citationText,
    fontSize: CITATION_FONT_SIZE,
    fill: '#94a3b8',
  })
}

// ══════════════════════════════════════════════════════════════
// 正文分页引擎（v3：前瞻式分页，防孤儿标题）
// ══════════════════════════════════════════════════════════════

/**
 * 将一个章节的 Markdown 内容解析为多张幻灯片元素数组。
 *
 * v3 前瞻式分页算法：
 * - 使用索引循环遍历 tokens
 * - 若当前 token 为 heading 且有后续 token，
 *   则 totalH = 标题高度 + 后续内容高度（确保标题不孤悬）
 * - 若 currentY + totalH > MAX_Y 则先行翻页
 */
function buildContentSlides(
  sectionTitle: string,
  content: string,
  citationsDict: Record<string, string>,
  logoUrl?: string,
): CanvasElement[][] {
  const slidesElements: CanvasElement[][] = []
  const layout = computeLayout(logoUrl)

  // 1. AST 解析
  const tokens = marked.lexer(content)
  if (tokens.length === 0) {
    // 空内容 → 仍输出一张装饰页
    slidesElements.push([...buildSlideDecor(sectionTitle, layout, logoUrl)])
    return slidesElements
  }

  // 2. 初始化第一页
  let state: SlideBuildState = {
    elements: [...buildSlideDecor(sectionTitle, layout, logoUrl)],
    currentY: START_Y,
    activeCitations: new Set<string>(),
    layout,
  }

  let continuationIndex = 0

  // 3. v3：索引循环 + 前瞻判页
  for (let i = 0; i < tokens.length; i++) {
    const token = tokens[i]
    let totalH = estimateTokenHeight(token)

    // 孤儿标题前瞻：若当前为 heading 且有下一个 token，
    // 将下一个 token 的高度也计入需求，确保标题与内容同页
    if (token.type === 'heading' && i + 1 < tokens.length) {
      const nextH = estimateTokenHeight(tokens[i + 1])
      totalH += nextH
    }

    // 翻页条件（v3 修复：禁止在空页面上强制翻页，必须 currentY > START_Y）
    if (hasSubstance(token) && state.currentY > START_Y && state.currentY + totalH > MAX_Y) {
      // 当前页收尾
      appendCitationFooter(
        state.elements,
        state.activeCitations,
        citationsDict,
        layout.contentX,
      )
      slidesElements.push(state.elements)

      // 新页
      continuationIndex++
      const contTitle =
        continuationIndex === 1
          ? sectionTitle
          : `${sectionTitle}(续${continuationIndex})`

      state = {
        elements: [...buildSlideDecor(contTitle, layout, logoUrl)],
        currentY: START_Y,
        activeCitations: new Set<string>(),
        layout,
      }
    }

    processToken(token, state)
  }

  // 最后一页收尾
  appendCitationFooter(
    state.elements,
    state.activeCitations,
    citationsDict,
    layout.contentX,
  )
  slidesElements.push(state.elements)

  return slidesElements
}

// ══════════════════════════════════════════════════════════════
// 公开 API
// ══════════════════════════════════════════════════════════════

/**
 * 将后端 DocumentBlock 数组转换为 Konva 幻灯片数组（v3 AST 分页版）。
 *
 * @param topic   项目主题（用作封面标题）
 * @param blocks  后端文档块列表
 * @param logoUrl 可选 Logo 图片 URL（用于左上角渲染 + 弹性安全区）
 * @returns       幻灯片数组
 */
export function convertBlocksToKonvaSlides(
  topic: string,
  blocks: Pick<DocumentBlockResponse, 'section_title' | 'content' | 'order_index'>[],
  logoUrl?: string,
): KonvaSlide[] {
  const slides: KonvaSlide[] = []
  _elementIdCounter = 0

  // ── Slide 0：封面 ────────────────────────────────────
  slides.push({
    pageNumber: 0,
    sectionTitle: '封面',
    elements: buildCoverSlide(topic),
  })

  // ── Slides 1..N：AST 分页正文 ─────────────────────────
  const sorted = [...blocks].sort((a, b) => a.order_index - b.order_index)

  let pageNum = 1
  for (const block of sorted) {
    const title = block.section_title || `章节`
    const rawContent = block.content || ''

    const { cleanedMarkdown, citationsDict } = extractCitations(rawContent)
    const pageElements = buildContentSlides(title, cleanedMarkdown, citationsDict, logoUrl)

    for (const elements of pageElements) {
      slides.push({
        pageNumber: pageNum,
        sectionTitle: title,
        elements,
      })
      pageNum++
    }
  }

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
        fill: '#ffffff',
      },
    ],
  }
}
