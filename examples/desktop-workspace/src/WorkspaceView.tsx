import { useState } from "react";
import {
  ArrowsClockwise, CalendarBlank, CaretDown, CaretRight, CheckCircle,
  ClipboardText, Clock, CompassRose, Cube, HouseLine, ListBullets,
  MagnifyingGlass, PlusCircle, Pulse, ShieldCheck,
  Sparkle, User, WarningCircle, X,
} from "@phosphor-icons/react";
import type { DemoController, DemoTask, TaskFilter } from "./contracts";
import "./workspace.css";

type ViewProps = { demo: DemoController };
type TaskSelection = { onSelect(id: string): void };
const ORIGINAL_TASK_ID = "TASK-1042";

function syncClock(value: string) {
  return value.match(/\d{2}:\d{2}/)?.[0] ?? value;
}

function WorkspaceHeader({ demo }: ViewProps) {
  return (
    <header className="ws-header">
      <div className="ws-brand"><CompassRose size={34} weight="bold" /><span>CloudHelm</span></div>
      <span className="ws-header-divider" />
      <button className="ws-connection" onClick={() => demo.openModal("connection")}>
        <span className={`ws-connection-dot ${demo.connected ? "" : "is-offline"}`} />
        Hub {demo.connected ? "已连接" : "已断开"}
      </button>
      <div className="ws-header-meta">
        <span className="ws-identity"><User size={20} />当前身份：项目维护者</span>
        <span className="ws-demo-label">演示数据</span>
        <span className="ws-header-time"><Clock size={19} />10月26日 {syncClock(demo.lastSync)}</span>
      </div>
    </header>
  );
}

function ProjectSidebar({ demo }: ViewProps) {
  const items = [
    { label: "项目概览", Icon: HouseLine, action: () => demo.openModal("digest", "project") },
    { label: "任务", Icon: ListBullets, action: () => { demo.setFilter("all"); demo.setQuery(""); } },
    { label: "部署计划", Icon: CalendarBlank, action: () => demo.openModal("plan", demo.plan.id) },
    { label: "部署跟踪", Icon: Pulse, action: () => demo.openModal("operation", "Op-218") },
    { label: "连接与身份", Icon: ShieldCheck, action: () => demo.openModal("connection") },
  ];
  return (
    <aside className="ws-sidebar" aria-label="项目导航">
      <button className="ws-project" aria-label="查看便签服务项目概览" onClick={() => demo.openModal("digest", "project")}>
        <span className="ws-project-category"><Cube size={16} /><span>项目</span><Sparkle size={11} weight="fill" /></span>
        <span className="ws-project-name">便签服务<CaretDown size={18} /></span>
      </button>
      <nav className="ws-navigation">
        {items.map(({ label, Icon, action }) => (
          <button key={label} className={`ws-nav-item ${label === "任务" ? "is-active" : ""}`}
            aria-current={label === "任务" ? "page" : undefined} aria-label={label} onClick={action} title={label}>
            <Icon size={22} weight={label === "任务" ? "bold" : "regular"} /><span>{label}</span>
          </button>
        ))}
      </nav>
      <button className="ws-sync" onClick={demo.refresh} aria-label="刷新本地演示状态" title="刷新本地演示状态">
        <ArrowsClockwise size={18} /><span>最后同步{syncClock(demo.lastSync)} CST</span>
      </button>
    </aside>
  );
}

function TaskStatus({ task }: { task: DemoTask }) {
  const ready = task.status === "ready";
  const unresolved = task.status === "cancel_requested" || (!ready && task.id === ORIGINAL_TASK_ID);
  const text = ready ? "待启动" : task.status === "cancel_requested" ? "停止待确认" : unresolved ? "等待原操作核对" : "等待推进";
  return (
    <span className={`ws-task-status ${unresolved ? "is-waiting" : "is-ready"}`}>
      {unresolved ? <WarningCircle size={20} weight="fill" /> : <Clock size={20} />}<span>{text}</span>
    </span>
  );
}

