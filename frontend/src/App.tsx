import { Suspense, lazy } from 'react'
import { Routes, Route } from 'react-router-dom'
import { LoadingFallback } from '@/components/motion/PageTransition'

// V2-W1 R3：旧 SPA 收缩为「演示重型编辑器 + 导出打印」专用子应用。
// 主界面（工作台/研究/PRD/设计/资产库/记忆图谱等）已由 QX Studio（deer-flow 前端）承载。
const PresentationEditorPage = lazy(() =>
  import('@/pages/PresentationEditorPage').then((m) => ({ default: m.PresentationEditorPage })))
const ExportPage = lazy(() =>
  import('@/pages/ExportPage').then((m) => ({ default: m.ExportPage })))

/** 根路径提示页：引导回主界面（同主机 2026 端口）。 */
function MainAppRedirect() {
  const mainUrl = window.location.origin.replace(/:8000$/, ':2026')
  return (
    <div style={{ display: 'grid', placeItems: 'center', height: '100vh', fontFamily: 'system-ui' }}>
      <div style={{ textAlign: 'center' }}>
        <p style={{ fontSize: 18, fontWeight: 600 }}>QX Studio 演示编辑器子应用</p>
        <p style={{ opacity: 0.7, margin: '8px 0 16px' }}>本站仅承载演示页重型编辑与导出打印</p>
        <a href={mainUrl} style={{ color: '#3B82F6' }}>前往 QX Studio 主界面 →</a>
      </div>
    </div>
  )
}

export function App() {
  return (
    <Routes>
      <Route path="/" element={<MainAppRedirect />} />
      <Route
        path="/presentation/editor/:productId"
        element={
          <Suspense fallback={<LoadingFallback message="加载演示编辑器" />}>
            <PresentationEditorPage />
          </Suspense>
        }
      />
      <Route
        path="/export/:productId"
        element={
          <Suspense fallback={<LoadingFallback message="准备导出" />}>
            <ExportPage />
          </Suspense>
        }
      />
      <Route path="*" element={<MainAppRedirect />} />
    </Routes>
  )
}
