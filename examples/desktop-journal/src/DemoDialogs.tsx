import { useEffect, useId, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { ArrowClockwise, CheckCircle, WarningCircle, X } from "@phosphor-icons/react";
import type { DemoController, ModalKind, TaskStatus } from "./contracts";
import "./dialogs.css";

const headings: Record<ModalKind, [string, string]> = {
  create: ["新建任务", "写下目标，为下一步保留清晰的起点。"],
  connection: ["连接设置", "管理此份手记的连接状态。"],
  task: ["任务索引", "选择任务，查看目标、预算和当前事实。"],
  operation: ["原操作核对", "沿用同一操作身份，先确认已经发生的事实。"],
  plan: ["完整交付计划", "固定输入、目标差异与批准事实一并保留。"],
  digest: ["计划摘要", "批准所绑定的完整 SHA-256 摘要。"],
  input: ["引用输入", "每项引用保留自己的身份与修订。"],
  cancel: ["请求取消任务", "记录原因，并等待执行器确认物理停止。"],
};
const statusText: Record<TaskStatus, string> = {
  ready: "待启动", waiting: "等待中", cancel_requested: "已请求取消",
};
const references = [
  { id: "SRC-021", title: "便签服务来源", revision: "固定来源快照", detail: "作为构建与交付的来源输入，与 TASK-1042 绑定；本页保留其固定引用。" },
  { id: "REQ-014", title: "构建与交付需求", revision: "r3", detail: "固定需求修订，用于核对便签服务的构建目标与交付范围。" },
  { id: "ACC-014", title: "独立验收说明", revision: "r2", detail: "固定验收说明修订。引用存在与实际验证通过分别记录，不能相互替代。" },
];

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return <div className="jd-fact"><dt>{label}</dt><dd>{children}</dd></div>;
}

function OfflineHint({ connected }: { connected: boolean }) {
  return connected ? null : <p className="jd-warning"><WarningCircle size={18} />当前离线，可阅读快照；恢复连接后才能提交操作。</p>;
}

function CreateTaskForm({ demo }: { demo: DemoController }) {
  const id = useId();
  const [errors, setErrors] = useState<Record<string, string>>({});
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const title = String(data.get("title") ?? "").trim();
    const goal = String(data.get("goal") ?? "").trim();
    const budget = Number(data.get("budget"));
    const next: Record<string, string> = {};
    if (!title) next.title = "请填写任务名称。";
    if (!goal) next.goal = "请填写本次任务要达成的目标。";
    if (!Number.isFinite(budget) || budget <= 0) next.budget = "预算须为大于 0 的金额。";
    setErrors(next);
    const firstError = Object.keys(next)[0];
    if (firstError) {
      const field = event.currentTarget.elements.namedItem(firstError);
      if (field instanceof HTMLElement) field.focus();
      return;
    }
    demo.createTask({ title, goal, budget });
  }
  return <form className="jd-form" noValidate onSubmit={submit} onChange={() => setErrors({})}>
    <OfflineHint connected={demo.connected} />
    <div className="jd-field">
      <label htmlFor={`${id}-title`}>任务名称 <span>必填</span></label>
      <input id={`${id}-title`} name="title" required placeholder="例如：验证便签服务的交付" data-dialog-autofocus="true" aria-invalid={Boolean(errors.title)} aria-describedby={errors.title ? `${id}-title-error` : undefined} />
      {errors.title && <p id={`${id}-title-error`} className="jd-error" role="alert">{errors.title}</p>}
    </div>
    <div className="jd-field">
      <label htmlFor={`${id}-goal`}>任务目标 <span>必填</span></label>
      <textarea id={`${id}-goal`} name="goal" rows={4} required placeholder="写下预期结果，以及需要保留的证据。" aria-invalid={Boolean(errors.goal)} aria-describedby={errors.goal ? `${id}-goal-error` : undefined} />
      {errors.goal && <p id={`${id}-goal-error`} className="jd-error" role="alert">{errors.goal}</p>}
    </div>
    <div className="jd-field jd-field--budget">
      <label htmlFor={`${id}-budget`}>预算（元） <span>必填</span></label>
      <input id={`${id}-budget`} name="budget" type="number" min="0.01" step="any" required inputMode="decimal" defaultValue="12" aria-invalid={Boolean(errors.budget)} aria-describedby={errors.budget ? `${id}-budget-error` : undefined} />
      {errors.budget && <p id={`${id}-budget-error`} className="jd-error" role="alert">{errors.budget}</p>}
    </div>
    <div className="jd-actions"><span>创建后为待启动状态。</span><button className="jd-button" type="submit" disabled={!demo.connected}>创建任务</button></div>
  </form>;
}

