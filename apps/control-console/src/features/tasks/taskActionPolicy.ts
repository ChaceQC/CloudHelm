import type { TaskStatus } from '../../shared/types/api'

const PAUSABLE_STATUSES: readonly TaskStatus[] = ['created', 'running', 'waiting_approval']
const TERMINAL_STATUSES: readonly TaskStatus[] = ['failed', 'done', 'cancelled']
const EXECUTABLE_NEXT_ACTIONS = ['run_requirement', 'run_architect', 'resume_planning', 'run_planner']

/**
 * 判断任务是否允许从控制台暂停。
 *
 * 状态集合与 Platform API 的 TaskService 保持一致，避免页面展示后端必然拒绝
 * 的操作。后端仍是最终权限边界，前端判断只用于减少无效请求。
 */
export function canPauseTask(status: TaskStatus): boolean {
  return PAUSABLE_STATUSES.includes(status)
}

/**
 * 判断任务是否允许恢复。
 */
export function canResumeTask(status: TaskStatus): boolean {
  return status === 'paused'
}

/**
 * 判断任务是否允许取消。
 */
export function canCancelTask(status: TaskStatus): boolean {
  return !TERMINAL_STATUSES.includes(status)
}

/**
 * 判断编排是否允许执行 start。
 */
export function canStartOrchestration(status: TaskStatus, nextAction: string): boolean {
  return !isOrchestrationBlocked(status) && nextAction === 'start'
}

/**
 * 判断编排是否允许推进下一步。
 */
export function canRunNextOrchestration(status: TaskStatus, nextAction: string): boolean {
  return !isOrchestrationBlocked(status) && EXECUTABLE_NEXT_ACTIONS.includes(nextAction)
}

function isOrchestrationBlocked(status: TaskStatus): boolean {
  return status === 'paused' || TERMINAL_STATUSES.includes(status)
}
