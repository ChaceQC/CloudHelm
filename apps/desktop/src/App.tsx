import { useEffect, useState } from "react";
import { ConnectionPanel } from "./ConnectionPanel";
import { ObjectPanel, kindNames } from "./ObjectPanel";
import { OperationPanel } from "./OperationPanel";
import { PlanPanel } from "./PlanPanel";
import { CreateTask, TaskPanel } from "./TaskPanel";
import { useHub } from "./useHub";
import { Empty, JsonView, Status } from "./ui";
import "./styles.css";

const navigation = [
  ["tasks", "任务", "01"], ["plans", "部署批准", "02"], ["delivery", "交付对象", "03"],
  ["operations", "原操作查询", "04"], ["events", "事件", "05"], ["connection", "连接", "06"],
];

export default function App() {
  const hub = useHub();
  const [page, setPage] = useState("tasks");
  const [taskId, setTask] = useState("");
  const [planId, setPlan] = useState("");
  const [objectId, setObject] = useState("");
  const [filter, setFilter] = useState("");
  const [creating, setCreating] = useState(false);
  const [projectInput, setProjectInput] = useState("");
  const snapshot = hub.snapshot;
  const tasks = snapshot?.tasks ?? [];
  const plans = snapshot?.objects.filter(item => item.kind === "plan") ?? [];
  const objects = snapshot?.objects.filter(item => item.kind !== "plan") ?? [];
  const selected = tasks.find(task => task.task_id === taskId) ?? tasks[0];
  const selectedPlan = plans.find(item => item.object_id === planId) ?? plans[0];
  const selectedObject = objects.find(item => item.object_id === objectId) ?? objects[0];
  useEffect(() => { setTask(""); setPlan(""); setObject(""); setCreating(false); }, [snapshot?.project.project_id]);
  useEffect(() => { if (!hub.writable) setCreating(false); }, [hub.writable]);
  const receiptBody = hub.receipt?.body;
  const commandResult = receiptBody && typeof receiptBody.task === "object" ? receiptBody.task as Record<string, unknown> : receiptBody;

  return <div className="workspace">
    <aside className="sidebar"><div className="brand"><span className="brand-mark">云</span><div>CloudHelm<small>工程工作台</small></div></div>
      <nav aria-label="工作台导航">{navigation.map(([key, title, number]) => <button key={key} aria-current={page === key ? "page" : undefined}
        onClick={() => setPage(key)}><span>{number}</span>{title}</button>)}</nav>
      <div className="sidebar-bottom"><Status value={hub.connection}/><span>{hub.identity?.display_name ?? "尚未连接 Hub"}</span>
        <button onClick={() => setPage("connection")}>管理连接</button></div>
    </aside>
    <main><header><div className="project-switch"><span className="eyebrow">项目</span>
      <select aria-label="当前项目" value={snapshot?.project.project_id ?? ""} disabled={!hub.identity}
        onChange={e => hub.selectProject(e.target.value)}>
        <option value="" disabled>选择项目</option>
        {hub.projects.map(project => <option key={project.project_id} value={project.project_id}>{project.name}</option>)}
        {snapshot && !hub.projects.some(p => p.project_id === snapshot.project.project_id)
          && <option value={snapshot.project.project_id}>{snapshot.project.name}</option>}
      </select></div>
      <form className="project-open" onSubmit={e => { e.preventDefault(); hub.selectProject(projectInput.trim()); }}>
        <input aria-label="按项目 ID 打开" value={projectInput} maxLength={160} onChange={e => setProjectInput(e.target.value)} placeholder="项目 ID"/>
        <button disabled={!hub.identity || !projectInput.trim()}>打开</button></form>
      <div className="header-status"><Status value={hub.connection}/><button disabled={!snapshot} onClick={() => { void hub.refresh(); }}>刷新</button></div>
    </header>
    <div className="content"><div className="page-heading"><div><span className="eyebrow">{snapshot?.project.name ?? "CLOUDHELM"}</span>
      <h1>{navigation.find(item => item[0] === page)?.[1]}</h1></div>
      {page === "tasks" && <button className="primary" disabled={!hub.can("task.command")} onClick={() => setCreating(true)}>＋ 提交任务</button>}</div>
      {hub.error && <div className="error" role="alert">{hub.error}</div>}
      {hub.connection === "offline" && <div className="notice">当前显示上次快照；重新连接并取得当前权限前暂停写入。</div>}
      {hub.connection === "revoked" && <div className="notice">授权范围已清理，请重新连接。</div>}
      {hub.pending.map(original => <div className="notice pending-command" key={original.idempotency_key}><div><strong>原命令结果待确认</strong>
        <code>{original.idempotency_key}</code><small>{original.route}</small></div>
        <button disabled={hub.connection !== "live" || hub.busy} onClick={() => hub.retry(original)}>使用原身份核对 / 重投</button></div>)}
      {hub.receipt && <section className="receipt"><div className="section-title"><span>HTTP {hub.receipt.status} · {String(commandResult?.code ?? "回执")}</span>
        <Status value={String(commandResult?.outcome ?? "received")}/></div>
        {hub.receipt.status === 202 && <p>已可靠接收，当前业务状态请查看任务与原操作。</p>}
        <JsonView value={hub.receipt.body} title="命令回执"/></section>}
      {page === "connection" ? <ConnectionPanel hub={hub}/>
        : !snapshot ? <Empty><p>{hub.identity ? "等待项目快照" : "连接 Hub 后打开项目"}</p><button className="primary" onClick={() => setPage("connection")}>连接设置</button></Empty>
        : page === "tasks" ? <>
          <div className="metrics"><div><strong>{tasks.length}</strong><span>任务</span></div>
            <div><strong>{tasks.filter(t => t.blockers.length).length}</strong><span>有阻塞</span></div>
            <div><strong>{plans.filter(p => !p.approved).length}</strong><span>待批准计划</span></div>
            <div><strong>{snapshot.cursor}</strong><span>快照游标</span></div></div>
          <div className="split"><section className="object-list"><div className="list-toolbar"><input aria-label="搜索任务" value={filter} onChange={e => setFilter(e.target.value)} placeholder="搜索任务或 ID"/></div>
            {tasks.filter(t => `${t.task_id} ${t.declaration.title}`.toLowerCase().includes(filter.toLowerCase())).map(task =>
              <button className={`object-row ${selected?.task_id === task.task_id ? "selected" : ""}`} key={task.task_id} onClick={() => setTask(task.task_id)}>
                <span className="row-title">{task.declaration.title}<Status value={task.state}/></span><code>{task.task_id}</code>
                <span className="muted">{task.blockers[0]?.code ?? `输入 r${task.input_validity_revision}`}</span></button>)}
            {!tasks.length && <Empty>暂无任务</Empty>}</section><TaskPanel key={selected?.task_id} hub={hub} task={selected}/></div>
        </> : page === "plans" ? <div className="split"><section className="object-list">{plans.map(plan =>
          <button className={`object-row ${selectedPlan?.object_id === plan.object_id ? "selected" : ""}`} key={plan.object_id} onClick={() => setPlan(plan.object_id)}>
            <span className="row-title"><Status value={plan.approved ? "awaiting_remote_agent" : "approval_pending"}/></span>
            <code>{plan.object_id}</code><span>{plan.target_id}</span><code>{plan.operation_id}</code></button>)}
          {!plans.length && <Empty>暂无部署计划</Empty>}</section><PlanPanel hub={hub} planId={selectedPlan?.object_id ?? ""}/></div>
        : page === "delivery" ? <div className="split"><section className="object-list">{objects.map(object =>
          <button className={`object-row ${selectedObject?.object_id === object.object_id ? "selected" : ""}`} key={object.object_id} onClick={() => setObject(object.object_id)}>
            <span className="row-title">{kindNames[object.kind]}</span><code>{object.object_id}</code><span className="muted">{object.target_id ?? `r${object.revision}`}</span></button>)}</section>
          <ObjectPanel hub={hub} object={selectedObject}/></div>
        : page === "operations" ? <OperationPanel key={snapshot.project.project_id} hub={hub} taskId={selected?.task_id ?? ""}/>
        : <section className="card"><div className="section-title"><h2>业务事件</h2><span className="muted">游标 {snapshot.cursor} · 最近 {hub.events.length} 条</span></div>
          {hub.events.map(event => <div className="event" key={event.event_id}><span className="event-cursor">{event.cursor}</span><strong>{event.event_type}</strong>
            <code>{event.aggregate_kind} / {event.aggregate_id}</code><span>v{event.aggregate_version}</span></div>)}
          {!hub.events.length && <Empty>当前快照之后暂无新事件</Empty>}<JsonView value={{ stream_id: snapshot.stream_id,
            captured_at: snapshot.captured_at, tombstones: snapshot.tombstones }} title="同步位置"/></section>}
    </div><footer><span>{snapshot ? `快照 ${snapshot.captured_at}` : "Windows Desktop"}</span><span>CloudHelm 0.8.0</span></footer></main>
    {creating && <CreateTask hub={hub} close={() => setCreating(false)}/>}
  </div>;
}
