import { formatDateTime, formatJson } from '../../shared/api/formatters'
import type { DevelopmentPlan } from '../../shared/types/api'

interface DevelopmentPlanPanelProps {
  developmentPlans: DevelopmentPlan[]
}

/**
 * Development Plan 展示面板。
 *
 * 只展示 Planner Agent 持久化到 `development_plans` 的真实结构化记录；
 * M4 不把这些步骤当作已经执行的代码或工具动作。
 */
export function DevelopmentPlanPanel({ developmentPlans }: DevelopmentPlanPanelProps) {
  return (
    <section className="sub-panel" aria-labelledby="development-plan-title">
      <h3 id="development-plan-title">开发计划与任务图</h3>
      {developmentPlans.length === 0 ? <p className="empty-state">暂无真实 DevelopmentPlan。</p> : null}
      {developmentPlans.map((plan) => (
        <article className="review-card" key={plan.id}>
          <div className="card-toolbar">
            <div>
              <strong>v{plan.version}</strong>
              <span className={`review-status status-${plan.status}`}>{plan.status}</span>
            </div>
            <small>{formatDateTime(plan.updated_at)}</small>
          </div>
          <p>{plan.summary}</p>
          <dl className="meta-grid">
            <div>
              <dt>Plan ID</dt>
              <dd>{plan.id}</dd>
            </div>
            <div>
              <dt>Technical Design</dt>
              <dd>{plan.technical_design_id}</dd>
            </div>
          </dl>
          <h4>Steps JSON</h4>
          <pre>{formatJson(plan.steps_json)}</pre>
          <h4>Risks JSON</h4>
          <pre>{formatJson(plan.risks_json)}</pre>
        </article>
      ))}
    </section>
  )
}