function TaskTable({ demo, onSelect }: ViewProps & TaskSelection) {
  return (
    <div className="ws-table-wrap">
      <table className="ws-task-table" aria-label="项目任务">
        <colgroup><col className="ws-col-task" /><col className="ws-col-status" /><col className="ws-col-budget" /><col className="ws-col-time" /><col className="ws-col-arrow" /></colgroup>
        <thead><tr><th>任务</th><th>当前推进</th><th>预算上限</th><th>更新</th><th aria-label="选择任务" /></tr></thead>
        <tbody>
          {demo.visibleTasks.map((task) => (
            <tr key={task.id} className="ws-task-row" aria-selected={task.id === demo.selectedTask.id}
              tabIndex={0} onClick={() => onSelect(task.id)}
              onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onSelect(task.id); } }}>
              <td><span className="ws-task-name"><strong>{task.id}</strong><span>{task.title}</span></span></td>
              <td><TaskStatus task={task} /></td>
              <td className="ws-budget">¥{task.budget.toFixed(2)}</td>
              <td className="ws-updated">{task.updatedAt}</td>
              <td className="ws-row-arrow"><CaretRight size={20} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      {demo.visibleTasks.length === 0 && (
        <div className="ws-empty"><MagnifyingGlass size={28} /><strong>没有找到匹配的任务</strong><span>试试其他关键词，或查看全部任务。</span>
          <button onClick={() => { demo.setQuery(""); demo.setFilter("all"); }}>清除筛选</button>
        </div>
      )}
    </div>
  );
}

function TaskFilters({ demo }: ViewProps) {
  const filters: { key: TaskFilter; label: string; count: number }[] = [
    { key: "all", label: "全部", count: demo.tasks.length },
    { key: "ready", label: "待启动", count: demo.tasks.filter((task) => task.status === "ready").length },
    { key: "attention", label: "需要关注", count: demo.tasks.filter((task) => task.status !== "ready").length },
  ];
  return (
    <div className="ws-filters" role="group" aria-label="按任务状态筛选">
      {filters.map(({ key, label, count }) => (
        <button key={key} className={`ws-filter ${demo.filter === key ? "is-active" : ""}`}
          aria-pressed={demo.filter === key} onClick={() => demo.setFilter(key)}>
          {label}<span>{count}</span>
        </button>
      ))}
    </div>
  );
}

function TaskList({ demo, onSelect }: ViewProps & TaskSelection) {
  return (
    <main className="ws-main">
      <div className="ws-page-heading">
        <div><h1>便签服务</h1><p>任务与交付</p></div>
        <button className="ws-new-task" onClick={() => demo.openModal("create")}><PlusCircle size={19} weight="fill" />新建任务</button>
      </div>
      <label className="ws-search"><MagnifyingGlass size={22} /><input value={demo.query} onChange={(event) => demo.setQuery(event.target.value)} placeholder="搜索任务名称、ID 或相关内容..." aria-label="搜索任务名称、ID 或相关内容" /></label>
      <TaskFilters demo={demo} />
      <TaskTable demo={demo} onSelect={onSelect} />
    </main>
  );
}

function TaskAlert({ task }: { task: DemoTask }) {
  const isReady = task.status === "ready";
  const isCancelled = task.status === "cancel_requested";
  const isPending = task.status === "waiting" && task.id !== ORIGINAL_TASK_ID;
  const heading = isReady ? "任务已准备就绪" : isCancelled ? "物理停止待确认" : isPending ? "启动请求已接收" : "归档传输结果未知";
  const description = isReady ? "当前任务尚未启动，可提交本地演示请求。" : isCancelled ? "取消请求已接收，停止确认前资源继续保留。" : isPending ? "等待当前任务继续推进，接收不表示执行完成。" : "Op-218需要核对原操作，后续步骤尚未启动。";
  return (
    <div className={`ws-task-alert ${isReady || isPending ? "is-ready" : ""}`}>
      <strong>{isReady || isPending ? <Clock size={21} /> : <WarningCircle size={21} weight="fill" />}{heading}</strong>
      <p>{description}</p>
    </div>
  );
}

