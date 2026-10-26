import { useEffect, useId, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { ArrowRight, CheckCircle, Info, MagnifyingGlass, Play, Plug, WarningCircle, X } from "@phosphor-icons/react";
import type { DemoController, DemoTask, ModalKind } from "./contracts";
import "./dialogs.css";

const STATUS = { ready: "可启动", waiting: "等待处理", cancel_requested: "取消请求已接收" };
const TITLES: Record<ModalKind, string> = {
  create: "创建任务", connection: "连接与身份", task: "任务详情", operation: "原操作核对",
  plan: "部署计划", digest: "计划摘要", input: "输入与引用", cancel: "请求取消任务",
};

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <div className="demo-field"><span className="demo-field-label">{label}</span><div>{children}</div></div>;
}

function TaskDetails({ demo }: { demo: DemoController }) {
  const task = demo.selectedTask;
  return <>
    <div className="demo-task-switch" aria-label="选择任务">
      {demo.tasks.map((item) => <button key={item.id} type="button" aria-pressed={item.id === task.id}
        onClick={() => demo.selectTask(item.id)}>{item.id}</button>)}
    </div>
    <div className="demo-detail-title"><span>{task.id}</span><h3>{task.title}</h3></div>
    <div className="demo-field-grid">
      <Field label="任务状态"><span className={`demo-state ${task.status}`}>{STATUS[task.status]}</span></Field>
      <Field label="预算">¥ {task.budget.toFixed(2)}</Field>
      <Field label="最近更新">{task.updatedAt} CST</Field><Field label="当前计划">{demo.plan.id}</Field>
    </div>
    <Field label="任务目标"><p className="demo-long-text">{task.goal}</p></Field>
    {task.status === "waiting" && <div className="demo-callout"><WarningCircle size={20} />
      <div><strong>启动请求已接收</strong><p>当前等待执行结果，接收不等于任务完成。</p></div></div>}
    {task.status === "cancel_requested" && <div className="demo-callout"><WarningCircle size={20} />
      <div><strong>物理停止待确认，资源继续保留</strong><p>取消原因：{task.cancelReason}</p></div></div>}
    <div className="demo-actions">
      <button className="demo-button" type="button" onClick={() => demo.openModal("input", task.id)}>查看输入与引用</button>
      {task.status === "ready" && <button className="demo-button primary" type="button" disabled={!demo.connected}
        onClick={demo.startTask}><Play size={16} weight="fill" />启动任务</button>}
      {task.status === "waiting" && task.id === "TASK-1042" && <button className="demo-button primary" type="button"
        onClick={() => demo.openModal("operation", "Op-218")}><MagnifyingGlass size={17} />查询原操作</button>}
      {task.status === "waiting" && task.id !== "TASK-1042" && <button className="demo-button primary" type="button"
        onClick={demo.refresh}>刷新任务快照</button>}
      {task.status !== "cancel_requested" && <button className="demo-button danger" type="button" disabled={!demo.connected}
        onClick={() => demo.openModal("cancel", task.id)}>请求取消</button>}
    </div>
  </>;
}

function PlanDetails({ demo }: { demo: DemoController }) {
  const plan = demo.plan;
  return <>
    <div className="demo-detail-title"><span>{plan.id}</span><h3>{plan.environment}</h3>
      <span className="demo-approved"><CheckCircle size={16} weight="fill" />{plan.approved ? "已批准" : "待批准"}</span></div>
    <div className="demo-field-grid">
      <Field label="Release">{plan.currentRelease}<ArrowRight size={15} />{plan.release}</Field>
      <Field label="配置修订">r{plan.configFrom}<ArrowRight size={15} />r{plan.configTo}</Field>
      <Field label="目标环境">{plan.target}</Field><Field label="许可截止">{plan.expiresAt}</Field>
      <Field label="最近核对">{demo.checkedAt} CST</Field><Field label="批准记录">{demo.approvedAt} CST</Field>
    </div>
    <Field label="计划摘要 · SHA-256"><code className="demo-digest">{plan.digest}</code></Field>
    <div className="demo-callout"><WarningCircle size={20} /><div><strong>批准记录与执行结果分别保存</strong>
      <p>Op-218 的结果仍为 unknown；后续步骤尚未启动，物理停止待确认，资源继续保留。</p></div></div>
    <label className="demo-checkbox"><input type="checkbox" checked={demo.approvalConfirmed}
      onChange={(event) => demo.setApprovalConfirmed(event.target.checked)} />
      <span>我已核对计划摘要、目标环境与配置修订。</span></label>
    <div className="demo-actions"><button type="button" className="demo-button" disabled={!demo.connected} onClick={demo.checkPlan}>重新核对</button>
      <button type="button" className="demo-button primary" disabled={!demo.connected || !demo.approvalConfirmed}
        onClick={demo.approvePlan}>{plan.approved ? "确认批准记录" : "批准计划"}</button></div>
  </>;
}

