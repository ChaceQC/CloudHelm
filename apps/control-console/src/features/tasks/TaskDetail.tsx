import { useCallback } from 'react'
import { DesignReviewPanel } from '../design-review/DesignReviewPanel'
import { ApprovalPanel } from '../approvals/ApprovalPanel'
import { LocalDevelopmentControls } from '../local-development/LocalDevelopmentControls'
import { LocalDevelopmentEvidence } from '../local-development/LocalDevelopmentEvidence'
import { useLocalDevelopmentEvidence } from '../local-development/useLocalDevelopmentEvidence'
import { DevelopmentPlanPanel } from '../planning/DevelopmentPlanPanel'
import { ToolCallList } from '../tool-calls/ToolCallList'
import { formatDateTime } from '../../shared/api/formatters'
import { OrchestrationControls } from './OrchestrationControls'
import { refreshAfterSuccess } from './refreshAfterSuccess'
import { TaskStatusBadge } from './TaskStatusBadge'
import { TaskTimeline } from './TaskTimeline'
import { useTaskDetail } from './useTaskDetail'

interface TaskDetailProps {
  taskId: string | null
  refreshKey: number
  onTaskChanged: () => void | Promise<void>
}

/**
 * Task Detail 主面板。
 *
 * 聚合任务详情、规格评审、M6 开发证据、Timeline、ToolCall 和 Approval。
 * 所有数据均来自 Platform API；空状态表示数据库当前没有记录。
 */
export function TaskDetail({ taskId, refreshKey, onTaskChanged }: TaskDetailProps) {
  const detail = useTaskDetail(taskId, refreshKey, onTaskChanged)
  const latestDevelopmentPlan = detail.data?.developmentPlans[0] ?? null
  const localDevelopmentEnabled = latestDevelopmentPlan?.status === 'approved'
  const handleLocalDevelopmentChanged = useCallback(async () => {
    await Promise.all([
      detail.refresh(),
      Promise.resolve(onTaskChanged()),
    ])
  }, [detail.refresh, onTaskChanged])
  const localDevelopment = useLocalDevelopmentEvidence(
    taskId,
    localDevelopmentEnabled,
    refreshKey,
    detail.streamEventRevision,
    handleLocalDevelopmentChanged,
  )

  const decideRequirement: typeof detail.decideRequirement = async (...args) => {
    return refreshAfterSuccess(detail.decideRequirement, onTaskChanged, ...args)
  }

  const decideDesign: typeof detail.decideDesign = async (...args) => {
    return refreshAfterSuccess(detail.decideDesign, onTaskChanged, ...args)
  }

  const decideApproval: typeof detail.decideApproval = async (...args) => {
    return refreshAfterSuccess(detail.decideApproval, onTaskChanged, ...args)
  }

  if (taskId === null) {
    return (
      <section className="panel detail-panel">
        <div className="welcome-state">
          <span className="welcome-spark" aria-hidden="true">✦</span>
          <p className="eyebrow">CloudHelm 工作台</p>
          <h2>今天想推进哪个研发任务？</h2>
          <p>从左侧选择任务，即可查看真实的规格、开发证据、Timeline、ToolCall 和 Approval 数据。</p>
        </div>
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
  const completedRuns = agentRuns.filter((run) => run.status === 'succeeded').length
  const cachedTokens = agentRuns.reduce((total, run) => total + run.cached_input_tokens, 0)
  const pendingApprovals = approvals.filter((approval) => approval.status === 'pending').length
  const latestTurn = agentRuns.reduce(
    (latest, run) => Math.max(latest, run.conversation_turn ?? 0),
    0,
  )

  return (
    <section className="panel detail-panel" aria-labelledby="task-detail-title">
      <div className="task-hero">
        <div className="task-hero-heading">
          <div>
            <p className="eyebrow">Task workspace</p>
            <h2 id="task-detail-title">{task.title}</h2>
          </div>
          <button type="button" className="ghost-button" onClick={detail.refresh}>
            刷新
          </button>
        </div>

        <div className="detail-meta">
          <TaskStatusBadge status={task.status} riskLevel={task.risk_level} />
          <span>阶段：{task.current_phase}</span>
          <span>更新：{formatDateTime(task.updated_at)}</span>
        </div>
        <p className="detail-description">{task.description}</p>

        <dl className="task-metric-strip">
          <div>
            <dt>主会话 Turn</dt>
            <dd>{latestTurn}</dd>
          </div>
          <div>
            <dt>成功 Agent</dt>
            <dd>{completedRuns}</dd>
          </div>
          <div>
            <dt>缓存 Token</dt>
            <dd>{cachedTokens.toLocaleString('zh-CN')}</dd>
          </div>
          <div>
            <dt>待审批</dt>
            <dd>{pendingApprovals}</dd>
          </div>
        </dl>
      </div>

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
        <div>
          <dt>创建时间</dt>
          <dd>{formatDateTime(task.created_at)}</dd>
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
        onDecideRequirement={decideRequirement}
        onDecideDesign={decideDesign}
      />
      <DevelopmentPlanPanel developmentPlans={developmentPlans} />
      <LocalDevelopmentControls
        task={task}
        workflowState={localDevelopment.data?.workflowState ?? null}
        loadStatus={localDevelopment.status}
        onStart={localDevelopment.start}
        onRunNext={localDevelopment.runNext}
      />
      <LocalDevelopmentEvidence
        enabled={localDevelopmentEnabled}
        status={localDevelopment.status}
        data={localDevelopment.data}
        error={localDevelopment.error}
        warning={localDevelopment.warning}
        onRetry={localDevelopment.refresh}
      />
      <TaskTimeline agentRuns={agentRuns} events={timeline} streamStatus={detail.streamStatus} />
      <ToolCallList toolCalls={toolCalls} />
      <ApprovalPanel approvals={approvals} onDecideApproval={decideApproval} />
    </section>
  )
}
