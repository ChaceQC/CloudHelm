import type { LocalDevelopmentAction, TaskStatus } from '../../shared/types/api'

const TERMINAL_STATUSES: readonly TaskStatus[] = ['failed', 'done', 'cancelled']
const RUN_NEXT_ACTIONS: readonly LocalDevelopmentAction[] = [
  'run_scaffold',
  'run_coder',
  'run_tester',
  'run_reviewer',
  'run_security',
  'finalize_local_pull_request',
]

/**
 * 判断是否允许启动 M6 本地开发闭环。
 *
 * 前端只负责减少无效请求；DevelopmentPlan 最新版审批、幂等和状态迁移仍由
 * Platform API 作为最终边界。
 */
export function canStartLocalDevelopment(
  status: TaskStatus,
  nextAction: string,
  activeAgentRunId: string | null,
): boolean {
  return (
    !isExecutionBlocked(status)
    && activeAgentRunId === null
    && nextAction === 'start_local_development'
  )
}

/**
 * 判断是否允许执行一次 M6 run-next。
 */
export function canRunNextLocalDevelopment(
  status: TaskStatus,
  nextAction: string,
  activeAgentRunId: string | null,
): boolean {
  return (
    !isExecutionBlocked(status)
    && activeAgentRunId === null
    && RUN_NEXT_ACTIONS.includes(nextAction as LocalDevelopmentAction)
  )
}

function isExecutionBlocked(status: TaskStatus): boolean {
  return status === 'paused' || TERMINAL_STATUSES.includes(status)
}
