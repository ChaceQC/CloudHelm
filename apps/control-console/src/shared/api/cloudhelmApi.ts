import { apiGet, apiPost, buildApiUrl } from './apiClient'
import type {
  AgentRun,
  ApprovalRequest,
  ApprovalStatus,
  DecisionRequest,
  EventLog,
  PageResponse,
  Project,
  ProjectCreateInput,
  RequirementSpec,
  Task,
  TaskCreateInput,
  TechnicalDesign,
  ToolCall,
} from '../types/api'
import { TASK_EVENT_TYPES, parseTaskEvent } from '../types/events'

/**
 * CloudHelm 控制台 API 门面。
 *
 * 所有功能组件只能通过本文件访问 Platform API，避免在组件里散落 URL
 * 拼接、错误处理和 M2/M3 边界判断。
 */

export function listProjects(): Promise<PageResponse<Project>> {
  return apiGet<PageResponse<Project>>('/api/projects')
}

export function createProject(payload: ProjectCreateInput): Promise<Project> {
  return apiPost<Project>('/api/projects', payload)
}

export function listTasks(projectId: string): Promise<PageResponse<Task>> {
  return apiGet<PageResponse<Task>>('/api/tasks', { project_id: projectId })
}

export function getTask(taskId: string): Promise<Task> {
  return apiGet<Task>(`/api/tasks/${taskId}`)
}

export function createTask(payload: TaskCreateInput): Promise<Task> {
  return apiPost<Task>('/api/tasks', payload)
}

export function pauseTask(taskId: string, payload: DecisionRequest): Promise<Task> {
  return apiPost<Task>(`/api/tasks/${taskId}/pause`, payload)
}

export function resumeTask(taskId: string, payload: DecisionRequest): Promise<Task> {
  return apiPost<Task>(`/api/tasks/${taskId}/resume`, payload)
}

export function cancelTask(taskId: string, payload: DecisionRequest): Promise<Task> {
  return apiPost<Task>(`/api/tasks/${taskId}/cancel`, payload)
}

export function listRequirements(taskId: string): Promise<PageResponse<RequirementSpec>> {
  return apiGet<PageResponse<RequirementSpec>>(`/api/tasks/${taskId}/requirements`)
}

export function approveRequirement(requirementId: string, payload: DecisionRequest): Promise<RequirementSpec> {
  return apiPost<RequirementSpec>(`/api/requirements/${requirementId}/approve`, payload)
}

export function requestRequirementChanges(
  requirementId: string,
  payload: DecisionRequest,
): Promise<RequirementSpec> {
  return apiPost<RequirementSpec>(`/api/requirements/${requirementId}/request-changes`, payload)
}

export function listTechnicalDesigns(taskId: string): Promise<PageResponse<TechnicalDesign>> {
  return apiGet<PageResponse<TechnicalDesign>>(`/api/tasks/${taskId}/technical-designs`)
}

export function approveTechnicalDesign(designId: string, payload: DecisionRequest): Promise<TechnicalDesign> {
  return apiPost<TechnicalDesign>(`/api/technical-designs/${designId}/approve`, payload)
}

export function requestTechnicalDesignChanges(
  designId: string,
  payload: DecisionRequest,
): Promise<TechnicalDesign> {
  return apiPost<TechnicalDesign>(`/api/technical-designs/${designId}/request-changes`, payload)
}

export function listAgentRuns(taskId: string): Promise<PageResponse<AgentRun>> {
  return apiGet<PageResponse<AgentRun>>(`/api/tasks/${taskId}/agent-runs`)
}

export function listToolCalls(taskId: string): Promise<PageResponse<ToolCall>> {
  return apiGet<PageResponse<ToolCall>>(`/api/tasks/${taskId}/tool-calls`)
}

export function listApprovals(status?: ApprovalStatus): Promise<PageResponse<ApprovalRequest>> {
  return apiGet<PageResponse<ApprovalRequest>>('/api/approvals', { status })
}

export function approveApproval(approvalId: string, payload: DecisionRequest): Promise<ApprovalRequest> {
  return apiPost<ApprovalRequest>(`/api/approvals/${approvalId}/approve`, payload)
}

export function rejectApproval(approvalId: string, payload: DecisionRequest): Promise<ApprovalRequest> {
  return apiPost<ApprovalRequest>(`/api/approvals/${approvalId}/reject`, payload)
}

export function getTimeline(taskId: string): Promise<PageResponse<EventLog>> {
  return apiGet<PageResponse<EventLog>>(`/api/tasks/${taskId}/timeline`)
}

export interface TaskEventStreamHandlers {
  onEvent: (event: EventLog) => void
  onStatus: (status: 'connecting' | 'open' | 'closed' | 'error') => void
}

/**
 * 打开任务 SSE 事件流。
 *
 * M2 SSE 端点只回放已有事件并追加 heartbeat，不提供生产级持续推送；
 * 因此出错或连接结束后由调用方继续用 Timeline 轮询刷新。
 */
export function openTaskEventStream(taskId: string, handlers: TaskEventStreamHandlers): () => void {
  handlers.onStatus('connecting')
  const source = new EventSource(buildApiUrl(`/api/tasks/${taskId}/events/stream`))

  source.onopen = () => handlers.onStatus('open')
  source.onerror = () => {
    handlers.onStatus('error')
    source.close()
    handlers.onStatus('closed')
  }

  TASK_EVENT_TYPES.forEach((eventType) => {
    source.addEventListener(eventType, (message) => {
      const event = parseTaskEvent(message)
      if (event !== null) {
        handlers.onEvent(event)
      }
    })
  })

  return () => {
    source.close()
  }
}
