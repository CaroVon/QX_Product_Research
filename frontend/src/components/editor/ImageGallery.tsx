/**
 * ============================================================
 * ImageGallery —— 图片搜索与预览库面板
 *
 * 位于 Canvas 编辑器下方，提供：
 * - 图片搜索（DuckDuckGo），带搜索强度控制
 * - 缩略图预览网格（支持拖拽到画布）
 * - 持久化存储（按项目隔离，刷新后保留）
 * ============================================================
 */

import { useState, useEffect, useCallback, useRef } from 'react'
import {
  Search,
  ChevronDown,
  ChevronUp,
  X,
  Image as ImageIcon,
  Loader2,
  Trash2,
} from 'lucide-react'
import { Button } from '@/components/common/button'
import { cn } from '@/lib/utils'
import { projectsApi } from '@/lib/api'
import type { ImageResult } from '@/types/api'

// ══════════════════════════════════════════════════════════════
// 搜索强度选项
// ══════════════════════════════════════════════════════════════

const SEARCH_DEPTH_OPTIONS = [
  { value: 5, label: '快速', desc: '~2 张' },
  { value: 10, label: '标准', desc: '~4 张' },
  { value: 15, label: '深度', desc: '~6 张' },
  { value: 20, label: '极致', desc: '~8 张' },
] as const

// ══════════════════════════════════════════════════════════════
// Props
// ══════════════════════════════════════════════════════════════

interface ImageGalleryProps {
  projectId: string
  className?: string
}

// ══════════════════════════════════════════════════════════════
// 组件
// ══════════════════════════════════════════════════════════════

