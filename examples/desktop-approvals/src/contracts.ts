export type TaskStatus = "ready" | "waiting" | "cancel_requested";
export type TaskFilter = "all" | "ready" | "attention";
export interface DemoTask {
  id: string;
  title: string;
  goal: string;
  budget: number;
  status: TaskStatus;
  updatedAt: string;
  cancelReason?: string;
}
export interface DemoPlan {
  id: string;
  digest: string;
  currentRelease: string;
  release: string;
  configFrom: number;
  configTo: number;
  target: string;
  environment: string;
  expiresAt: string;
  approved: boolean;
}
export type ModalKind = "create" | "connection" | "task" | "operation" | "plan" | "digest" | "input" | "cancel";
export type DemoModal = { kind: ModalKind; reference?: string } | null;
export interface NewTaskInput {
  title: string;
  goal: string;
  budget: number;
}
export interface DemoController {
  tasks: DemoTask[];
  visibleTasks: DemoTask[];
  selectedTask: DemoTask;
  query: string;
  filter: TaskFilter;
  connected: boolean;
  lastSync: string;
  plan: DemoPlan;
  checkedAt: string;
  approvedAt: string;
  approvalConfirmed: boolean;
  notice: string;
  modal: DemoModal;
  setQuery(value: string): void;
  setFilter(value: TaskFilter): void;
  selectTask(id: string): void;
  setApprovalConfirmed(value: boolean): void;
  openModal(kind: ModalKind, reference?: string): void;
  closeModal(): void;
  dismissNotice(): void;
  toggleConnection(): void;
  createTask(input: NewTaskInput): boolean;
  startTask(): void;
  cancelTask(reason: string): boolean;
  checkPlan(): void;
  approvePlan(): void;
  refresh(): void;
}
