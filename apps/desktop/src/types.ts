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
export interface Reply { status: number; body: Json }
export interface SyncEvent {
  cursor: number; event_id: string; project_id: string; aggregate_kind: string;
  aggregate_id: string; aggregate_version: number; event_type: string; schema_version: string;
}
export interface Batch { schema_revision: string; stream_id: string; cursor: number; events: SyncEvent[] }
export interface SyncNotice { subscription_id: string; kind: string; data: Batch | null }
export type Connection = "disconnected" | "connecting" | "syncing" | "live" | "offline" | "revoked" | "incompatible";
