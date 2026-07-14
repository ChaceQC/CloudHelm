import type { AgentRun, JsonValue, Task, ToolCall } from './api'

/**
 * M6 本地开发闭环类型。
 *
 * 字段手工映射 Platform API 的 Artifact、PullRequestRecord 和
 * LocalDevelopment DTO。Artifact 详情仅包含服务端生成的安全预览，不暴露
 * storage key、workspace root 或本机绝对路径。
 */

export type ArtifactProducerType = 'agent' | 'tool' | 'system'
export type ArtifactStatus = 'available' | 'invalidated' | 'missing'
export type PullRequestProvider = 'local' | 'github' | 'gitea'
export type PullRequestRecordStatus = 'open' | 'superseded' | 'closed'

export type LocalDevelopmentAction =
  | 'start_local_development'
  | 'run_scaffold'
  | 'run_coder'
  | 'run_tester'
  | 'run_reviewer'
  | 'run_security'
  | 'finalize_local_pull_request'
  | 'stop'

export interface ArtifactPreview {
  kind: 'text' | 'json'
  text: string | null
  json_value: JsonValue | null
  truncated: boolean
  bytes_returned: number
}

export interface ArtifactRead {
  id: string
  task_id: string
  agent_run_id: string | null
  tool_call_id: string | null
  producer_type: ArtifactProducerType
  artifact_type: string
  status: ArtifactStatus
  display_name: string
  media_type: string
  uri: string
  sha256: string
  size_bytes: number
  summary: string
  metadata_json: Record<string, JsonValue>
  created_at: string
  updated_at: string
}

export interface ArtifactDetailRead extends ArtifactRead {
  preview: ArtifactPreview | null
}

export interface PullRequestChangedFile {
  path: string
  operation?: string
  intent?: string
  [key: string]: JsonValue | undefined
}

export interface PullRequestRecordRead {
  id: string
  task_id: string
  project_id: string
  development_plan_id: string
  created_by_agent_run_id: string | null
  branch_tool_call_id: string | null
  commit_tool_call_id: string | null
  provider: PullRequestProvider
  status: PullRequestRecordStatus
  title: string
  summary: string
  base_branch: string
  head_branch: string
  base_commit_sha: string
  commit_sha: string
  changed_files_json: PullRequestChangedFile[]
  diff_stat_json: Record<string, JsonValue>
  diff_artifact_id: string
  test_artifact_id: string
  review_artifact_id: string
  security_artifact_id: string
  url: string | null
  created_at: string
  updated_at: string
}

export interface LocalDevelopmentActionRequest {
  actor_id?: string
  reason?: string | null
}

export interface LocalDevelopmentStateRead {
  task_id: string
  current_phase: string
  next_action: LocalDevelopmentAction | string
  development_plan_id: string
  active_agent_run_id: string | null
  latest_artifact_ids: Record<string, string>
  latest_pull_request_record_id: string | null
}

export interface LocalDevelopmentStepRead {
  task: Task
  action: string
  message: string
  agent_run: AgentRun | null
  tool_calls: ToolCall[]
  artifacts: ArtifactRead[]
  pull_request_record: PullRequestRecordRead | null
  gate_evidence: Record<string, JsonValue>
}

export interface ChangedFileEvidence {
  path: string
  operation: 'created' | 'updated' | 'deleted'
  intent: string
  tool_call_id: string | null
  sha256: string | null
}

export interface CommandExecutionEvidence {
  call_id: string
  tool_call_id: string | null
  command: string[]
  purpose: string
  status: 'succeeded' | 'failed' | 'waiting_approval'
  exit_code: number | null
  passed_count: number | null
  failed_count: number | null
  skipped_count: number | null
  duration_ms: number | null
  report_ref: string | null
  stdout_summary: string | null
  stderr_summary: string | null
  error_code: string | null
}

export interface TestReportContent {
  task_id: string
  development_plan_id: string
  summary: string
  status: 'passed' | 'failed' | 'partial' | 'blocked'
  commands: CommandExecutionEvidence[]
  passed_count: number | null
  failed_count: number | null
  skipped_count: number | null
  failure_reasons: string[]
  risk_level: string
}

export interface AcceptanceReviewContent {
  criterion_id: string
  status: 'satisfied' | 'partial' | 'missing'
  evidence_refs: string[]
  notes: string
}

export interface ReviewIssueContent {
  id: string
  severity: 'low' | 'medium' | 'high' | 'critical'
  path: string | null
  line: number | null
  message: string
  recommendation: string
}

export interface ReviewReportContent {
  task_id: string
  development_plan_id: string
  summary: string
  verdict: 'approved' | 'changes_requested' | 'blocked'
  acceptance_results: AcceptanceReviewContent[]
  issues: ReviewIssueContent[]
  changed_files: ChangedFileEvidence[]
  proceed_to_security: boolean
  risk_level: string
}

export interface SecurityFindingContent {
  id: string
  scanner: string
  rule_id: string
  severity: 'info' | 'low' | 'medium' | 'high' | 'critical'
  path: string | null
  line: number | null
  message: string
}

export interface SecurityReportContent {
  task_id: string
  development_plan_id: string
  summary: string
  verdict: 'passed' | 'failed' | 'partial' | 'blocked'
  scanners: CommandExecutionEvidence[]
  findings: SecurityFindingContent[]
  remaining_risks: string[]
  blocking: boolean
  risk_level: string
}
