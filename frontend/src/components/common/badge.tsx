import { cn } from '@/lib/utils'
import type { ProjectStatusEnum, TaskStatusEnum } from '@/types/api'

interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: 'default' | 'secondary' | 'outline' | 'success' | 'warning' | 'destructive'
  children?: React.ReactNode
}

export function Badge({ className, variant = 'default', ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium transition-colors',
        {
          'bg-primary text-primary-foreground': variant === 'default',
          'bg-secondary text-secondary-foreground': variant === 'secondary',
          'border border-input text-foreground': variant === 'outline',
          'bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300': variant === 'success',
          'bg-amber-50 text-amber-700 dark:bg-amber-950 dark:text-amber-300': variant === 'warning',
          'bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-300': variant === 'destructive',
        },
        className,
      )}
      {...props}
    />
  )
}

/** 项目状态对应的 Badge 变体 */
const projectBadgeVariant: Record<ProjectStatusEnum, BadgeProps['variant']> = {
  preparing_data: 'default',
  waiting_outline_approval: 'warning',
  drafting: 'default',
  completed: 'success',
  failed: 'destructive',
}

const projectBadgeLabel: Record<ProjectStatusEnum, string> = {
  preparing_data: '资料准备中',
  waiting_outline_approval: '待确认大纲',
  drafting: '撰写中',
  completed: '已完成',
  failed: '失败',
}

export function ProjectStatusBadge({ status }: { status: ProjectStatusEnum }) {
  return (
    <Badge variant={projectBadgeVariant[status]}>
      {projectBadgeLabel[status]}
    </Badge>
  )
}

/** 任务状态对应的 Badge 变体 */
const taskBadgeVariant: Record<TaskStatusEnum, BadgeProps['variant']> = {
  pending: 'secondary',
  processing: 'default',
  completed: 'success',
  failed: 'destructive',
  retrying: 'warning',
  cancelled: 'outline',
}

const taskBadgeLabel: Record<TaskStatusEnum, string> = {
  pending: '等待中',
  processing: '执行中',
  completed: '已完成',
  failed: '失败',
  retrying: '重试中',
  cancelled: '已取消',
}

export function TaskStatusBadge({ status }: { status: TaskStatusEnum }) {
  return (
    <Badge variant={taskBadgeVariant[status]}>
      {taskBadgeLabel[status]}
    </Badge>
  )
}
