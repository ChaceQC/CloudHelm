/**
 * CloudHelm M2-M7-2B1 API 类型。
 *
 * 本文件手写映射 `packages/shared-contracts/openapi/cloudhelm.openapi.yaml`
 * 中当前控制台需要的 DTO。后续如接入 OpenAPI 类型生成器，应以该契约为
 * 唯一来源并替换本文件，避免组件层散落字段猜测。
 */

export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue }

export type RiskLevel = 'L0' | 'L1' | 'L2' | 'L3' | 'L4'

export type TaskStatus =
  | 'created'
  | 'running'
  | 'waiting_approval'
  | 'paused'
  | 'failed'
  | 'done'
  | 'cancelled'

export type ReviewStatus = 'draft' | 'approved' | 'changes_requested'

export type AgentRunStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'cancelled'

export type ToolCallStatus =
  | 'pending'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'waiting_approval'
  | 'cancelled'

export type ApprovalStatus =
  | 'pending'
  | 'approved'
  | 'rejected'
  | 'expired'
  | 'cancelled'

export interface PageInfo {
  limit: number
  next_cursor: string | null
}

export interface PageResponse<TItem> {
  items: TItem[]
  page: PageInfo
}

export interface ApiErrorResponse {
  code: string
  message: string
  detail: JsonValue | null
  trace_id: string
}

export interface DecisionRequest {
  actor_id?: string
  reason?: string | null
}

export interface ProjectCreateInput {
  name: string
  repo_url: string
  default_branch: string
  provider: string
}

export interface Project {
  id: string
  name: string
  repo_url: string
  default_branch: string
  provider: string
  created_at: string
  updated_at: string
}

export interface RepositoryBindingPutInput {
  profile_key: string
}

export interface RepositoryBinding {
  id: string
  project_id: string
  provider: 'gitea'
  profile_key: string
  repository_external_id: string
  repository_owner: string
  repository_name: string
  default_branch: string
  workflow_id: string
  release_ref_prefix: string
  status: 'active' | 'disabled'
  created_at: string
  updated_at: string
}

export interface TaskCreateInput {
  project_id: string
  title: string
  description: string
  source_type?: string
  source_ref?: string | null
  risk_level?: RiskLevel
  created_by?: string
}

export interface Task {
  id: string
  project_id: string
  title: string
  description: string
  source_type: string
  source_ref: string | null
  status: TaskStatus
  risk_level: RiskLevel
  current_phase: string
  created_by: string
  created_at: string
  updated_at: string
}

export interface RequirementSpec {
  id: string
  task_id: string
  project_id: string
  source_type: string
  raw_input: string
  user_story: string | null
  constraints_json: JsonValue[]
  acceptance_criteria_json: JsonValue[]
  status: ReviewStatus
  version: number
  created_at: string
  updated_at: string
}

export interface TechnicalDesign {
  id: string
  task_id: string
  requirement_spec_id: string
  design_type: string
  content_markdown: string
  openapi_json: Record<string, JsonValue> | null
  db_schema_json: Record<string, JsonValue> | null
  mermaid_diagram: string | null
  risk_level: RiskLevel
  status: ReviewStatus
  created_by_agent_run_id: string | null
  version: number
  created_at: string
  updated_at: string
}

export type DevelopmentPlanStatus = 'ready_for_review' | 'approved' | 'changes_requested'

export interface DevelopmentPlan {
  id: string
  task_id: string
  project_id: string
  technical_design_id: string
  summary: string
  steps_json: Record<string, JsonValue>[]
  risks_json: Record<string, JsonValue>[]
  status: DevelopmentPlanStatus
  version: number
  created_by_agent_run_id: string | null
  created_at: string
  updated_at: string
}

export interface ProviderRequestUsage {
  response_id: string | null
  prompt_cache_key: string | null
  input_tokens: number
  cached_input_tokens: number
  output_tokens: number
  cache_hit: boolean
}

export interface AgentRun {
  id: string
  task_id: string
  conversation_id: string | null
  conversation_turn: number | null
  agent_type: string
  status: AgentRunStatus
  workflow_step: string | null
  attempt: number | null
  idempotency_key: string | null
  model_name: string | null
  prompt_hash: string | null
  summary: string | null
  structured_output_type: string | null
  structured_output_json: Record<string, JsonValue> | null
  error_code: string | null
  error_message: string | null
  input_tokens: number
  output_tokens: number
  cached_input_tokens: number
  provider_request_count: number
  provider_requests: ProviderRequestUsage[]
  provider_response_id: string | null
  prompt_cache_key: string | null
  cost_usd: string
  started_at: string
  finished_at: string | null
}

export interface ToolCall {
  id: string
  task_id: string
  agent_run_id: string | null
  tool_name: string
  provider_call_id: string | null
  provider_item_type: string | null
  risk_level: RiskLevel
  arguments_summary: string
  audit_json: Record<string, JsonValue>
  result_json: Record<string, JsonValue> | null
  result_summary: string | null
  stdout_summary: string | null
  stderr_summary: string | null
  duration_ms: number | null
  error_code: string | null
  status: ToolCallStatus
  approval_id: string | null
  idempotency_key: string | null
  started_at: string
  finished_at: string | null
}

export interface ToolDeclaration {
  name: string
  description: string
  risk_level: RiskLevel
  requires_approval: boolean
  allowed_agent_types: string[]
  allow_system_call: boolean
  audit_fields: string[]
  arguments_schema: Record<string, JsonValue>
  result_schema: Record<string, JsonValue>
}

export interface ToolGatewayCallInput {
  agent_run_id?: string | null
  tool_name: string
  risk_level: RiskLevel
  idempotency_key: string
  arguments: Record<string, JsonValue>
  reason: string
}

export interface ApprovalRequest {
  id: string
  task_id: string
  action: string
  risk_level: RiskLevel
  reason: string
  resource_type: string | null
  resource_id: string | null
  request_hash: string | null
  status: ApprovalStatus
  requested_by_agent_run_id: string | null
  decided_by: string | null
  decided_at: string | null
  expires_at: string | null
  consumed_at: string | null
  created_at: string
}

export interface EventLog {
  id: string
  task_id: string | null
  event_type: string
  actor_type: string
  actor_id: string | null
  payload: Record<string, JsonValue>
  created_at: string
}

export interface OrchestrationActionRequest {
  actor_id?: string
  reason?: string | null
  expected_phase?: string | null
}

export interface OrchestrationState {
  task_id: string
  current_phase: string
  next_action: string
  plan_exists: boolean
  design_approved: boolean
}

export interface OrchestrationStepResult {
  task: Task
  action: string
  message: string
  agent_run: AgentRun | null
  requirement: RequirementSpec | null
  technical_design: TechnicalDesign | null
  development_plan: DevelopmentPlan | null
  approval: ApprovalRequest | null
}

export type * from './localDevelopment'