function OperationDetails({ demo }: { demo: DemoController }) {
  return <>
    <div className="demo-detail-title"><span>Op-218</span><h3>核对原交付操作</h3><span className="demo-state waiting">unknown</span></div>
    <p className="demo-long-text">继续使用原操作身份查询与核对。当前没有可靠结果，不能据此重放或把它记为失败。</p>
    <div className="demo-operation-facts">
      <Field label="绑定任务">TASK-1042 · 验证构建与交付</Field><Field label="绑定计划">{demo.plan.id}</Field>
      <Field label="操作结果"><strong>unknown · 结果待核对</strong></Field>
      <Field label="后续步骤">尚未启动</Field><Field label="物理执行">停止待确认</Field><Field label="冲突资源">继续保留</Field>
    </div>
    <div className="demo-callout"><WarningCircle size={20} /><div><strong>原操作结果尚未明确</strong>
      <p>取消请求、等待结束或重新连接，都不会自动确认物理停止，也不会释放资源。</p></div></div>
    <div className="demo-actions"><button type="button" className="demo-button" onClick={() => demo.openModal("plan", demo.plan.id)}>查看绑定计划</button>
      <button type="button" className="demo-button primary" onClick={demo.refresh}><MagnifyingGlass size={17} />按原身份查询</button></div>
  </>;
}

function DigestDetails({ demo, project }: { demo: DemoController; project: boolean }) {
  return <>
    {project && <><div className="demo-detail-title"><span>CloudHelm</span><h3>云舵工程工作台</h3></div>
      <p className="demo-long-text">将任务目标、固定输入、部署计划与原操作事实放在同一个工作区中核对。</p>
      <div className="demo-field-grid"><Field label="任务数量">{demo.tasks.length} 项</Field>
        <Field label="当前任务">{demo.selectedTask.id}</Field><Field label="目标环境">{demo.plan.target}</Field>
        <Field label="当前计划">{demo.plan.id}</Field></div></>}
    <Field label="完整计划摘要 · SHA-256"><code className="demo-digest">{demo.plan.digest}</code></Field>
    <Field label="固定变化">Release {demo.plan.currentRelease} → {demo.plan.release}；配置 r{demo.plan.configFrom} → r{demo.plan.configTo}</Field>
    <Field label="摘要绑定">{demo.plan.id} · {demo.plan.environment} · {demo.plan.target}</Field>
    <Field label="许可截止">{demo.plan.expiresAt}</Field>
    <div className="demo-actions"><button type="button" className="demo-button primary" onClick={() => demo.openModal("plan", demo.plan.id)}>查看完整计划<ArrowRight size={17} /></button></div>
  </>;
}

function InputDetails({ task }: { task: DemoTask }) {
  return <>
    <p className="demo-long-text">{task.id} 的固定输入。引用保留来源与修订，后续核对沿用同一输入身份。</p>
    <div className="demo-reference-list">
      <article><span className="demo-reference-kind">来源</span><h3>SRC-021</h3><p>交付验证需求记录</p><small>固定来源 · 2026-10-26 09:30 CST</small></article>
      <article><span className="demo-reference-kind">需求</span><h3>REQ-014 <span>r3</span></h3><p>核对 Release、环境配置修订及目标起始状态。</p><small>引用来源 SRC-021</small></article>
      <article><span className="demo-reference-kind">验收</span><h3>ACC-014 <span>r2</span></h3><p>保留原操作结果；物理停止未知时保留资源并阻止冲突推进。</p><small>关联需求 REQ-014 r3</small></article>
    </div>
  </>;
}

