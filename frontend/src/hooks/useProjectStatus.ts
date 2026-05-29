/**
 * ============================================================
 * useProjectStatus —— 状态机感知的轮询 Hook
 *
 * 核心职责：
 * 1. 使用 React Query 以可变速率的频率轮询 /status
 * 2. 根据返回的 project_status 决定渲染逻辑：
 *    - preparing_data → 节点1 执行中，继续轮询
 *    - waiting_outline_approval → 暂停轮询，抛出 needApproval 信号
 *    - drafting → 节点2 执行中，继续轮询 + 拉取 blocks
 *    - completed / failed → 停止轮询
 * 3. 对外暴露 isWaitingApproval, isDrafting 等语义化标志
 * ============================================================
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { projectsApi } from '@/lib/api'
import type { OutlineApproveResponse, OutlineApproveRequest } from '@/types/api'
import type { ProjectStatusEnum } from '@/types/api'

const PROJECTS_KEY = ['projects'] as const

interface UseProjectStatusOptions {
  /** 项目 ID */
  projectId: string | undefined
  /** 是否启用轮询 */
  enabled?: boolean
}

/**
 * 状态机感知的项目状态轮询
 *
 * 轮询策略：
 * - preparing_data / drafting → 每 3 秒轮询
 * - waiting_outline_approval → 停止轮询（等待用户操作）
 * - completed / failed → 停止轮询（终态）
 */
export function useProjectStatus({ projectId, enabled = true }: UseProjectStatusOptions) {
  return useQuery({
    queryKey: [...PROJECTS_KEY, projectId, 'status'],
    queryFn: () => projectsApi.getStatus(projectId!),
    enabled: !!projectId && enabled,
    refetchInterval: (query) => {
      const data = query.state.data
      if (!data) return 3000
      const status = data.project_status as ProjectStatusEnum
      // 需要用户交互 → 暂停轮询
      if (status === 'waiting_outline_approval') return false
      // 终态 → 停止轮询
      if (status === 'completed' || status === 'failed') return false
      // 活跃态 → 每 3 秒轮询
      return 3000
    },
    refetchIntervalInBackground: true,
    staleTime: 0,
    // 当 status 发生变化时触发回调
    structuralSharing: true,
  })
}

// ─── 语义化状态标志计算 ──────────────────────────────────────

/** 提取语义化状态标志 */
export function getStatusFlags(status: ProjectStatusEnum | undefined) {
  return {
    /** 节点1 资料准备中 */
    isPreparing: status === 'preparing_data',
    /** 🎯 等待用户确认大纲（交互核心节点） */
    isWaitingApproval: status === 'waiting_outline_approval',
    /** 节点2 AI 撰写中 */
    isDrafting: status === 'drafting',
    /** 已完成 */
    isCompleted: status === 'completed',
    /** 已失败 */
    isFailed: status === 'failed',
    /** 是否处于活跃状态（非终态） */
    isActive: status !== 'completed' && status !== 'failed',
  }
}

// ─── 文档块查询 ──────────────────────────────────────────────

/**
 * 获取项目的所有 DocumentBlock
 * 仅在 drafting / completed 状态下才启用
 */
export function useProjectBlocks(projectId: string | undefined, enabled = false) {
  return useQuery({
    queryKey: [...PROJECTS_KEY, projectId, 'blocks'],
    queryFn: () => projectsApi.getBlocks(projectId!),
    enabled: !!projectId && enabled,
    // drafting 阶段每 5 秒轮询新块（SSE 降级方案）
    refetchInterval: (query) => {
      const data = query.state.data
      if (!data) return 5000
      return 5000
    },
    refetchIntervalInBackground: true,
    staleTime: 0,
  })
}

// ─── 大纲确认 Mutation ──────────────────────────────────────

/**
 * 提交大纲确认
 *
 * 调用后：
 * 1. 后端将 ProjectStatus 从 waiting_outline_approval → drafting
 * 2. 触发 Celery 节点2：run_draft_sections_workflow
 * 3. 前端重新获取最新状态，进入 drafting 模式
 */
export function useApproveOutline() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({
      projectId,
      data,
    }: {
      projectId: string
      data: OutlineApproveRequest
    }) => projectsApi.approveOutline(projectId, data),
    onSuccess: (response: OutlineApproveResponse, variables) => {
      // 刷新状态到 drafting
      queryClient.invalidateQueries({
        queryKey: [...PROJECTS_KEY, variables.projectId, 'status'],
      })
      // 触发 blocks 查询
      queryClient.invalidateQueries({
        queryKey: [...PROJECTS_KEY, variables.projectId, 'blocks'],
      })
    },
  })
}
