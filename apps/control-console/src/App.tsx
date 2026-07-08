import { HealthPanel } from './features/health/HealthPanel'

/**
 * 控制台应用根组件。
 *
 * 当前控制台仍只组合真实平台 API 健康检查。M2 已完成后端数据底座，
 * 但任务主流程 UI 留到 M3，避免提前展示尚未实现的假数据。
 */
export function App() {
  return (
    <main className="app-shell">
      <section className="hero">
        <p className="eyebrow">CloudHelm M2</p>
        <h1>云舵控制台工程骨架与 API 底座</h1>
        <p className="hero-copy">
          当前阶段已完成后端真实数据库 API 与事件底座，控制台仍只验证
          React/TypeScript 与 FastAPI 的连接，任务、事件和审批主流程将在 M3 接入。
        </p>
      </section>
      <HealthPanel />
    </main>
  )
}
