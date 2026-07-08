import { DesignReviewPanel } from '../design-review/DesignReviewPanel'
import { ApprovalPanel } from '../approvals/ApprovalPanel'
import { DevelopmentPlanPanel } from '../planning/DevelopmentPlanPanel'
import { ToolCallList } from '../tool-calls/ToolCallList'
import { formatDateTime } from '../../shared/api/formatters'
import { OrchestrationControls } from './OrchestrationControls'
import { TaskStatusBadge } from './TaskStatusBadge'
import { TaskTimeline } from './TaskTimeline'
import { useTaskDetail } from './useTaskDetail'

interface TaskDetailProps {
  taskId: string | null
  refreshKey: number
  onTaskChanged: () => void
}

/**
 * Task Detail 主面板。
 *
 * 聚合任务详情、Requirement、Technical Design、Timeline、ToolCall 和
 * Approval。所有数据均来自 Platform API；空状态表示数据库当前没有记录。
 */
export function TaskDetail({ taskId, refreshKey, onTaskChanged }: TaskDetailProps) {
  const detail = useTaskDetail(taskId, refreshKey)

  if (taskId === null) {
    return (
      <section className="panel detail-panel">
        <p className="eyebrow">Task Detail</p>
        <h2>请选择任务</h2>
        <p className="empty-state">选择任务后将读取真实 Requirement、Design、Timeline、ToolCall 和 Approval 数据。</p>
      </section>
    )
  }

  if (detail.status === 'loading' && detail.data === null) {
    return (
      <section className="panel detail-panel">
        <p className="status-line">正在加载任务详情...</p>
      </section>
    )
  }

  if (detail.status === 'error') {
    return (
      <section className="panel detail-panel">
        <div className="status-error" role="alert">
          <strong>任务详情加载失败</strong>
          <p>{detail.error}</p>
          <button type="button" onClick={detail.refresh}>
            重新加载
          </button>
        </div>
      </section>
    )
  }

  if (detail.data === null) {
    return null
  }

  const { task, requirements, designs, developmentPlans, agentRuns, toolCalls, approvals, timeline, orchestration } =
    detail.data

  return (
    <section className="panel detail-panel" aria-labelledby="task-detail-title">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Task Detail</p>
          <h2 id="task-detail-title">{task.title}</h2>
        </div>
        <button type="button" className="ghost-button" onClick={detail.refresh}>
          刷新详情
        </button>
      </div>

      <div className="detail-meta">
        <TaskStatusBadge status={task.status} riskLevel={task.risk_level} />
        <span>阶段：{task.current_phase}</span>
        <span>创建：{formatDateTime(task.created_at)}</span>
        <span>更新：{formatDateTime(task.updated_at)}</span>
      </div>
      <p className="detail-description">{task.description}</p>
      <dl className="meta-grid">
        <div>
          <dt>任务 ID</dt>
          <dd>{task.id}</dd>
        </div>
        <div>
          <dt>来源</dt>
          <dd>
            {task.source_type}
            {task.source_ref === null ? '' : ` / ${task.source_ref}`}
          </dd>
        </div>
        <div>
          <dt>创建者</dt>
          <dd>{task.created_by}</dd>
        </div>
      </dl>

      <OrchestrationControls
        task={task}
        orchestration={orchestration}
        onStart={detail.startOrchestration}
        onRunNext={detail.runNextOrchestration}
        onTaskChanged={onTaskChanged}
      />
      <DesignReviewPanel
        requirements={requirements}
        designs={designs}
        onDecideRequirement={detail.decideRequirement}
        onDecideDesign={detail.decideDesign}
      />
      <DevelopmentPlanPanel developmentPlans={developmentPlans} />
      <TaskTimeline agentRuns={agentRuns} events={timeline} streamStatus={detail.streamStatus} />
      <ToolCallList toolCalls={toolCalls} />
      <ApprovalPanel approvals={approvals} onDecideApproval={detail.decideApproval} />
    </section>
  )
}
