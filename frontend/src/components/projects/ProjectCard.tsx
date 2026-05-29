import { Link } from 'react-router-dom'
import { FileText, Clock, ArrowRight } from 'lucide-react'
import { cn, formatDate } from '@/lib/utils'
import { ProjectStatusBadge } from '@/components/common/badge'
import type { ProjectResponse } from '@/types/api'

interface ProjectCardProps {
  project: ProjectResponse
}

/**
 * 项目卡片组件
 *
 * 在控制台/项目列表中展示单个项目的信息缩略
 */
export function ProjectCard({ project }: ProjectCardProps) {
  const isProcessing = project.status === 'processing'
  const isCompleted = project.status === 'completed'
  const isFailed = project.status === 'failed'

  return (
    <Link
      to={
        isCompleted
          ? `/projects/${project.id}/report`
          : isFailed
            ? `/projects/${project.id}/progress`
            : `/projects/${project.id}/progress`
      }
      className={cn(
        'group relative flex flex-col gap-3 rounded-xl border bg-card p-5 transition-all duration-200',
        'hover:shadow-md hover:border-primary/20',
        'active:scale-[0.98]',
      )}
    >
      {/* ─── 顶部行：主题 + 状态 ──────────────────────────────── */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-3 min-w-0">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-secondary">
            <FileText className="h-5 w-5 text-muted-foreground" />
          </div>
          <div className="min-w-0">
            <h3 className="truncate text-sm font-semibold leading-tight">
              {project.topic}
            </h3>
            <p className="mt-0.5 text-xs text-muted-foreground">
              <Clock className="mr-1 inline h-3 w-3" />
              {formatDate(project.created_at)}
            </p>
          </div>
        </div>
        <ProjectStatusBadge status={project.status} />
      </div>

      {/* ─── 进度指示 / 操作入口 ──────────────────────────────── */}
      <div className="mt-auto flex items-center justify-between">
        {isProcessing && (
          <span className="text-xs text-muted-foreground">
            正在生成中...
          </span>
        )}
        {isCompleted && (
          <span className="flex items-center gap-1 text-xs font-medium text-primary">
            查看报告
            <ArrowRight className="h-3 w-3 transition-transform group-hover:translate-x-0.5" />
          </span>
        )}
        {isFailed && (
          <span className="text-xs text-destructive">查看错误详情</span>
        )}
        {isProcessing && (
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary/40" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-primary" />
          </span>
        )}
      </div>
    </Link>
  )
}
