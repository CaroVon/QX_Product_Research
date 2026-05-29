import { useParams, Link } from 'react-router-dom'
import { ArrowLeft, Loader2, AlertCircle, Download, FileDown } from 'lucide-react'
import { Button } from '@/components/common/button'
import { CitationMarkdown } from '@/components/report/CitationMarkdown'
import { useProjectStatus, useProjectDownload } from '@/hooks/useProjects'
import type { CitationMap, DocumentResponse } from '@/types/api'
import { useEffect, useState } from 'react'

/**
 * 模拟获取报告内容（TODO：替换为真实的 /content API 调用）
 *
 * 当前后端尚未暴露独立的 /content 端点，
 * 这里展示如何消费 `documents` 数据并渲染。
 *
 * 实际生产环境中，应该调用：
 *   GET /api/v1/projects/{projectId}/content
 * 该接口返回 `DocumentResponse[]` 列表，
 * 每个 DocumentResponse 包含：
 *   - content: Markdown 正文
 *   - source_urls: JSON 字符串，格式 ["url1", "url2"]
 *
 * 前端需要将 source_urls 数组转换为 CitationMap 格式：
 *   { "1": "url1", "2": "url2" }
 */
async function fetchReportContent(projectId: string): Promise<{
  documents: DocumentResponse[]
}> {
  // ─── 真实实现应取消注释并调用后端 API ────────────────────────
  // const res = await fetch(`/api/v1/projects/${projectId}/content`)
  // if (!res.ok) throw new Error('获取报告内容失败')
  // return res.json()

  // 当前阶段：从 status 接口的 tasks 中获取章节数据（演示用）
  throw new Error('报告内容接口尚未接入，请在后端实现 GET /api/v1/projects/{id}/content 后启用')
}

/**
 * 将 source_urls JSON 数组转换为 CitationMap
 * { "1": "https://...", "2": "https://..." }
 */
function parseCitationMap(document: DocumentResponse): CitationMap {
  try {
    if (!document.source_urls) return {}
    const urls: string[] = JSON.parse(document.source_urls)
    const map: CitationMap = {}
    urls.forEach((url, index) => {
      map[String(index + 1)] = url
    })
    return map
  } catch {
    return {}
  }
}

/**
 * 交互式报告阅读器页面（任务 4）
 *
 * 核心功能：
 * - 使用 react-markdown 渲染带 [^n] 角标的 Markdown 正文
 * - 自定义渲染器实现 Citation Hover：悬停角标时弹出气泡卡片
 * - 显示参考来源 URL 或标题
 */
