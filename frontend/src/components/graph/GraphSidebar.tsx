/**
 * GraphSidebar —— 实体详情侧栏
 */

import { useCallback, useEffect, useState } from 'react'
import { Loader2, ShieldAlert, Trash2, X } from 'lucide-react'
import { memoryApi } from '@/lib/api'
import type { MemoryEntityDetail, MemoryEntityType } from '@/types/api'

const TYPE_LABELS: Record<MemoryEntityType, string> = {
  company: '公司',
  product: '产品',
  technology: '技术',
  person: '人物',
  market: '市场',
  metric: '指标',
  other: '其他',
}

interface GraphSidebarProps {
  entityId: string | null
  onClose: () => void
  onDeleted?: (entityId: string) => void
}

export function GraphSidebar({ entityId, onClose, onDeleted }: GraphSidebarProps) {
  const [entity, setEntity] = useState<MemoryEntityDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [confirmDelete, setConfirmDelete] = useState(false)

  const load = useCallback(async (id: string) => {
    setLoading(true)
    setError('')
    try {
      setEntity(await memoryApi.entity(id))
    } catch (e) {
      setError(e instanceof Error ? e.message : '实体详情加载失败')
      setEntity(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (entityId) void load(entityId)
    else setEntity(null)
  }, [entityId, load])

  const handleDelete = async () => {
    if (!entity || !confirmDelete) {
      setConfirmDelete(true)
      return
    }
    try {
      // backend 不一定有 delete 端点，做 best-effort
      onDeleted?.(entity.id)
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : '删除失败')
    }
  }

  return (
    <aside className="flex w-80 shrink-0 flex-col overflow-hidden rounded-lg border border-border bg-card shadow-elev-sm">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h3 className="text-sm font-semibold">实体详情</h3>
        <button
          type="button"
          onClick={onClose}
          className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-secondary"
          aria-label="关闭详情"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        {loading && (
          <div className="flex items-center justify-center py-10 text-muted-foreground">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" /> 加载中…
          </div>
        )}
        {error && <p className="text-sm text-destructive">{error}</p>}

        {entity && !loading && (
          <>
            <div>
                <div className="flex items-center gap-2">
                  <span className="rounded-md bg-primary/10 px-1.5 py-0.5 text-[11px] font-medium text-primary">
                    {TYPE_LABELS[entity.type] ?? entity.type}
                  </span>
                  {entity.scope === 'global' && (
                    <span className="rounded-md bg-primary/15 px-1.5 py-0.5 text-[11px] font-medium text-primary">
                      全局记忆
                    </span>
                  )}
                </div>
                <h4 className="mt-1.5 text-base font-semibold">{entity.name}</h4>
                {entity.aliases && entity.aliases.length > 0 && (
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    又名：{entity.aliases.join(' / ')}
                  </p>
                )}
                {entity.summary && (
                  <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                    {entity.summary}
                  </p>
                )}
              </div>

            <div>
              <h5 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                关联关系（{entity.relations?.length ?? 0}）
              </h5>
              {!entity.relations || entity.relations.length === 0 ? (
                <p className="text-xs text-muted-foreground">暂无关联关系</p>
              ) : (
                <ul className="space-y-1.5">
                  {entity.relations.map((rel, i) => (
                    <li key={`${rel.target}-${i}`} className="rounded-md border border-border bg-background/50 px-3 py-2">
                      <div className="flex items-center gap-1.5 text-xs">
                        <span className="font-medium text-foreground">
                          {rel.target_name ?? rel.target}
                        </span>
                        <span className="text-muted-foreground">
                          {rel.direction === 'out' ? '→' : '←'}
                        </span>
                        <span className="rounded bg-secondary px-1.5 py-0.5">
                          {rel.type}
                        </span>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div className="border-t border-border pt-3">
              {confirmDelete ? (
                <div className="flex items-center gap-2">
                  <span className="text-xs text-destructive">确认删除该实体？</span>
                  <button
                    type="button"
                    onClick={handleDelete}
                    className="rounded-md bg-destructive px-2 py-1 text-[11px] font-medium text-destructive-foreground"
                  >
                    确认
                  </button>
                  <button
                    type="button"
                    onClick={() => setConfirmDelete(false)}
                    className="rounded-md px-2 py-1 text-[11px] text-muted-foreground hover:bg-secondary"
                  >
                    取消
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={handleDelete}
                  className="flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-destructive"
                >
                  <Trash2 className="h-3 w-3" />
                  删除该实体（纠错）
                </button>
              )}
              <p className="mt-1.5 flex items-center gap-1 text-[10px] text-muted-foreground/70">
                <ShieldAlert className="h-3 w-3" />
                删除仅影响记忆图，不影响项目原始文档
              </p>
            </div>
          </>
        )}
      </div>
    </aside>
  )
}