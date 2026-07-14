export type TaskDetailLoadStatus = 'idle' | 'loading' | 'ready' | 'error'
export type TaskDetailStreamStatus = 'idle' | 'connecting' | 'open' | 'closed' | 'error'

interface CurrentRequestGate {
  isCurrent: (token: number) => boolean
}

export interface TaskDetailState<TData> {
  taskId: string | null
  status: TaskDetailLoadStatus
  data: TData | null
  error: string | null
  streamStatus: TaskDetailStreamStatus
}

export interface TaskDetailRequestIdentity {
  taskId: string | null
  token: number
}

/**
 * 创建与当前 Task 绑定的空详情状态。
 *
 * Task 切换时必须先返回不含旧数据的状态，避免新任务标题下仍显示并操作旧
 * Requirement、Design 或 Approval。
 */
export function createEmptyTaskDetailState<TData>(
  taskId: string | null,
): TaskDetailState<TData> {
  return {
    taskId,
    status: taskId === null ? 'idle' : 'loading',
    data: null,
    error: null,
    streamStatus: 'idle',
  }
}

/**
 * 只暴露与当前 Task ID 一致的详情状态。
 *
 * React effect 在 render 后才启动新请求，因此这里承担同步切换门禁：即使旧
 * state 仍在内存中，界面也只能看到新 Task 的空加载态。
 */
export function visibleTaskDetailState<TData>(
  state: TaskDetailState<TData>,
  currentTaskId: string | null,
): TaskDetailState<TData> {
  return state.taskId === currentTaskId
    ? state
    : createEmptyTaskDetailState<TData>(currentTaskId)
}

/**
 * 同时核对请求顺序和 Task 身份，拒绝旧 Task 的迟到响应。
 */
export function canCommitTaskDetailRequest(
  request: TaskDetailRequestIdentity,
  currentTaskId: string | null,
  gate: CurrentRequestGate,
): boolean {
  return request.taskId === currentTaskId && gate.isCurrent(request.token)
}