export function ReportPage() {
  const { projectId } = useParams<{ projectId: string }>()
  const { data: statusData } = useProjectStatus(projectId, false)
  const { data: downloadData } = useProjectDownload(projectId)
  const [documents, setDocuments] = useState<DocumentResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // ─── 获取报告内容 ────────────────────────────────────────────
  useEffect(() => {
    if (!projectId) return

    // TODO: 后端实现后，取消注释下面的代码
    // fetchReportContent(projectId)
    //   .then((data) => setDocuments(data.documents))
    //   .catch((err) => setError(err.message))
    //   .finally(() => setLoading(false))

    // 演示：使用定时器展示 loading 状态
    const timer = setTimeout(() => {
      setError('报告内容接口尚未接入。请在 backend 中实现 GET /api/v1/projects/{id}/content 端点。')
      setLoading(false)
    }, 1000)

    return () => clearTimeout(timer)
  }, [projectId])

  // ─── 加载中 ──────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="flex items-center justify-center py-32">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="h-10 w-10 animate-spin text-primary" />
          <p className="text-sm text-muted-foreground">加载报告内容...</p>
        </div>
      </div>
    )
  }

  // ─── 错误 ────────────────────────────────────────────────────
  if (error) {
    return (
      <div className="flex items-center justify-center py-32">
        <div className="flex flex-col items-center gap-4">
          <AlertCircle className="h-10 w-10 text-destructive" />
          <p className="font-medium text-destructive">无法加载报告</p>
          <p className="max-w-md text-center text-sm text-muted-foreground">
            {error}
          </p>
          <div className="flex gap-3 mt-2">
            <Link to={`/projects/${projectId}/progress`}>
              <Button variant="outline" size="sm">
                返回进度页
              </Button>
            </Link>
            <Link to="/">
              <Button variant="outline" size="sm">
                返回控制台
              </Button>
            </Link>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      {/* ─── 顶部导航 ─────────────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <Link
          to="/"
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
          返回控制台
        </Link>

        {/* 下载按钮 */}
        {downloadData?.download_url && (
          <a href={downloadData.download_url} target="_blank" rel="noopener noreferrer">
            <Button variant="outline" size="sm" className="gap-2">
              <Download className="h-4 w-4" />
              下载 PDF
            </Button>
          </a>
        )}
      </div>

      {/* ─── 报告标题 ─────────────────────────────────────────── */}
      <div className="border-b pb-4">
        <h1 className="text-2xl font-bold">
          {statusData?.topic ?? '行业研究报告'}
        </h1>
        <div className="mt-2 flex items-center gap-4 text-xs text-muted-foreground">
          <span className="inline-flex items-center gap-1">
            <FileDown className="h-3 w-3" />
            PDF 导出可用
          </span>
          {downloadData?.file_size_bytes && (
            <span>
              文件大小: {(downloadData.file_size_bytes / 1024 / 1024).toFixed(1)} MB
            </span>
          )}
        </div>
      </div>

      {/* ─── 章节列表（Tab 切换） ─────────────────────────────── */}
      {documents.length > 0 && (
        <div className="flex gap-2 overflow-x-auto pb-2">
          {documents.map((doc) => (
            <a
              key={doc.id}
              href={`#section-${doc.section_order}`}
              className="shrink-0 rounded-full border bg-secondary/50 px-3 py-1 text-xs font-medium text-muted-foreground hover:bg-secondary transition-colors"
            >
              {doc.section_title}
            </a>
          ))}
        </div>
      )}

      {/* ─── 报告正文（带溯源的 Markdown） ────────────────────── */}
      <div className="space-y-10">
        {documents.length === 0 && !loading && !error && (
          <div className="rounded-xl border border-dashed p-12 text-center">
            <p className="text-sm text-muted-foreground">
              暂无章节内容。请确认后端已完成报告生成。
            </p>
          </div>
        )}

        {documents.map((doc) => {
          const citationMap = parseCitationMap(doc)
          return (
            <section
              key={doc.id}
              id={`section-${doc.section_order}`}
              className="scroll-mt-20"
            >
              {/* ─── 章节标题 ────────────────────────────────── */}
              <h2 className="mb-4 text-lg font-semibold">
                {doc.section_title}
              </h2>

              {/* ─── 引用角标渲染 ────────────────────────────── */}
              <CitationMarkdown
                content={doc.content}
                citationMap={citationMap}
              />

              {/* ─── 章节引用列表 ────────────────────────────── */}
              {Object.keys(citationMap).length > 0 && (
                <div className="mt-6 rounded-lg border bg-muted/30 p-4">
                  <h4 className="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                    本章参考来源
                  </h4>
                  <ol className="space-y-1.5">
                    {Object.entries(citationMap).map(([num, url]) => (
                      <li key={num} className="text-xs">
                        <span className="font-medium text-muted-foreground">[{num}]</span>{' '}
                        <a
                          href={url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-blue-600 hover:text-blue-800 hover:underline break-all"
                        >
                          {url}
                        </a>
                      </li>
                    ))}
                  </ol>
                </div>
              )}

              {/* ─── 章节分隔 ──────────────────────────────────── */}
              <div className="mt-10 border-t" />
            </section>
          )
        })}
      </div>
    </div>
  )
}