export default function DemoDialogs({ demo }: { demo: DemoController }) {
  const prefix = useId();
  const dialogRef = useRef<HTMLElement>(null);
  const [title, setTitle] = useState("");
  const [goal, setGoal] = useState("");
  const [budget, setBudget] = useState("12.00");
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const modalKey = demo.modal ? `${demo.modal.kind}:${demo.modal.reference ?? ""}` : "";
  const isOpen = Boolean(demo.modal);

  useEffect(() => {
    setTitle(""); setGoal(""); setBudget("12.00"); setReason(""); setError("");
  }, [modalKey]);

  useEffect(() => {
    if (!isOpen) return;
    const previouslyFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const focusable = () => Array.from(dialogRef.current?.querySelectorAll<HTMLElement>(
      'button:not(:disabled), input:not(:disabled), textarea:not(:disabled), select:not(:disabled), [tabindex="0"]',
    ) ?? []).filter((element) => element.getClientRects().length > 0);
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); demo.closeModal(); }
      if (event.key !== "Tab") return;
      const elements = focusable();
      const first = elements[0];
      const last = elements[elements.length - 1];
      if (!first || !last) { event.preventDefault(); dialogRef.current?.focus(); return; }
      const active = document.activeElement;
      if (event.shiftKey && (active === first || !elements.includes(active as HTMLElement))) {
        event.preventDefault(); last.focus();
      } else if (!event.shiftKey && (active === last || !elements.includes(active as HTMLElement))) {
        event.preventDefault(); first.focus();
      }
    };
    const keepFocus = (event: FocusEvent) => {
      if (event.target instanceof Node && !dialogRef.current?.contains(event.target)) {
        (focusable()[0] ?? dialogRef.current)?.focus();
      }
    };
    document.addEventListener("keydown", handleKey);
    document.addEventListener("focusin", keepFocus);
    return () => {
      document.removeEventListener("keydown", handleKey);
      document.removeEventListener("focusin", keepFocus);
      document.body.style.overflow = previousOverflow;
      if (previouslyFocused?.isConnected) previouslyFocused.focus();
    };
  }, [isOpen, demo.closeModal]);

  useEffect(() => {
    if (!isOpen) return;
    const target = dialogRef.current?.querySelector<HTMLElement>("[data-primary-focus]")
      ?? dialogRef.current?.querySelector<HTMLElement>("[data-dialog-heading]");
    target?.focus();
  }, [modalKey, isOpen]);

  const modal = demo.modal;
  const submitCreate = (event: FormEvent) => {
    event.preventDefault();
    const amount = Number(budget);
    if (!title.trim() || !goal.trim() || !Number.isFinite(amount) || amount <= 0) {
      setError("请填写任务名称和目标，预算需大于 0。"); return;
    }
    if (!demo.createTask({ title, goal, budget: amount })) setError("当前无法创建任务，请检查连接状态与输入。");
  };
  const submitCancel = (event: FormEvent) => {
    event.preventDefault();
    if (!reason.trim()) { setError("请填写取消原因。"); return; }
    if (!demo.cancelTask(reason)) setError("当前无法提交取消请求，请检查连接状态。");
  };

  return <>
    {demo.notice && <div className="demo-notice" role="status"><Info size={20} />
      <p>{demo.notice}</p><button type="button" aria-label="关闭通知" onClick={demo.dismissNotice}><X size={17} /></button></div>}
    {modal && <div className="demo-overlay" onClick={(event) => { if (event.target === event.currentTarget) demo.closeModal(); }}>
      <section className="demo-dialog" ref={dialogRef} role="dialog" aria-modal="true" tabIndex={-1}
        aria-labelledby={`${prefix}-heading`} aria-describedby={`${prefix}-subtitle`}>
        <header className="demo-dialog-header"><div><p id={`${prefix}-subtitle`}>CLOUDHELM WORKSPACE</p>
          <h2 id={`${prefix}-heading`} data-dialog-heading tabIndex={-1}>{modal.kind === "digest" && modal.reference === "project" ? "项目概览" : TITLES[modal.kind]}</h2></div>
          <button type="button" className="demo-close" aria-label="关闭对话框" onClick={demo.closeModal}><X size={21} /></button></header>
        <div className="demo-dialog-body">
          {!demo.connected && modal.kind !== "connection" && <p className="demo-offline"><Plug size={16} />离线快照 · 写操作暂不可用</p>}
          {modal.kind === "create" && <form className="demo-form" onSubmit={submitCreate}>
            <label htmlFor={`${prefix}-title`}>任务名称</label><input id={`${prefix}-title`} value={title} data-primary-focus
              onChange={(event) => setTitle(event.target.value)} placeholder="例如：核对交付输入" required maxLength={100} />
            <label htmlFor={`${prefix}-goal`}>任务目标</label><textarea id={`${prefix}-goal`} value={goal}
              onChange={(event) => setGoal(event.target.value)} placeholder="描述这项任务需要完成的目标与范围" rows={4} required maxLength={1500} />
            <label htmlFor={`${prefix}-budget`}>预算（元）</label><input id={`${prefix}-budget`} type="number" min="0.01" step="0.01" value={budget}
              onChange={(event) => setBudget(event.target.value)} required inputMode="decimal" />
            {error && <p className="demo-form-error" role="alert">{error}</p>}
            <p className="demo-form-hint">创建后为“可启动”，启动前仍可核对任务与固定输入。</p>
            <div className="demo-actions"><button type="button" className="demo-button" onClick={demo.closeModal}>返回</button>
              <button type="submit" className="demo-button primary" disabled={!demo.connected}>创建任务</button></div>
          </form>}
          {modal.kind === "connection" && <>
            <div className={`demo-connection ${demo.connected ? "online" : "offline"}`}><Plug size={25} /><div>
              <strong>{demo.connected ? "已连接" : "离线快照"}</strong><p>最近同步 {demo.lastSync}</p></div></div>
            <div className="demo-form"><label htmlFor={`${prefix}-address`}>Hub 地址（演示）</label>
              <input id={`${prefix}-address`} value="https://hub.cloudhelm.example" readOnly />
              <Field label="当前身份">本地演示用户</Field><Field label="工作区">CloudHelm · 工程工作台</Field></div>
            <p className="demo-long-text">离线时保留任务与原操作快照，创建、启动、取消、核对和批准暂不可用。恢复连接后继续使用原身份。</p>
            <div className="demo-actions"><button type="button" className="demo-button" onClick={demo.refresh}>刷新快照</button>
              <button type="button" className="demo-button primary" onClick={demo.toggleConnection}>{demo.connected ? "模拟断开" : "模拟重连"}</button></div>
          </>}
          {modal.kind === "task" && <TaskDetails demo={demo} />}
          {modal.kind === "operation" && <OperationDetails demo={demo} />}
          {modal.kind === "plan" && <PlanDetails demo={demo} />}
          {modal.kind === "digest" && <DigestDetails demo={demo} project={modal.reference === "project"} />}
          {modal.kind === "input" && <InputDetails task={demo.selectedTask} />}
          {modal.kind === "cancel" && <form className="demo-form" onSubmit={submitCancel}>
            <div className="demo-detail-title"><span>{demo.selectedTask.id}</span><h3>{demo.selectedTask.title}</h3></div>
            <div className="demo-callout"><WarningCircle size={20} /><div><strong>提交取消意图，等待停止确认</strong>
              <p>原操作未确认停止前，保留冲突资源，不重放操作或启动冲突步骤。</p></div></div>
            <label htmlFor={`${prefix}-reason`}>取消原因</label><textarea id={`${prefix}-reason`} value={reason} data-primary-focus
              onChange={(event) => setReason(event.target.value)} placeholder="请说明为什么需要取消此任务" rows={4} required maxLength={1000} />
            {error && <p className="demo-form-error" role="alert">{error}</p>}
            <div className="demo-actions"><button type="button" className="demo-button" onClick={demo.closeModal}>继续保留任务</button>
              <button type="submit" className="demo-button danger solid" disabled={!demo.connected}>提交取消请求</button></div>
          </form>}
        </div>
      </section>
    </div>}
  </>;
}