function PlanLink({ demo }: ViewProps) {
  return (
    <button className="ws-plan-link" onClick={() => demo.openModal("plan", demo.plan.id)}>
      <CalendarBlank size={20} weight="bold" />
      <span className="ws-plan-content"><span>{demo.plan.id} · Release {demo.plan.release} · {demo.plan.target}</span>
        <span className="ws-plan-tags"><span className={`ws-plan-approval ${demo.plan.approved ? "is-approved" : ""}`}><CheckCircle size={14} weight="fill" />{demo.plan.approved ? "已批准" : "待批准"}</span><span className="ws-plan-pending"><Clock size={14} weight="fill" />执行结果待核对</span></span>
      </span>
    </button>
  );
}

function CancellationSection({ demo }: ViewProps) {
  const [expanded, setExpanded] = useState(false);
  const requested = demo.selectedTask.status === "cancel_requested";
  const original = demo.selectedTask.id === ORIGINAL_TASK_ID;
  return (
    <section className="ws-cancellation">
      <button className="ws-section-toggle" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>
        <CaretDown size={19} /><strong>取消与停止</strong>
      </button>
      <p>{requested ? "取消请求已接收，物理停止待确认，资源继续保留。" : "取消请求需填写原因，停止确认前资源继续保留。"}</p>
      {expanded && <div className="ws-cancellation-actions"><button className="ws-cancel-button" disabled={requested} onClick={() => demo.openModal("cancel", demo.selectedTask.id)}>{requested ? "已申请取消" : "申请取消"}</button><button className="ws-text-button" onClick={() => original ? demo.openModal("operation", "Op-218") : demo.openModal("task", demo.selectedTask.id)}>{original ? "查看原操作" : "查看任务详情"}</button></div>}
    </section>
  );
}

function CurrentTask({ demo, onClose }: ViewProps & { onClose(): void }) {
  const task = demo.selectedTask;
  const ready = task.status === "ready";
  const original = task.id === ORIGINAL_TASK_ID;
  const openDetails = () => demo.openModal("task", task.id);
  const primaryAction = ready ? demo.startTask : original ? () => demo.openModal("operation", "Op-218") : openDetails;
  const receipt = ready ? "任务尚未启动，尚无执行回执。" : task.status === "cancel_requested" ? "取消请求已接收，物理停止尚未确认。" : original ? "请求已接收，任务尚未完成。" : "启动请求已接收，当前任务等待推进。";
  return (
    <aside className="ws-current" aria-label="当前任务">
      <div className="ws-current-heading"><h2>当前任务</h2><button className="ws-icon-button" onClick={onClose} aria-label="收起当前任务"><X size={19} /></button></div>
      <h3>{task.id}</h3><p className="ws-current-title">{task.title}</p>
      <TaskAlert task={task} />
      <div className="ws-current-actions">
        <button className="ws-primary-button" disabled={ready && !demo.connected} onClick={primaryAction}>{ready ? "启动任务" : original ? "查看核对详情" : "查看任务详情"}</button>
        <button className="ws-text-button" onClick={ready || original ? openDetails : demo.refresh}>{ready || original ? "查看任务详情" : "刷新任务"}</button>
      </div>
      <p className="ws-receipt"><ClipboardText size={20} /><span>{receipt}</span></p>
      {original && <PlanLink demo={demo} />}
      <CancellationSection key={task.id} demo={demo} />
    </aside>
  );
}

export default function WorkspaceView({ demo }: ViewProps) {
  const [detailsOpen, setDetailsOpen] = useState(true);
  const selectTask = (id: string) => { demo.selectTask(id); setDetailsOpen(true); };
  return (
    <div className="workspace-shell">
      <WorkspaceHeader demo={demo} />
      <div className="ws-body"><ProjectSidebar demo={demo} />
        <div className={`ws-workspace ${detailsOpen ? "" : "is-details-closed"}`}>
          <TaskList demo={demo} onSelect={selectTask} />
          {detailsOpen && <CurrentTask demo={demo} onClose={() => setDetailsOpen(false)} />}
        </div>
      </div>
    </div>
  );
}
