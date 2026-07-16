import type { EventLog } from './api'

/**
 * M2-M7-2B2 已落库且可进入 Task SSE 的事件类型。
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
  'TaskPhaseChanged',
  'RequirementSpecCreated',
  'RequirementSpecApproved',
  'RequirementSpecChangesRequested',
  'TechnicalDesignCreated',
  'TechnicalDesignApproved',
  'TechnicalDesignChangesRequested',
  'DevelopmentPlanCreated',
  'DevelopmentPlanApproved',
  'DevelopmentPlanChangesRequested',
  'AgentRunRecorded',
  'AgentRunStarted',
  'AgentRunCompleted',
  'AgentRunFailed',
  'AgentRunCancelled',
  'AgentConversationCreated',
  'AgentConversationStopped',
  'SubagentSpawned',
  'SubagentCompleted',
  'SubagentStopped',
  'ToolCallRecorded',
  'ToolCallStarted',
  'ToolCallSucceeded',
  'ToolCallFailed',
  'ToolCallRejected',
  'ToolCallCancelled',
  'ApprovalRequested',
  'ApprovalApproved',
  'ApprovalRejected',
  'ApprovalExpired',
  'LocalDevelopmentStarted',
  'ScaffoldCompleted',
  'CodePatchGenerated',
  'TestRunStarted',
  'TestRunPassed',
  'TestRunFailed',
  'ReviewCompleted',
  'SecurityScanCompleted',
  'SecurityScanBlocked',
  'ArtifactCreated',
  'BranchCreated',
  'CommitCreated',
  'PullRequestRecordCreated',
  'WorkflowJobQueued',
  'ReleaseCandidateApprovalRequested',
  'ReleaseCandidateApproved',
  'ReleaseCandidateRejected',
] as const

export type TaskEventType = (typeof TASK_EVENT_TYPES)[number]

export function parseTaskEvent(message: MessageEvent<string>): EventLog | null {
  try {
    return JSON.parse(message.data) as EventLog
  } catch {
    return null
  }
}
