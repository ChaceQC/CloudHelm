export type Json = Record<string, unknown>;
export interface Identity { user_id: string; display_name: string; session_id: string; expires_at: string }
export interface Project { project_id: string; name: string; revision: number; permission_revision: number; policy_revision: number }
export interface Blocker { code: string; object_kind: string; object_id: string | null }
export interface Task {
  task_id: string; project_id: string; state: string; version: number; control_revision: number;
  input_validity_revision: number; input_status: string; ordinary_progress_closed: boolean;
  declaration: { title: string; goal: string; budget: { amount: string; currency: string } };
  cancellation: Json | null; completion_report_id: string | null; blockers: Blocker[];
  work_items: { work_item_id: string; state: string; goal: string }[];
}
export interface AgentView {
  task_id: string; truncated: boolean;
  sessions: {
    session_id: string; version: number; state: string; work_item_id: string;
    policy: { max_requests: number; max_duration_seconds: number; max_output_tokens: number; per_request_cost_upper_bound: string };
    runs: {
      run_id: string; state: string; request_count: number; reserved_cost: string; created_at: string;
      started_at: string | null; deadline_at: string | null; result: Json | null;
      tool_results: { tool_call_id: string; tool_name: string; result: unknown }[];
      requests: { request_record_id: string; state: string; reserved_cost: string; calculated_cost: string | null;
        billed_amount: string | null; billed_currency: string | null }[];
      waits: { wait_condition_id: string; operation_id: string; state: string; continuation_run_id: string | null }[];
    }[];
  }[];
}
export interface AgentDiff {
  workspace_id: string | null; work_item_id: string; truncated: boolean;
  files: { path: string; patch: string | null; binary: boolean; truncated: boolean; reason_code: string | null }[];
}
export interface EngineeringRef {
  kind: string; object_id: string; revision: string; authority: string | null;
  digest: string | null; digest_algorithm: string | null;
}
export interface HumanTestOptions {
  candidates: { candidate_id: string; label: string; test_config_ref: EngineeringRef; dataset_ref: EngineeringRef }[];
  tester_id: string; management_start_url: string | null;
}
export interface HumanTestSession {
  session_id: string; round_id: string; revision: number; task_version: number; control_revision: number;
  input_validity_revision: number; candidate_id: string; candidate_ref: EngineeringRef;
  final_input_set_ref: EngineeringRef; policy_ref: EngineeringRef; test_config_ref: EngineeringRef;
  dataset_ref: EngineeringRef; policy: { is_completion_gate: boolean; skip_allowed: boolean };
  tester: { kind: "human"; subject_id: string }; environment_id: string | null;
  state: "preparing" | "awaiting_human" | "testing" | "completed" | "expired" | "cancelled";
  preparation_reason: string | null; ready_at: string | null; expires_at: string | null;
  last_human_activity_at: string | null; idle_warning_at: string | null; renewed_at: string | null;
  feedback: { summary: string; steps: string | null; expected: string | null; actual: string | null } | null;
  conclusion: { conclusion: "passed" | "changes_requested" | "skipped"; concluded_at_utc: string;
    concluded_by: { subject_id: string }; skip_reason: string | null } | null;
}
export interface HumanTestEnvironment {
  environment_id: string; purpose: string; state: string; actual_revision: string | null;
  resource_reservation_id: string | null; expires_at: string | null; reason: string | null;
  revocation_status: string | null;
  management_start_url?: string | null;
  entry_origin?: string | null;
  client_route?: "browser_windows_edge" | "browser_linux_chromium" | "external_windows_edge" |
    "external_linux_chromium" | "tauri_windows_webview2" | "tauri_linux_webkitgtk" | null;
}
export interface DeliveryObject {
  kind: "release" | "configuration" | "environment" | "plan"; object_id: string; digest: string;
  revision: number; release_id: string | null; config_revision_id: string | null;
  target_id: string | null; operation_id: string | null; approved: boolean;
}
export interface Snapshot {
  schema_revision: "p1-sync-r1"; stream_id: string; cursor: number; captured_at: string;
  project: Project; tasks: Task[]; objects: DeliveryObject[]; tombstones: string[];
  available_actions: string[];
}
export interface DomainObject { object_id: string; digest: string; value: Json }
export interface Deployment {
  plan: DomainObject; approval: Json | null; operation_id: string | null; status: string; environment_revision: number;
}
export interface HubRequest { method: "GET" | "POST"; route: string; body?: Json; idempotency_key?: string }
export interface PendingCommand extends HubRequest { generation: string }
export interface Connected { identity: Identity; generation: string }
export interface Reply { status: number; body: Json }
export interface SyncEvent {
  cursor: number; event_id: string; project_id: string; aggregate_kind: string;
  aggregate_id: string; aggregate_version: number; event_type: string; schema_version: string;
}
export interface Batch { schema_revision: string; stream_id: string; cursor: number; events: SyncEvent[] }
export interface SyncNotice { subscription_id: string; kind: string; data: Batch | null }
export type Connection = "disconnected" | "connecting" | "syncing" | "live" | "offline" | "revoked" | "incompatible";