function ConnectionDetails({ demo }: { demo: DemoController }) {
  const id = useId();
  return <div className="jd-stack">
    <div className={`jd-connection ${demo.connected ? "is-connected" : ""}`}><span className="jd-connection-dot" /><div><strong>{demo.connected ? "已连接" : "离线"}</strong><p>最近同步 {demo.lastSync}</p></div></div>
    <div className="jd-field"><label htmlFor={id}>演示 Hub 地址</label><input id={id} value="https://hub.cloudhelm.local" readOnly data-dialog-autofocus="true" /></div>
    <p className="jd-muted">地址仅作展示，不读取或保存凭据。切换连接状态会同步影响本地操作门禁。</p>
    <p className="jd-note">断开后仍可查看已有任务与证据。恢复连接沿用原任务及 Op-218，不自动重放未知操作。</p>
    <div className="jd-actions"><span>{demo.connected ? "写操作当前可用" : "写操作已暂停"}</span><button type="button" className={demo.connected ? "jd-button jd-button--quiet" : "jd-button"} onClick={demo.toggleConnection}>{demo.connected ? "模拟断开连接" : "恢复连接"}</button></div>
  </div>;
}

function TaskDetails({ demo }: { demo: DemoController }) {
  const task = demo.selectedTask;
  return <div className="jd-task-layout">
    <nav className="jd-task-list" aria-label="本地任务列表">{demo.tasks.map((item) => <button type="button" key={item.id} className={`jd-task-choice ${item.id === task.id ? "is-selected" : ""}`} aria-pressed={item.id === task.id} onClick={() => demo.selectTask(item.id)}><span>{item.id}</span><strong>{item.title}</strong><small>{statusText[item.status]}</small></button>)}</nav>
    <div className="jd-stack jd-task-detail">
      <div><span className="jd-kicker">{task.id}</span><h3>{task.title}</h3><span className={`jd-status jd-status--${task.status}`}>{statusText[task.status]}</span></div>
      <p className="jd-task-goal">{task.goal}</p>
      <dl className="jd-facts"><Fact label="预算">¥ {task.budget.toFixed(2)}</Fact><Fact label="最近更新">{task.updatedAt} CST</Fact></dl>
      {task.status === "waiting" && <p className="jd-note">正在等待可复核的事实。请求被接收不代表任务已经完成。</p>}
      {task.status === "cancel_requested" && <div className="jd-note"><strong>停止待确认 · 资源保留</strong><p>取消原因：{task.cancelReason}</p><p>不释放冲突资源，不重新启动原操作。</p></div>}
      <OfflineHint connected={demo.connected} />
      <div className="jd-task-actions"><button type="button" className="jd-button" onClick={demo.startTask} disabled={!demo.connected || task.status !== "ready"}>启动任务</button><button type="button" className="jd-button jd-button--quiet" onClick={() => demo.openModal("cancel", task.id)} disabled={!demo.connected || task.status === "cancel_requested"}>请求取消</button></div>
    </div>
  </div>;
}

function OperationDetails({ demo }: { demo: DemoController }) {
  return <div className="jd-stack">
    <div className="jd-operation-heading"><div><span className="jd-kicker">OPERATION</span><h3>Op-218 · 归档传输</h3></div><span className="jd-status jd-status--unknown">unknown</span></div>
    <p className="jd-note">归档传输的结果未知。先查询 Op-218 的原结果，不生成第二个操作，不把未知改写为失败或成功。</p>
    <dl className="jd-facts"><Fact label="任务身份">TASK-1042</Fact><Fact label="计划身份">{demo.plan.id}</Fact><Fact label="当前结果">未知 · 待原身份核对</Fact><Fact label="资源占用">继续保留</Fact></dl>
    <ol className="jd-operation-steps">{["归档传输", "镜像加载", "数据库迁移", "服务切换", "健康窗口"].map((step, index) => <li key={step}><span className="jd-step-index">{String(index + 1).padStart(2, "0")}</span><strong>{step}</strong><span className={index === 0 ? "jd-unknown-text" : ""}>{index === 0 ? "unknown · 待核对" : "未启动"}</span></li>)}</ol>
    <div className="jd-actions"><span>后续步骤保持未启动。</span><button type="button" className="jd-button" onClick={demo.refresh} data-dialog-autofocus="true"><ArrowClockwise size={17} />查询原操作</button></div>
  </div>;
}

