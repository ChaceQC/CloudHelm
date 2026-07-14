import { useState } from 'react'
import { formatApiError } from '../../shared/api/formatters'
import type {
  LocalDevelopmentStateRead,
  LocalDevelopmentStepRead,
  Task,
} from '../../shared/types/api'
import {
  canRunNextLocalDevelopment,
  canStartLocalDevelopment,
} from './localDevelopmentActionPolicy'

interface LocalDevelopmentControlsProps {
  task: Task
  workflowState: LocalDevelopmentStateRead | null
  loadStatus: 'idle' | 'loading' | 'ready' | 'error'
  onStart: () => Promise<LocalDevelopmentStepRead>
  onRunNext: () => Promise<LocalDevelopmentStepRead>
}

const actionLabels: Record<string, string> = {
  start_local_development: '启动本地开发',
  run_scaffold: '运行 Scaffold',
  run_coder: '运行 Coder',
  run_tester: '运行 Tester',
  run_reviewer: '运行 Reviewer',
  run_security: '运行 Security',
  finalize_local_pull_request: '生成本地 PR 记录',
  stop: '本地闭环已完成',
}

/**
 * M6 本地开发单步控制区。
 *
 * 这里只触发 start/run-next；受控 workspace、工具参数、幂等和门禁均由
 * Platform API 与 Tool Gateway 决定，页面不接受任意路径或命令输入。
 */
export function LocalDevelopmentControls({
  task,
  workflowState,
  loadStatus,
  onStart,
  onRunNext,
}: LocalDevelopmentControlsProps) {
  const [operationStatus, setOperationStatus] = useState<'idle' | 'running'>('idle')
  const [message, setMessage] = useState<string | null>(null)
  const nextAction = workflowState?.next_action ?? 'waiting_for_approved_plan'
  const isBusy = operationStatus === 'running'
  const canStart = workflowState !== null && canStartLocalDevelopment(
    task.status,
    nextAction,
    workflowState.active_agent_run_id,
  )
  const canRunNext = workflowState !== null && canRunNextLocalDevelopment(
    task.status,
    nextAction,
    workflowState.active_agent_run_id,
  )

  const runOperation = async (operation: () => Promise<LocalDevelopmentStepRead>) => {
    setOperationStatus('running')
    setMessage(null)
    try {
      const result = await operation()
      setMessage(result.message)
    } catch (error) {
      setMessage(formatApiError(error))
    } finally {
      setOperationStatus('idle')
    }
  }

  return (
    <section className="sub-panel local-development-panel" aria-labelledby="local-development-title">
      <div className="inline-heading">
        <div>
          <p className="eyebrow">本地开发闭环</p>
          <h3 id="local-development-title">M6 Code · Test · Review · PR</h3>
        </div>
        <span className="stream-chip">
          下一步：{actionLabels[nextAction] ?? nextAction}
        </span>
      </div>
      <p className="muted">
        每次只推进一个可审计步骤；文件、测试、安全扫描和 Git 操作全部经过 Tool Gateway，
        最终生成 provider=local 的等价 PR record。
      </p>

      <dl className="meta-grid local-development-meta">
        <div>
          <dt>当前阶段</dt>
          <dd>{workflowState?.current_phase ?? task.current_phase}</dd>
        </div>
        <div>
          <dt>DevelopmentPlan</dt>
          <dd>{workflowState?.development_plan_id ?? '等待最新版计划审批'}</dd>
        </div>
        <div>
          <dt>运行中 Agent</dt>
          <dd>{workflowState?.active_agent_run_id ?? '无'}</dd>
        </div>
        <div>
          <dt>证据状态</dt>
          <dd>
            {loadStatus === 'loading'
              ? '读取中'
              : workflowState === null
                ? '等待进入 M6'
                : `${Object.keys(workflowState.latest_artifact_ids).length} 类 Artifact`}
          </dd>
        </div>
      </dl>

      <div className="action-row local-development-actions">
        <button
          type="button"
          disabled={isBusy || !canStart}
          onClick={() => void runOperation(onStart)}
        >
          启动本地开发
        </button>
        <button
          type="button"
          disabled={isBusy || !canRunNext}
          onClick={() => void runOperation(onRunNext)}
        >
          {isBusy ? '正在推进...' : actionLabels[nextAction] ?? '推进下一步'}
        </button>
      </div>
      {message !== null ? <p className="operation-message">{message}</p> : null}
    </section>
  )
}
