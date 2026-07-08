import { HealthPanel } from './features/health/HealthPanel'

/**
 * 控制台应用根组件。
 *
 * M1 只组合真实平台 API 健康检查，避免提前展示尚未实现的
 * Task、Agent、部署或监控假数据。
 */
export function App() {
  return (
    <main className="app-shell">
      <section className="hero">
        <p className="eyebrow">CloudHelm M1</p>
        <h1>云舵控制台工程骨架</h1>
        <p className="hero-copy">
          当前阶段验证 React/TypeScript 控制台与 FastAPI 平台 API 的最小连接，
          后续将在 M2 以后接入任务、事件和审批主流程。
        </p>
      </section>
      <HealthPanel />
    </main>
  )
}