function PlanDetails({ demo }: { demo: DemoController }) {
  const { plan } = demo;
  return <div className="jd-stack">
    <div className="jd-operation-heading"><div><span className="jd-kicker">DEPLOYMENT PLAN</span><h3>{plan.id}</h3></div><span className="jd-status">{plan.approved ? "已批准" : "待批准"}</span></div>
    <dl className="jd-facts jd-facts--two">
      <Fact label="Release">v{plan.currentRelease} → v{plan.release}</Fact><Fact label="环境配置">r{plan.configFrom} → r{plan.configTo}</Fact>
      <Fact label="目标">{plan.target}</Fact><Fact label="环境">{plan.environment}</Fact>
      <Fact label="最近核对">{demo.checkedAt} CST</Fact><Fact label="计划到期">{plan.expiresAt}</Fact>
    </dl>
    <div className="jd-plan-inputs"><h4>固定输入</h4>{references.map((reference) => <button type="button" key={reference.id} onClick={() => demo.openModal("input", reference.id)}><span>{reference.id}</span>{reference.title}<small>{reference.revision}</small></button>)}</div>
    <div className="jd-digest-block"><h4>批准绑定的完整摘要</h4><code>{plan.digest}</code><button type="button" className="jd-text-button" onClick={() => demo.openModal("digest")}>单独查看摘要 ↗</button></div>
    <ol className="jd-plan-stages">
      <li><CheckCircle size={18} /><div><strong>输入固定</strong><span>来源、需求与验收修订已绑定。</span></div></li>
      <li><CheckCircle size={18} /><div><strong>启动前核对</strong><span>{demo.checkedAt} CST · 本地计划快照</span></div></li>
      <li><CheckCircle size={18} /><div><strong>摘要批准</strong><span>{plan.approved ? `${demo.approvedAt} CST · 已记录显式批准` : "等待显式确认"}</span></div></li>
      <li><WarningCircle size={18} /><div><strong>原操作核对</strong><span>Op-218 归档传输 unknown，后续未启动。</span></div></li>
    </ol>
    <label className="jd-confirmation"><input type="checkbox" checked={plan.approved || demo.approvalConfirmed} disabled={plan.approved || !demo.connected} onChange={(event) => demo.setApprovalConfirmed(event.target.checked)} /><span>已核对目标、配置和完整计划摘要。</span></label>
    <OfflineHint connected={demo.connected} />
    <div className="jd-task-actions"><button type="button" className="jd-button jd-button--quiet" disabled={!demo.connected} onClick={demo.checkPlan}>重新核对计划</button><button type="button" className="jd-button" disabled={!demo.connected || plan.approved || !demo.approvalConfirmed} onClick={demo.approvePlan}>{plan.approved ? `已批准 · ${demo.approvedAt}` : "批准此计划"}</button></div>
    <p className="jd-muted">批准保留为独立事实，不代表远端执行或交付已经完成。</p>
  </div>;
}

function DigestDetails({ demo }: { demo: DemoController }) {
  return <div className="jd-stack"><dl className="jd-facts"><Fact label="计划">{demo.plan.id}</Fact><Fact label="摘要算法">SHA-256 · 64 位十六进制</Fact></dl><div className="jd-digest-block jd-digest-block--large"><code>{demo.plan.digest}</code></div><p className="jd-note">批准绑定这份完整摘要。目标、配置或计划输入发生变化时，不能沿用原批准。</p><p className="jd-muted">批准时间：{demo.approvedAt} CST · 计划到期：{demo.plan.expiresAt}</p></div>;
}

function InputDetails({ reference }: { reference?: string }) {
  const normalized = reference?.toUpperCase().replace(/[^A-Z0-9]/g, "") ?? "";
  const selected = references.find((item) => normalized.startsWith(item.id.replace("-", "")));
  const items = selected ? [selected] : references;
  return <div className="jd-stack">{items.map((item) => <article className="jd-reference" key={item.id}><span className="jd-kicker">{item.id}</span><h3>{item.title}</h3><dl className="jd-facts"><Fact label="修订">{item.revision}</Fact><Fact label="所属任务">TASK-1042</Fact><Fact label="使用位置">{item.id === "ACC-014" ? "独立验收依据" : item.id === "REQ-014" ? "任务范围核对" : "固定构建来源"}</Fact></dl><p>{item.detail}</p></article>)}<p className="jd-muted">输入引用与运行结果分别保留；没有实际证据的项目继续等待确认。</p></div>;
}

