import { useParams, Link } from 'react-router-dom'
import { ArrowLeft, Loader2, AlertCircle, CheckCircle2, XCircle, ArrowRight } from 'lucide-react'
import { Button } from '@/components/common/button'
import { ProgressTracker } from '@/components/projects/ProgressTracker'
import { useProjectStatus } from '@/hooks/useProjects'
import { cn } from '@/lib/utils'

/**
 * 生成进度页面（任务 3）
 *
 * 核心体验优化：
 * - 使用 React Query 的 refetchInterval 每 3 秒轮询后端 /status
 * - 项目完成后自动展示"查看报告"入口
 * - 项目失败时展示错误详情
 */
export function ProgressPage() {
  const { projectId } = useParams<{ projectId: string }>()
  const { data, isLoading, isError, error } = useProjectStatus(projectId, true)

  // ─── 加载中 ──────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-32">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="h-10 w-10 animate-spin text-primary" />
          <p className="text-sm text-muted-foreground">加载项目信息...</p>
        </div>
      </div>
    )
  }

  // ─── 错误 ────────────────────────────────────────────────────
  if (isError || !data) {
    return (
      <div className="flex items-center justify-center py-32">
        <div className="flex flex-col items-center gap-4 text-destructive">
          <AlertCircle className="h-10 w-10" />
          <p className="font-medium">加载失败</p>
          <p className="text-sm text-muted-foreground">
            {(error as Error)?.message ?? '项目不存在或网络错误'}
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

  const isCompleted = data.project_status === 'completed'
  const isFailed = data.project_status === 'failed'
  const isProcessing = data.project_status === 'processing'

  return (
    <div className="mx-auto max-w-2xl space-y-8">
      {/* ─── 返回导航 ─────────────────────────────────────────── */}
      <Link
        to="/"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
      >
        <ArrowLeft className="h-4 w-4" />
        返回控制台
      </Link>

      {/* ─── 项目标题 ─────────────────────────────────────────── */}
      <div>
        <h1 className="text-xl font-bold leading-tight">{data.topic}</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          项目 ID: {data.project_id.slice(0, 8)}...
        </p>
      </div>

      {/* ─── 进度追踪器 ───────────────────────────────────────── */}
      <div className={cn(
        'rounded-xl border p-6 lg:p-8',
        isCompleted && 'border-emerald-200 bg-emerald-50/30',
        isFailed && 'border-red-200 bg-red-50/30',
        isProcessing && 'bg-card',
      )}>
        <ProgressTracker
          tasks={data.tasks}
          percentage={data.progress.percentage}
          projectStatus={data.project_status}
        />
      </div>

      {/* ─── 完成状态操作 ─────────────────────────────────────── */}
      {isCompleted && (
        <div className="flex flex-col items-center gap-4 rounded-xl border border-emerald-200 bg-emerald-50/50 p-6">
          <CheckCircle2 className="h-8 w-8 text-emerald-500" />
          <div className="text-center">
            <h3 className="font-semibold text-emerald-700">报告已生成完毕</h3>
            <p className="mt-1 text-sm text-emerald-600/70">
              您可以查看完整的行业研究报告。
            </p>
          </div>
          <Link to={`/projects/${data.project_id}/report`}>
            <Button className="gap-2">
              查看报告
              <ArrowRight className="h-4 w-4" />
            </Button>
          </Link>
        </div>
      )}

      {/* ─── 失败状态 ─────────────────────────────────────────── */}
      {isFailed && (
        <div className="rounded-xl border border-red-200 bg-red-50/50 p-6">
          <div className="flex items-start gap-3">
            <XCircle className="mt-0.5 h-5 w-5 shrink-0 text-destructive" />
            <div>
              <h3 className="font-semibold text-destructive">生成过程中出现错误</h3>
              <p className="mt-2 text-sm text-muted-foreground">
                失败任务数：{data.progress.failed_tasks} / {data.progress.total_tasks}
              </p>
              {data.tasks
                .filter((t) => t.status === 'failed' && t.error_message)
                .slice(0, 3)
                .map((failedTask) => (
                  <div key={failedTask.id} className="mt-2 rounded-md bg-red-100/50 p-3">
                    <p className="text-xs font-medium text-destructive">
                      步骤: {failedTask.task_type}
                    </p>
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      {failedTask.error_message}
                    </p>
                  </div>
                ))}
            </div>
          </div>
        </div>
      )}

      {/* ─── 任务详情（调试用） ───────────────────────────────── */}
      {isProcessing && data.tasks.length > 0 && (
        <details className="group rounded-lg border p-4">
          <summary className="cursor-pointer text-xs font-medium text-muted-foreground group-open:text-foreground">
            查看任务详情
          </summary>
          <div className="mt-3 space-y-2">
            {data.tasks.map((task) => (
              <div
                key={task.id}
                className="flex items-center justify-between rounded-md bg-secondary/50 px-3 py-2 text-xs"
              >
                <span className="font-medium">{task.task_type}</span>
                <span className={cn(
                  'px-1.5 py-0.5 rounded text-[10px] font-medium',
                  task.status === 'completed' && 'bg-emerald-100 text-emerald-700',
                  task.status === 'processing' && 'bg-blue-100 text-blue-700',
                  task.status === 'pending' && 'bg-gray-100 text-gray-500',
                  task.status === 'failed' && 'bg-red-100 text-red-700',
                )}>
                  {task.status}
                </span>
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  )
}
