import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/common/dialog'
import { Button } from '@/components/common/button'
import { Input } from '@/components/common/input'
import { useCreateProject } from '@/hooks/useProjects'

interface CreateProjectModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

/**
 * "新建行研" 模态框
 *
 * 用户输入 Topic → 调用 POST /api/v1/projects → 跳转到进度页面
 */
export function CreateProjectModal({ open, onOpenChange }: CreateProjectModalProps) {
  const navigate = useNavigate()
  const [topic, setTopic] = useState('')
  const createProject = useCreateProject()

  const handleSubmit = async () => {
    if (!topic.trim()) return

    try {
      const result = await createProject.mutateAsync({ topic: topic.trim() })
      // ─── 创建成功后跳转到进度页面 ────────────────────────────
      onOpenChange(false)
      setTopic('')
      navigate(`/projects/${result.project.id}/progress`)
    } catch {
      // 错误由 React Query 的 onError 或 UI 层处理
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>新建行业研究</DialogTitle>
          <DialogDescription>
            输入您想要研究的行业或主题，AI 将自动生成深度研究报告。
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          <div className="space-y-2">
            <label htmlFor="topic" className="text-sm font-medium">
              研究主题
            </label>
            <Input
              id="topic"
              placeholder="例如：AI眼镜行业、新能源汽车市场分析..."
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !createProject.isPending) {
                  handleSubmit()
                }
              }}
              disabled={createProject.isPending}
              autoFocus
            />
          </div>
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={createProject.isPending}
          >
            取消
          </Button>
          <Button
            onClick={handleSubmit}
            loading={createProject.isPending}
            disabled={!topic.trim()}
          >
            提交研究
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
