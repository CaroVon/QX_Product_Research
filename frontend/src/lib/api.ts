/**
 * ============================================================
 * API 服务层
 * —— 基于 fetch 封装，对接后端 FastAPI
 *     新增 approve-outline、blocks 等端点
 * ============================================================
 */

import type {
  ProjectCreateRequest,
  ProjectCreateResponse,
  ProjectResponse,
  ProjectStatusResponse,
  SourcesListResponse,
  SourceReviewRequest,
  SourceReviewResponse,
  OutlineApproveRequest,
  OutlineApproveResponse,
  DocumentBlockListResponse,
  DownloadResponse,
  ReportContentResponse,
  EditorReviseRequest,
  EditorReviseResponse,
} from '@/types/api'

const API_BASE = '/api/v1'

class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(`API Error [${status}]: ${detail}`)
    this.name = 'ApiError'
  }
}

async function request<T>(
  url: string,
  options?: RequestInit,
): Promise<T> {
  const res = await fetch(`${API_BASE}${url}`, {
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
    ...options,
  })

  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const body = await res.json()
      detail = body.detail ?? detail
    } catch {
      // ignore JSON parse errors
    }
    throw new ApiError(res.status, detail)
  }

  return res.json() as Promise<T>
}

// ─── 项目 API ──────────────────────────────────────────────────

export const projectsApi = {
  /** 获取项目列表 */
  list(skip = 0, limit = 50): Promise<ProjectResponse[]> {
    return request(`/projects?skip=${skip}&limit=${limit}`)
  },

  /** 创建项目（提交分析主题，触发节点1：资料准备与大纲生成） */
  create(data: ProjectCreateRequest): Promise<ProjectCreateResponse> {
    return request('/projects', {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  /** 获取项目进度（轮询用） */
  getStatus(projectId: string): Promise<ProjectStatusResponse> {
    return request(`/projects/${projectId}/status`)
  },

  /**
   * 🎯 确认/修改大纲（交互核心节点）
   * 将状态机从 waiting_outline_approval 推进到 drafting，
   * 并触发节点2：分章节异步撰写
   */
  approveOutline(
    projectId: string,
    data: OutlineApproveRequest,
  ): Promise<OutlineApproveResponse> {
    return request(`/projects/${projectId}/approve-outline`, {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  /** 获取项目的所有文档块（供 Tiptap 编辑器加载） */
  getBlocks(projectId: string): Promise<DocumentBlockListResponse> {
    return request(`/projects/${projectId}/blocks`)
  },

  /** 获取下载链接 */
  getDownload(projectId: string): Promise<DownloadResponse> {
    return request(`/projects/${projectId}/download`)
  },

  /** 🆕 获取报告全文内容（按章节排列，含引用映射） */
  getContent(projectId: string): Promise<ReportContentResponse> {
    return request(`/projects/${projectId}/content`)
  },

  /**
   * 🖥️ 获取项目时间轴日志（支持增量拉取）
   * 前端右侧面板使用此 API 渲染实时终端控制台
   */
  getLogs(projectId: string, afterSequence = 0): Promise<import('@/types/api').ProjectLogListResponse> {
    return request(`/projects/${projectId}/logs?after_sequence=${afterSequence}`)
  },

  /**
   * 🎯 获取资料来源列表（交互节点1）
   * 返回搜索结果的标题、URL、摘要，供用户审核
   */
  getSources(projectId: string): Promise<SourcesListResponse> {
    return request(`/projects/${projectId}/sources`)
  },

  /**
   * 🎯 提交资料审核结果（交互节点1确认）
   * 将筛选后的 URL 列表提交给后端，触发阶段2：大纲生成
   */
  reviewSources(
    projectId: string,
    data: SourceReviewRequest,
  ): Promise<SourceReviewResponse> {
    return request(`/projects/${projectId}/review-sources`, {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  /** 删除项目及其所有关联数据 */
  delete(projectId: string): Promise<{ detail: string }> {
    return request(`/projects/${projectId}`, {
      method: 'DELETE',
    })
  },
}

/**
 * 🌊 SSE 草稿流连接
 *
 * 使用方式:
 * ```typescript
 * const es = projectsApi.connectDraftStream(projectId);
 * es.addEventListener('section_chunk', (e) => {
 *   const block = JSON.parse(e.data);
 *   // 插入 Tiptap 编辑器
 * });
 * es.addEventListener('draft_complete', () => {
 *   es.close();
 * });
 * ```
 */
export function connectDraftStream(projectId: string): EventSource {
  return new EventSource(`${API_BASE}/projects/${projectId}/stream-draft`)
}

// ─── 编辑器 AI API ──────────────────────────────────────────────

export const editorApi = {
  /**
   * 🎯 划词改写
   * 将选中文本发送给 AI，返回改写后的内容
   */
  async revise(data: EditorReviseRequest): Promise<EditorReviseResponse> {
    return request('/editor/revise', {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },
}
