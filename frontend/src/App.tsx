import { Routes, Route, Navigate } from 'react-router-dom'
import { Layout } from '@/components/layout/Layout'
import { DashboardPage } from '@/pages/DashboardPage'
import { WorkspacePage } from '@/pages/WorkspacePage'
import { ProgressPage } from '@/pages/ProgressPage'
import { ReportPage } from '@/pages/ReportPage'

/**
 * 应用根路由
 *
 * 路由架构：
 * /                    → 控制台（项目列表 + 新建入口）
 * /projects/:id/workspace → 🌟 交互式工作台（核心页面）
 * /projects/:id/progress → 生成进度页（轮询，兼容旧链接）
 * /projects/:id/report  → 报告阅读器（含溯源，兼容旧链接）
 */
export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/projects/:projectId/workspace" element={<WorkspacePage />} />
        <Route path="/projects/:projectId/progress" element={<ProgressPage />} />
        <Route path="/projects/:projectId/report" element={<ReportPage />} />
        {/* 兜底重定向 */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
