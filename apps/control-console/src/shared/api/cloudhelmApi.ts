import { apiGet, apiPost, buildApiUrl } from './apiClient'
import type {
  AgentRun,
  ApprovalRequest,
  ApprovalStatus,
  ArtifactDetailRead,
  ArtifactRead,
  DevelopmentPlan,
  DecisionRequest,
  EventLog,
  LocalDevelopmentActionRequest,
  LocalDevelopmentStateRead,
  LocalDevelopmentStepRead,
  OrchestrationActionRequest,
  OrchestrationState,
  OrchestrationStepResult,
  PageResponse,
  Project,
  ProjectCreateInput,
  PullRequestRecordRead,
  RequirementSpec,
  Task,
  TaskCreateInput,
  TechnicalDesign,
  ToolCall,
  ToolDeclaration,
  ToolGatewayCallInput,
} from '../types/api'
import { TASK_EVENT_TYPES, parseTaskEvent } from '../types/events'
import { createReconnectingEventStream } from './taskEventStream'

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

export function getOrchestrationState(taskId: string): Promise<OrchestrationState> {
  return apiGet<OrchestrationState>(`/api/tasks/${taskId}/orchestration`)
}

export function startTaskOrchestration(
  taskId: string,
  payload: OrchestrationActionRequest,
): Promise<OrchestrationStepResult> {
  return apiPost<OrchestrationStepResult>(`/api/tasks/${taskId}/start`, payload)
}

export function runNextTaskOrchestration(
  taskId: string,
  payload: OrchestrationActionRequest,
): Promise<OrchestrationStepResult> {
  return apiPost<OrchestrationStepResult>(`/api/tasks/${taskId}/run-next`, payload)
}

export function getLocalDevelopmentState(taskId: string): Promise<LocalDevelopmentStateRead> {
  return apiGet<LocalDevelopmentStateRead>(`/api/tasks/${taskId}/local-development`)
}

export function startLocalDevelopment(
  taskId: string,
  payload: LocalDevelopmentActionRequest,
): Promise<LocalDevelopmentStepRead> {
  return apiPost<LocalDevelopmentStepRead>(`/api/tasks/${taskId}/local-development/start`, payload)
}

export function runNextLocalDevelopment(
  taskId: string,
  payload: LocalDevelopmentActionRequest,
): Promise<LocalDevelopmentStepRead> {
  return apiPost<LocalDevelopmentStepRead>(`/api/tasks/${taskId}/local-development/run-next`, payload)
}

export function listArtifacts(taskId: string, artifactType?: string): Promise<PageResponse<ArtifactRead>> {
  return apiGet<PageResponse<ArtifactRead>>(`/api/tasks/${taskId}/artifacts`, {
    artifact_type: artifactType,
  })
}

export function getArtifactDetail(artifactId: string): Promise<ArtifactDetailRead> {
  return apiGet<ArtifactDetailRead>(`/api/artifacts/${artifactId}`)
}

export function listPullRequestRecords(taskId: string): Promise<PageResponse<PullRequestRecordRead>> {
  return apiGet<PageResponse<PullRequestRecordRead>>(`/api/tasks/${taskId}/pull-request-records`)
}

export function getPullRequestRecord(recordId: string): Promise<PullRequestRecordRead> {
  return apiGet<PullRequestRecordRead>(`/api/pull-request-records/${recordId}`)
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

export function listDevelopmentPlans(taskId: string): Promise<PageResponse<DevelopmentPlan>> {
  return apiGet<PageResponse<DevelopmentPlan>>(`/api/tasks/${taskId}/development-plans`)
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

export function listToolGatewayTools(): Promise<PageResponse<ToolDeclaration>> {
  return apiGet<PageResponse<ToolDeclaration>>('/api/tool-gateway/tools')
}

export function callToolGateway(taskId: string, payload: ToolGatewayCallInput): Promise<ToolCall> {
  return apiPost<ToolCall>(`/api/tasks/${taskId}/tool-gateway/call`, payload)
}

export function listApprovals(taskId?: string, status?: ApprovalStatus): Promise<PageResponse<ApprovalRequest>> {
  return apiGet<PageResponse<ApprovalRequest>>('/api/approvals', { task_id: taskId, status })
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
 * M2 SSE 端点每次回放已有事件后会关闭；客户端固定退避重连，并按事件
 * ID 去重，从而在不手工刷新页面的情况下读取后续落库事件。
 */
export function openTaskEventStream(taskId: string, handlers: TaskEventStreamHandlers): () => void {
  return createReconnectingEventStream({
    url: buildApiUrl(`/api/tasks/${taskId}/events/stream`),
    eventTypes: TASK_EVENT_TYPES,
    parseEvent: (message) => parseTaskEvent(message as MessageEvent<string>),
    onEvent: handlers.onEvent,
    onStatus: handlers.onStatus,
    createSource: (url) => {
      const browserSource = new EventSource(url)
      const sourceAdapter = {
        onopen: null as (() => void) | null,
        onerror: null as (() => void) | null,
        addEventListener: (eventType: string, listener: (message: { data: string }) => void) => {
          browserSource.addEventListener(eventType, (message) => {
            listener({ data: (message as MessageEvent<string>).data })
          })
        },
        close: () => browserSource.close(),
      }
      browserSource.onopen = () => sourceAdapter.onopen?.()
      browserSource.onerror = () => sourceAdapter.onerror?.()
      return sourceAdapter
    },
  })
}
