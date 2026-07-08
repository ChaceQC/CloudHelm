import type { EventLog } from './api'

/**
 * M2 已落库的任务相关事件类型。
 *
 * EventSource 需要显式监听具名事件；后续事件 schema 扩展后应同步
 * `packages/shared-contracts/schemas/events/task-event.schema.json`。
 */
export const TASK_EVENT_TYPES = [
  'ProjectCreated',
  'TaskCreated',
  'TaskPaused',
  'TaskResumed',
  'TaskCancelled',
  'RequirementSpecCreated',
  'RequirementSpecApproved',
  'RequirementSpecChangesRequested',
  'TechnicalDesignCreated',
  'TechnicalDesignApproved',
  'TechnicalDesignChangesRequested',
  'AgentRunRecorded',
  'ToolCallRecorded',
  'ApprovalRequested',
  'ApprovalApproved',
  'ApprovalRejected',
] as const

export type TaskEventType = (typeof TASK_EVENT_TYPES)[number]

export function parseTaskEvent(message: MessageEvent<string>): EventLog | null {
  try {
    return JSON.parse(message.data) as EventLog
  } catch {
    return null
  }
}
