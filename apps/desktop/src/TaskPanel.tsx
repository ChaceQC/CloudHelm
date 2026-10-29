import { useState } from "react";
import { AgentPanel } from "./AgentPanel";
import { HumanTestPanel } from "./HumanTestPanel";
import { bodyOf, codeOf, objectPath, taskPath } from "./api";
import type { Hub } from "./useHub";
import type { Task } from "./types";
import { Empty, Facts, JsonView, Status } from "./ui";

export function CreateTask({ hub, close }: { hub: Hub; close: () => void }) {
  const [mode, setMode] = useState("reference");
  const [error, setError] = useState("");
  const project = hub.snapshot?.project;
  if (!project) return null;
  return <div className="modal-backdrop"><form className="modal" onSubmit={e => {
    e.preventDefault(); setError("");
    const form = new FormData(e.currentTarget);
    try {
      const body = mode === "reference" ? {
        expected_project_revision: project.revision, source_operation_id: String(form.get("source")),
        title: String(form.get("title")), goal: String(form.get("goal")),
        budget: { amount: String(form.get("budget")), currency: String(form.get("currency")) },
      } : { expected_project_revision: project.revision, declaration: bodyOf(JSON.parse(String(form.get("declaration")))) };
      hub.command(objectPath(project.project_id, mode === "reference" ? "reference-tasks" : "tasks", "").replace(/\/$/, ""), body);
      close();
    } catch (reason) { setError(codeOf(reason)); }
  }}>
    <div className="section-title"><h2>提交任务</h2><button type="button" onClick={close}>关闭</button></div>
    <label>输入方式<select value={mode} onChange={e => setMode(e.target.value)}><option value="reference">已登记的参照源码</option><option value="declaration">完整 Task 声明</option></select></label>
    {mode === "reference" ? <>
      <label>已完成的源码导入 Operation ID<input name="source" required maxLength={160}/></label>
      <label>任务标题<input name="title" required maxLength={160}/></label>
      <label>目标<textarea name="goal" required maxLength={4096} rows={4}/></label>
      <div className="form-row"><label>预算上限<input name="budget" defaultValue="1" required pattern="(0|[1-9][0-9]{0,15})(\.[0-9]{1,8})?"/></label>
        <label>币种<select name="currency"><option>USD</option><option>CNY</option></select></label></div>
    </> : <label>TaskDeclaration JSON<textarea name="declaration" required rows={12} placeholder="使用已登记的 requirement、acceptance_assets、source 和 policy 引用"/></label>}
    {error && <p className="error">{error}</p>}
    <button className="primary" disabled={!hub.can("task.command")}>提交</button>
  </form></div>;
}

export function TaskPanel({ hub, task }: { hub: Hub; task?: Task }) {
  const [reason, setReason] = useState("");
  if (!task) return <Empty>选择任务查看详情</Empty>;
  const version = { expected_version: task.version, expected_control_revision: task.control_revision,
    expected_input_validity_revision: task.input_validity_revision };
  const closed = task.ordinary_progress_closed || !!task.cancellation;
  return <article className="detail">
    <div className="section-title"><h2>{task.declaration.title}</h2><Status value={task.state}/></div>
    <p>{task.declaration.goal}</p>
    <Facts values={{ "Task": task.task_id, "业务版本": task.version, "控制修订": task.control_revision,
      "输入": `${task.input_status} · r${task.input_validity_revision}`, "预算上限": `${task.declaration.budget.amount} ${task.declaration.budget.currency}` }}/>
    <div className="actions"><button className="primary" disabled={!hub.can("task.command") || closed || task.state !== "draft"}
      onClick={() => hub.command(`${taskPath(task.task_id)}/start`, version)}>启动任务</button>
      <button onClick={() => { void hub.refresh(); }} disabled={!hub.identity}>查询当前事实</button>
      <button disabled={!hub.can(task.cancellation ? "task.cancel" : "task.command")}
        onClick={() => hub.command(`${taskPath(task.task_id)}/reconcile`, {
          expected_version: task.version, expected_control_revision: task.control_revision,
          purpose: task.cancellation ? "cancellation" : "completion",
        })}>核对控制事实</button></div>
    {!!task.blockers.length && <section><h3>阻塞对象</h3>{task.blockers.map((blocker, i) =>
      <div className="blocker" key={i}><strong>{blocker.code}</strong><code>{blocker.object_kind} · {blocker.object_id ?? task.task_id}</code></div>)}</section>}
    {task.work_items.length > 0 && <section><h3>工作项</h3>{task.work_items.map(item =>
      <div className="work-item" key={item.work_item_id}><Status value={item.state}/><span>{item.goal}</span></div>)}</section>}
    {task.cancellation && <div className="notice">取消已请求；停止与冲突占用以服务端核对事实为准。<JsonView value={task.cancellation} title="取消事实"/></div>}
    {task.completion_report_id && <Facts values={{ "完成报告": task.completion_report_id }}/>}
    <AgentPanel hub={hub} task={task}/>
    <HumanTestPanel hub={hub} task={task}/>
    {!task.ordinary_progress_closed && <form className="cancel" onSubmit={e => {
      e.preventDefault(); hub.command(`${taskPath(task.task_id)}/cancel`, {
        expected_version: task.version, expected_control_revision: task.control_revision, cancel_reason: reason.trim(),
      });
    }}><h3>请求取消</h3><div className="form-row"><input aria-label="取消原因" value={reason} maxLength={160}
      onChange={e => setReason(e.target.value)} placeholder="填写取消原因" required/>
      <button className="danger" disabled={!hub.can("task.cancel") || !reason.trim() || !!task.cancellation}>请求取消</button></div></form>}
    <JsonView value={task} title="Task 与输入事实"/>
  </article>;
}
