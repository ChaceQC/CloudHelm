import { useState } from 'react'
import { formatApiError } from '../../shared/api/formatters'
import type { OrchestrationState, OrchestrationStepResult, Task } from '../../shared/types/api'
import { canRunNextOrchestration, canStartOrchestration } from './taskActionPolicy'

interface OrchestrationControlsProps {
  task: Task
  orchestration: OrchestrationState | null
  onStart: () => Promise<OrchestrationStepResult>
  onRunNext: () => Promise<OrchestrationStepResult>
  onTaskChanged: () => void
}

/**
 * M4 编排控制区。
 *
 * 控制区只调用真实 `start` / `run-next` API，不在前端生成 Requirement、
 * Design 或 Plan；失败时展示后端返回的 trace_id 错误。
 */
export function OrchestrationControls({
  task,
  orchestration,
  onStart,
  onRunNext,
  onTaskChanged,
}: OrchestrationControlsProps) {
  const [operationStatus, setOperationStatus] = useState<'idle' | 'running'>('idle')
  const [message, setMessage] = useState<string | null>(null)

  const runOperation = async (operation: () => Promise<OrchestrationStepResult>) => {
    setOperationStatus('running')
    setMessage(null)
    try {
      const result = await operation()
      setMessage(result.message)
      onTaskChanged()
    } catch (error) {
      setMessage(formatApiError(error))
    } finally {
      setOperationStatus('idle')
    }
  }

  const nextAction = orchestration?.next_action ?? 'unknown'
  const isBusy = operationStatus === 'running'
  const canStart = canStartOrchestration(task.status, nextAction)
  const canRunNext = canRunNextOrchestration(task.status, nextAction)

  return (
    <section className="sub-panel orchestration-panel" aria-labelledby="orchestration-title">
      <div className="inline-heading">
        <h3 id="orchestration-title">M4 Agent 编排</h3>
        <span className="stream-chip">下一步：{nextAction}</span>
      </div>
      <p className="muted">
        M4 只运行 Requirement / Architect / Planner，写入需求、设计、开发计划和事件日志；不会修改代码、
        调用工具、创建 PR 或部署远端环境。
      </p>
      <dl className="meta-grid">
        <div>
          <dt>当前阶段</dt>
          <dd>{task.current_phase}</dd>
        </div>
        <div>
          <dt>计划状态</dt>
          <dd>{orchestration?.plan_exists === true ? '已有 DevelopmentPlan' : '尚未生成'}</dd>
        </div>
        <div>
          <dt>设计审批</dt>
          <dd>{orchestration?.design_approved === true ? '已通过' : '未通过或无需审批'}</dd>
        </div>
      </dl>
      <div className="action-row">
        <button type="button" disabled={isBusy || !canStart} onClick={() => void runOperation(onStart)}>
          启动编排
        </button>
        <button type="button" disabled={isBusy || !canRunNext} onClick={() => void runOperation(onRunNext)}>
          推进一步
        </button>
      </div>
      {message !== null ? <p className="operation-message">{message}</p> : null}
    </section>
  )
}