function CancelTaskForm({ demo }: { demo: DemoController }) {
  const id = useId();
  const [error, setError] = useState("");
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const reason = String(new FormData(event.currentTarget).get("reason") ?? "").trim();
    if (!reason) {
      setError("请填写取消原因。");
      const field = event.currentTarget.elements.namedItem("reason");
      if (field instanceof HTMLElement) field.focus();
      return;
    }
    demo.cancelTask(reason);
  }
  return <form className="jd-form" noValidate onSubmit={submit}>
    <div className="jd-cancel-task"><span className="jd-kicker">{demo.selectedTask.id}</span><h3>{demo.selectedTask.title}</h3></div>
    <p className="jd-warning"><WarningCircle size={20} />取消请求只阻止后续普通推进。物理停止尚待确认，冲突资源与磁盘占用继续保留。</p>
    <div className="jd-field"><label htmlFor={id}>取消原因 <span>必填</span></label><textarea id={id} name="reason" rows={4} required placeholder="说明本次取消的原因，便于后续核对。" data-dialog-autofocus="true" aria-invalid={Boolean(error)} aria-describedby={error ? `${id}-error` : undefined} onChange={() => setError("")} />{error && <p id={`${id}-error`} className="jd-error" role="alert">{error}</p>}</div>
    <OfflineHint connected={demo.connected} />
    <div className="jd-actions"><span>保留原任务与操作身份。</span><button type="submit" className="jd-button" disabled={!demo.connected || demo.selectedTask.status === "cancel_requested"}>确认请求取消</button></div>
  </form>;
}

function DialogContent({ demo }: { demo: DemoController }) {
  switch (demo.modal?.kind) {
    case "create": return <CreateTaskForm demo={demo} />;
    case "connection": return <ConnectionDetails demo={demo} />;
    case "task": return <TaskDetails demo={demo} />;
    case "operation": return <OperationDetails demo={demo} />;
    case "plan": return <PlanDetails demo={demo} />;
    case "digest": return <DigestDetails demo={demo} />;
    case "input": return <InputDetails reference={demo.modal.reference} />;
    case "cancel": return <CancelTaskForm demo={demo} />;
    default: return null;
  }
}

export default function DemoDialogs({ demo }: { demo: DemoController }) {
  const id = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef(demo.closeModal);
  closeRef.current = demo.closeModal;
  const kind = demo.modal?.kind;
  const reference = demo.modal?.reference;
  const open = Boolean(kind);
  useEffect(() => {
    const currentDialog = dialogRef.current;
    if (!open || !currentDialog) return;
    const dialog: HTMLDivElement = currentDialog;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const focusables = () => Array.from(dialog.querySelectorAll<HTMLElement>('button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])')).filter((element) => element.getClientRects().length > 0);
    const focusFirst = () => (dialog.querySelector<HTMLElement>("[data-dialog-autofocus]") ?? focusables()[0] ?? dialog).focus({ preventScroll: true });
    focusFirst();
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); closeRef.current(); return; }
      if (event.key !== "Tab") return;
      const elements = focusables();
      const first = elements[0];
      const last = elements[elements.length - 1];
      if (!first || !last) { event.preventDefault(); dialog.focus(); return; }
      if (!dialog.contains(document.activeElement) || (event.shiftKey && document.activeElement === first) || (!event.shiftKey && document.activeElement === last)) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      }
    }
    function onFocusIn(event: FocusEvent) {
      if (event.target instanceof Node && !dialog.contains(event.target)) focusFirst();
    }
    document.addEventListener("keydown", onKeyDown, true);
    document.addEventListener("focusin", onFocusIn);
    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      document.removeEventListener("focusin", onFocusIn);
      document.body.style.overflow = previousOverflow;
      if (previousFocus?.isConnected) previousFocus.focus({ preventScroll: true });
    };
  }, [open]);
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!kind || !dialog) return;
    const first = dialog.querySelector<HTMLElement>("[data-dialog-autofocus], button:not([disabled]), input:not([disabled]), textarea:not([disabled])");
    (dialog.querySelector<HTMLElement>("[data-dialog-autofocus]") ?? first ?? dialog).focus({ preventScroll: true });
  }, [kind, reference]);
  if (!demo.modal) return null;
  const [title, description] = headings[demo.modal.kind];
  return <div className="jd-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) demo.closeModal(); }}>
    <div ref={dialogRef} className={`jd-dialog jd-dialog--${demo.modal.kind}`} role="dialog" aria-modal="true" aria-labelledby={`${id}-title`} aria-describedby={`${id}-description`} tabIndex={-1}>
      <header className="jd-header"><div><p className="jd-eyebrow">CLOUDHELM / TASK JOURNAL</p><h2 id={`${id}-title`}>{title}</h2><p id={`${id}-description`}>{description}</p></div><button type="button" className="jd-close" aria-label="关闭对话框" onClick={demo.closeModal}><X size={20} /></button></header>
      <div className="jd-content"><DialogContent demo={demo} />{demo.notice && <div className="jd-notice" role="status"><span>{demo.notice}</span><button type="button" onClick={demo.dismissNotice} aria-label="关闭提示"><X size={16} /></button></div>}</div>
      <footer className="jd-footer"><span>云舵 CloudHelm · 本地手记</span><button type="button" className="jd-text-button" onClick={demo.closeModal}>返回手记</button></footer>
    </div>
  </div>;
}