export function ImageGallery({ projectId, className }: ImageGalleryProps) {
  const [collapsed, setCollapsed] = useState(() => {
    // 持久化折叠状态
    try {
      return localStorage.getItem('imageGalleryCollapsed') === 'true'
    } catch {
      return false
    }
  })
  const [query, setQuery] = useState('')
  const [searchDepth, setSearchDepth] = useState(10)
  const [images, setImages] = useState<ImageResult[]>([])
  const [searching, setSearching] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const searchInputRef = useRef<HTMLInputElement>(null)

  // ── 加载已有图片库 ──────────────────────────────────────────
  const loadImages = useCallback(async () => {
    if (!projectId) return
    try {
      setLoading(true)
      setError(null)
      const data = await projectsApi.getProjectImages(projectId)
      setImages(data.images || [])
    } catch (err: any) {
      setError(err?.message || '加载图片库失败')
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => {
    loadImages()
  }, [loadImages])

  // ── 执行搜索 ────────────────────────────────────────────────
  const handleSearch = useCallback(async () => {
    const trimmed = query.trim()
    if (!trimmed || !projectId) return

    try {
      setSearching(true)
      setError(null)
      const data = await projectsApi.searchImages(projectId, {
        query: trimmed,
        search_depth: searchDepth,
      })
      // 将新结果前置（后端已按 created_at desc 排序，但合并时新结果在前）
      setImages((prev) => {
        const existingIds = new Set(prev.map((img) => img.id))
        const newOnes = data.images.filter((img) => !existingIds.has(img.id))
        return [...newOnes, ...prev]
      })
    } catch (err: any) {
      setError(err?.message || '图片搜索失败')
    } finally {
      setSearching(false)
    }
  }, [query, searchDepth, projectId])

  // ── 删除图片 ────────────────────────────────────────────────
  const handleDelete = useCallback(
    async (imageId: string) => {
      try {
        await projectsApi.deleteProjectImage(projectId, imageId)
        setImages((prev) => prev.filter((img) => img.id !== imageId))
      } catch (err: any) {
        setError(err?.message || '删除失败')
      }
    },
    [projectId],
  )

  // ── Enter 键搜索 ────────────────────────────────────────────
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      handleSearch()
    }
  }

  // ── 拖拽开始 ────────────────────────────────────────────────
  const handleDragStart = (e: React.DragEvent, img: ImageResult) => {
    e.dataTransfer.setData(
      'application/json',
      JSON.stringify({
        imageUrl: img.image_url,
        title: img.title,
        query: img.query,
      }),
    )
    e.dataTransfer.effectAllowed = 'copy'
  }

  // ── 切换折叠 ────────────────────────────────────────────────
  const toggleCollapsed = () => {
    setCollapsed((prev) => {
      const next = !prev
      try {
        localStorage.setItem('imageGalleryCollapsed', String(next))
      } catch { /* ignore */ }
      return next
    })
  }

  return (
    <div className={cn('border-t border-border bg-card', className)}>
      {/* ── 标题栏 ─────────────────────────────────────────── */}
      <button
        type="button"
        onClick={toggleCollapsed}
        className="flex w-full items-center gap-2 px-4 py-2 text-sm font-medium text-muted-foreground hover:bg-muted/50 transition-colors"
      >
        <ImageIcon className="h-4 w-4" />
        <span>图片素材库</span>
        {images.length > 0 && (
          <span className="text-xs rounded-full bg-primary/10 text-primary px-1.5 py-0.5">
            {images.length}
          </span>
        )}
        <span className="ml-auto">
          {collapsed ? (
            <ChevronUp className="h-4 w-4" />
          ) : (
            <ChevronDown className="h-4 w-4" />
          )}
        </span>
      </button>

      {!collapsed && (
        <div className="px-4 pb-3 space-y-3">
          {/* ── 搜索栏 ─────────────────────────────────────── */}
          <div className="flex gap-2">
            <div className="relative flex-1">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <input
                ref={searchInputRef}
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="搜索图片素材…"
                className="w-full rounded-md border border-input bg-background pl-8 pr-3 py-1.5 text-sm
                           placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
              />
            </div>
            <Button
              size="sm"
              onClick={handleSearch}
              disabled={searching || !query.trim()}
            >
              {searching ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                '搜索'
              )}
            </Button>
          </div>

          {/* ── 搜索强度选择器 ─────────────────────────────── */}
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-muted-foreground whitespace-nowrap">
              强度:
            </span>
            <div className="flex gap-1">
              {SEARCH_DEPTH_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setSearchDepth(opt.value)}
                  className={cn(
                    'px-2 py-0.5 rounded text-xs transition-colors',
                    searchDepth === opt.value
                      ? 'bg-primary text-primary-foreground'
                      : 'bg-muted text-muted-foreground hover:bg-muted/70',
                  )}
                  title={opt.desc}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          {/* ── 错误提示 ───────────────────────────────────── */}
          {error && (
            <div className="text-xs text-destructive flex items-center gap-1">
              <span>{error}</span>
              <button
                type="button"
                onClick={() => setError(null)}
                className="ml-auto hover:underline"
              >
                关闭
              </button>
            </div>
          )}

          {/* ── 图片网格 ───────────────────────────────────── */}
          {loading ? (
            <div className="flex items-center justify-center py-6 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin mr-2" />
              加载中…
            </div>
          ) : images.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-6 text-sm text-muted-foreground gap-1">
              <ImageIcon className="h-8 w-8 opacity-30" />
              <span>暂无图片素材</span>
              <span className="text-xs">
                搜索关键词以添加图片到素材库
              </span>
            </div>
          ) : (
            <div className="flex gap-2 overflow-x-auto pb-1 scrollbar-thin">
              {images.map((img) => (
                <div
                  key={img.id}
                  className="group relative flex-shrink-0 cursor-grab active:cursor-grabbing"
                  draggable
                  onDragStart={(e) => handleDragStart(e, img)}
                  title={img.title || img.query}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={img.image_url}
                    alt={img.title || img.query}
                    className="h-[68px] w-[120px] object-cover rounded border border-border
                               group-hover:ring-1 group-hover:ring-primary/50 transition-shadow"
                    loading="lazy"
                    onError={(e) => {
                      // 图片加载失败显示占位符
                      ;(e.target as HTMLImageElement).style.display = 'none'
                      const placeholder = (e.target as HTMLImageElement)
                        .nextElementSibling
                      if (placeholder) {
                        ;(placeholder as HTMLElement).style.display = 'flex'
                      }
                    }}
                  />
                  {/* 加载失败占位符 */}
                  <div
                    className="hidden h-[68px] w-[120px] items-center justify-center
                                rounded border border-border bg-muted"
                  >
                    <ImageIcon className="h-5 w-5 text-muted-foreground opacity-50" />
                  </div>
                  {/* 删除按钮 */}
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation()
                      handleDelete(img.id)
                    }}
                    className="absolute -top-1.5 -right-1.5 h-5 w-5 rounded-full bg-destructive
                               text-destructive-foreground opacity-0 group-hover:opacity-100
                               transition-opacity flex items-center justify-center shadow-sm"
                    title="删除"
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                  {/* 搜索关键词标签 */}
                  <div
                    className="absolute bottom-1 left-1 text-[10px] px-1 py-0.5 rounded
                                bg-black/50 text-white truncate max-w-[110px] opacity-0
                                group-hover:opacity-100 transition-opacity"
                  >
                    {img.query}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* ── 提示文字 ───────────────────────────────────── */}
          {images.length > 0 && (
            <p className="text-[11px] text-muted-foreground">
              拖拽图片到画布以添加到当前幻灯片
            </p>
          )}
        </div>
      )}
    </div>
  )
}

export default ImageGallery
