import type { ReactNode } from "react";
import { stringify } from "./api";

const labels: Record<string, string> = {
  disconnected: "未连接", connecting: "连接中", syncing: "同步中", live: "已连接", offline: "离线 · 只读",
  revoked: "权限已变化", incompatible: "需要升级", pending: "待处理", running: "推进中", blocked: "已阻塞",
  completed: "已完成", cancelled: "已取消", cancellation_requested: "取消已请求", accepted: "已接收",
  approval_pending: "待批准", awaiting_remote_agent: "待远端执行", execution_registered: "执行已登记",
  needs_reconciliation: "unknown · 待核对", succeeded: "执行成功", failed_known: "已知失败",
};

export function Status({ value }: { value: string }) {
  return <span className={`status ${value}`}>{labels[value] ?? value}</span>;
}
export function Empty({ children }: { children: ReactNode }) { return <div className="empty">{children}</div>; }
export function Facts({ values }: { values: Record<string, unknown> }) {
  return <dl className="facts">{Object.entries(values).map(([key, value]) =>
    <div key={key}><dt>{key}</dt><dd>{value == null ? "—" : String(value)}</dd></div>)}</dl>;
}
export function JsonView({ value, title = "完整事实" }: { value: unknown; title?: string }) {
  return <details className="json"><summary>{title}</summary><pre>{stringify(value)}</pre></details>;
}
