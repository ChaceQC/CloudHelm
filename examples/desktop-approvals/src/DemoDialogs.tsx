import { useEffect, useId, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import type { DemoController, ModalKind } from "./contracts";
import "./dialogs.css";

type DialogProps = { demo: DemoController };
const STATUS = { ready: "待启动", waiting: "等待结果", cancel_requested: "取消已请求 · 停止待确认" };
const TITLES: Record<ModalKind, string> = {
  create: "创建任务", connection: "连接管理", task: "任务详情", operation: "执行事实", plan: "计划详情", digest: "核对计划摘要", input: "输入与引用", cancel: "请求取消任务",
};

function DialogShell({ title, onClose, children, wide = false }: { title: string; onClose(): void; children: ReactNode; wide?: boolean }) {
  const titleId = useId();
  const panel = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const focusable = () => Array.from(panel.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), textarea:not(:disabled), select:not(:disabled), a[href], [tabindex]:not([tabindex="-1"])') ?? []).filter((item) => item.getClientRects().length > 0);
    const focusFirst = () => (panel.current?.querySelector<HTMLElement>("[data-autofocus]") ?? focusable()[0] ?? panel.current)?.focus();
    const frame = requestAnimationFrame(focusFirst);
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); close.current(); }
      if (event.key !== "Tab") return;
      const elements = focusable();
      const first = elements[0];
      const last = elements[elements.length - 1];
      if (!first || !last) { event.preventDefault(); panel.current?.focus(); return; }
      if (event.shiftKey && (document.activeElement === first || document.activeElement === panel.current)) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    const onFocus = (event: FocusEvent) => { if (event.target instanceof Node && !panel.current?.contains(event.target)) focusFirst(); };
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("focusin", onFocus);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("focusin", onFocus);
      document.body.style.overflow = overflow;
      if (previous?.isConnected) previous.focus();
    };
  }, []);
  return <div className="demo-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <div ref={panel} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1} className={`demo-dialog${wide ? " demo-dialog--wide" : ""}`}>
      <header className="demo-dialog__header"><div><p className="demo-eyebrow">CLOUDHELM</p><h2 id={titleId}>{title}</h2></div><button type="button" className="demo-close" aria-label="关闭对话框" onClick={onClose}><svg viewBox="0 0 20 20" aria-hidden="true"><path d="m5 5 10 10M15 5 5 15" /></svg></button></header>
      {children}
    </div>
  </div>;
}

function Facts({ rows }: { rows: [string, ReactNode][] }) {
  return <dl className="demo-facts">{rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>;
}

function CloseFooter({ demo, children }: DialogProps & { children?: ReactNode }) {
  return <footer className="demo-dialog__footer"><button type="button" className="demo-button" onClick={demo.closeModal}>关闭</button>{children}</footer>;
}

function CreateTask({ demo }: DialogProps) {
  const id = useId();
  const [title, setTitle] = useState("");
  const [goal, setGoal] = useState("");
  const [budget, setBudget] = useState("12.00");
  const [errors, setErrors] = useState<Partial<Record<"title" | "goal" | "budget", string>>>({});
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const next = { title: title.trim() ? "" : "请填写任务名称。", goal: goal.trim() ? "" : "请填写任务目标。", budget: Number.isFinite(Number(budget)) && Number(budget) > 0 ? "" : "请填写大于零的预算。" };
    setErrors(next);
    const invalid = Object.entries(next).find(([, message]) => message);
    if (invalid) { event.currentTarget.querySelector<HTMLElement>(`[name="${invalid[0]}"]`)?.focus(); return; }
    if (demo.createTask({ title, goal, budget: Number(budget) })) demo.closeModal();
  }
  return <form noValidate onSubmit={submit}>
    <div className="demo-dialog__body"><p className="demo-lead">明确任务目标与预算。创建后保持待启动，准备好后再开始。</p>
      <label className="demo-field" htmlFor={`${id}-title`}><span>任务名称</span><input data-autofocus id={`${id}-title`} name="title" value={title} maxLength={80} placeholder="例如：核对交付前提" onChange={(event) => setTitle(event.target.value)} aria-invalid={Boolean(errors.title)} aria-describedby={errors.title ? `${id}-title-error` : undefined} />{errors.title && <small id={`${id}-title-error`} className="demo-error">{errors.title}</small>}</label>
      <label className="demo-field" htmlFor={`${id}-goal`}><span>任务目标</span><textarea id={`${id}-goal`} name="goal" value={goal} maxLength={600} rows={4} placeholder="描述预期交付与需要核对的输入" onChange={(event) => setGoal(event.target.value)} aria-invalid={Boolean(errors.goal)} aria-describedby={errors.goal ? `${id}-goal-error` : undefined} />{errors.goal && <small id={`${id}-goal-error`} className="demo-error">{errors.goal}</small>}</label>
      <label className="demo-field" htmlFor={`${id}-budget`}><span>预算上限（元）</span><input id={`${id}-budget`} name="budget" type="number" min="0.01" step="0.01" value={budget} onChange={(event) => setBudget(event.target.value)} aria-invalid={Boolean(errors.budget)} aria-describedby={errors.budget ? `${id}-budget-error` : `${id}-budget-help`} />{errors.budget ? <small id={`${id}-budget-error`} className="demo-error">{errors.budget}</small> : <small id={`${id}-budget-help`}>预算是任务上限，不代表已发生费用。</small>}</label>
      {!demo.connected && <p className="demo-callout demo-callout--amber">连接已断开，恢复后可创建任务。</p>}
    </div><footer className="demo-dialog__footer"><button type="button" className="demo-button" onClick={demo.closeModal}>返回</button><button type="submit" className="demo-button demo-button--primary" disabled={!demo.connected}>创建任务</button></footer>
  </form>;
}

function Connection({ demo }: DialogProps) {
  return <><div className="demo-dialog__body"><div className={`demo-connection${demo.connected ? " is-connected" : ""}`}><span className="demo-status-dot" /><div><strong>{demo.connected ? "已连接" : "连接已断开"}</strong><p>{demo.connected ? "可以继续核对与审批" : "正在查看最近同步快照"}</p></div><span className="demo-tag">演示连接</span></div>
    <Facts rows={[["工作空间", "CloudHelm"], ["最近同步", demo.lastSync], ["目标", demo.plan.target]]} /><p className="demo-callout">断线后仍可查看任务与计划快照；创建、启动、取消与批准将在连接恢复后开放。</p>
  </div><CloseFooter demo={demo}><button type="button" className="demo-button demo-button--primary" onClick={demo.toggleConnection}>{demo.connected ? "断开连接" : "恢复连接"}</button></CloseFooter></>;
}

function TaskDetail({ demo }: DialogProps) {
  const task = demo.selectedTask;
  return <><div className="demo-dialog__body"><div className="demo-section-heading"><span className="demo-mono">{task.id}</span><span className="demo-tag">{STATUS[task.status]}</span></div><h3 className="demo-task-title">{task.title}</h3><p className="demo-lead">{task.goal}</p>
    <Facts rows={[["预算上限", `¥ ${task.budget.toFixed(2)}`], ["最近更新", task.updatedAt], ["来源", "SRC-021"], ["需求 / 验收", "REQ-014 r3 / ACC-014 r2"]]} />
    {task.cancelReason && <p className="demo-callout demo-callout--amber"><strong>取消原因：</strong>{task.cancelReason}<br />停止待确认，相关资源继续保留。</p>}
    {task.id === "TASK-1042" && <button type="button" className="demo-link" onClick={() => demo.openModal("operation", "Op-218")}>查看原操作 Op-218 · unknown <span aria-hidden="true">↗</span></button>}
  </div><CloseFooter demo={demo}><button type="button" className="demo-button" onClick={() => demo.openModal("input", "SRC-021")}>查看输入</button><button type="button" className="demo-button demo-button--primary" disabled={!demo.connected || task.status !== "ready"} onClick={demo.startTask}>启动任务</button><button type="button" className="demo-button demo-button--danger" disabled={!demo.connected || task.status === "cancel_requested"} onClick={() => demo.openModal("cancel")}>请求取消</button></CloseFooter></>;
}

function Operation({ demo }: DialogProps) {
  const reference = demo.modal?.reference;
  const isPlan = Boolean(reference && reference !== "Op-218");
  const [queried, setQueried] = useState(false);
  return <><div className="demo-dialog__body"><div className="demo-section-heading"><span className="demo-mono">{isPlan ? demo.plan.id : "Op-218"}</span><span className={`demo-tag${isPlan ? "" : " demo-tag--amber"}`}>{isPlan ? "执行未开始" : "unknown · 结果待核对"}</span></div>
    <p className="demo-lead">{isPlan ? "该计划尚未开始执行。批准只记录你的决定，执行与健康结果需要分别确认。" : "最近记录不足以确认执行结果。请沿原操作身份核对，保留既有影响与资源占用。"}</p>
    <Facts rows={isPlan ? [["查看内容", reference ?? demo.plan.id], ["计划批准", demo.plan.approved ? `已批准 · ${demo.approvedAt}` : "待批准"], ["远端执行", "未开始"], ["健康观察", "未开始"], ["目标", demo.plan.target]] : [["所属任务", "TASK-1042 · 验证构建与交付"], ["操作身份", "Op-218"], ["最近观察", demo.lastSync], ["物理停止", "尚未确认"], ["资源", "继续保留，待核对后决定释放"]]} />
    {queried && <p className="demo-callout" role="status">{isPlan ? "已查看当前记录：计划执行仍未开始。" : "已按 Op-218 查询：结果仍为 unknown，停止待确认，资源继续保留。"}</p>}
    {!demo.connected && <p className="demo-callout demo-callout--amber">当前为离线快照。恢复连接后可再次查询。</p>}
  </div><CloseFooter demo={demo}><button type="button" className="demo-button demo-button--primary" disabled={!demo.connected} onClick={() => { demo.refresh(); setQueried(true); }}>{isPlan ? "查看最新记录" : "查询原操作"}</button></CloseFooter></>;
}

function PlanDetail({ demo }: DialogProps) {
  return <><div className="demo-dialog__body"><div className="demo-section-heading"><span className="demo-mono">{demo.plan.id}</span><span className="demo-tag">{demo.plan.approved ? "已批准 · 执行未开始" : "待批准"}</span></div>
    <div className="demo-change-grid"><div><span>Release</span><p>{demo.plan.currentRelease}<b aria-hidden="true">→</b><strong>{demo.plan.release}</strong></p></div><div><span>环境配置修订</span><p>r{demo.plan.configFrom}<b aria-hidden="true">→</b><strong>r{demo.plan.configTo}</strong></p></div></div>
    <Facts rows={[["目标", demo.plan.target], ["环境", demo.plan.environment], ["有效期", demo.plan.expiresAt], ["条件检查", demo.checkedAt ? `通过 · ${demo.checkedAt}` : "尚未检查"], ["批准时间", demo.approvedAt || "尚未批准"], ["秘密引用", "notes-db"]]} />
    <button type="button" className="demo-digest-preview" onClick={() => demo.openModal("digest")}><span>完整计划摘要</span><code>{demo.plan.digest}</code><span className="demo-link">展开核对 <span aria-hidden="true">↗</span></span></button>
    <label className="demo-check"><input type="checkbox" checked={demo.approvalConfirmed} disabled={!demo.connected || !demo.checkedAt || demo.plan.approved} onChange={(event) => demo.setApprovalConfirmed(event.target.checked)} /><span>我已核对目标、起始版本、配置修订与完整摘要，确认批准这份固定计划。</span></label>
    <p className="demo-caption">批准后仍需等待执行事实与健康观察。</p>
  </div><CloseFooter demo={demo}><button type="button" className="demo-button" disabled={!demo.connected || demo.plan.approved} onClick={demo.checkPlan}>检查条件</button><button type="button" className="demo-button demo-button--primary" disabled={!demo.connected || !demo.checkedAt || !demo.approvalConfirmed || demo.plan.approved} onClick={demo.approvePlan}>{demo.plan.approved ? "已批准" : "批准计划"}</button></CloseFooter></>;
}

function Digest({ demo }: DialogProps) {
  const [copyStatus, setCopyStatus] = useState("");
  const digest = useRef<HTMLTextAreaElement>(null);
  async function copy() {
    try {
      if (!navigator.clipboard?.writeText) throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(demo.plan.digest);
      setCopyStatus("完整摘要已复制。");
    } catch {
      digest.current?.focus();
      digest.current?.select();
      setCopyStatus("无法访问剪贴板，已选中完整摘要，可按 Ctrl+C 复制。");
    }
  }
  return <><div className="demo-dialog__body"><p className="demo-lead">{demo.plan.id} 的完整 SHA-256 摘要。请与目标、起始状态和配置修订一起核对。</p><label className="demo-field"><span>完整摘要 · 64 位十六进制</span><textarea ref={digest} className="demo-digest" readOnly rows={3} value={demo.plan.digest} onFocus={(event) => event.target.select()} /></label><Facts rows={[["目标", demo.plan.target], ["Release", `${demo.plan.currentRelease} → ${demo.plan.release}`], ["配置修订", `r${demo.plan.configFrom} → r${demo.plan.configTo}`]]} />{copyStatus && <p className="demo-copy-status" role="status">{copyStatus}</p>}</div><CloseFooter demo={demo}><button type="button" className="demo-button demo-button--primary" onClick={copy}>复制完整摘要</button><button type="button" className="demo-button" onClick={() => demo.openModal("plan")}>返回计划</button></CloseFooter></>;
}

function InputDetails({ demo }: DialogProps) {
  const reference = demo.modal?.reference;
  const migration = reference?.toLocaleLowerCase().includes("migration") || reference?.includes("迁移");
  return <><div className="demo-dialog__body"><p className="demo-lead">{migration ? "迁移核对属于计划的固定输入。执行尚未开始，当前没有迁移成功结论。" : "本次任务与审批使用以下固定来源及修订。输入变化后，需要重新核对适用性。"}</p>
    {reference && <p className="demo-caption">当前引用：<span className="demo-mono">{reference}</span></p>}
    <div className="demo-reference"><span className="demo-reference__kind">来源</span><div><strong>SRC-021</strong><h3>构建与交付验证任务说明</h3><p>核对制品、环境交付计划、目标起始状态，以及原操作待核对记录。</p></div></div>
    <div className="demo-reference"><span className="demo-reference__kind">需求</span><div><strong>REQ-014 r3</strong><h3>固定计划审批与执行核对</h3><p>从 Release {demo.plan.currentRelease}、配置 r{demo.plan.configFrom} 变更至 {demo.plan.release}、r{demo.plan.configTo}，目标为 {demo.plan.target}。</p></div></div>
    <div className="demo-reference"><span className="demo-reference__kind">验收</span><div><strong>ACC-014 r2</strong><h3>分别记录审批、执行与健康结果</h3><p>批准不作为执行完成依据；结果未知时继续核对原操作，停止未确认前保留资源。</p></div></div>
    <Facts rows={[["数据库前提", "按计划绑定的线性迁移与后置检查核对"], ["秘密引用", "notes-db"], ["执行状态", "尚未开始"]]} />
  </div><CloseFooter demo={demo} /></>;
}

function CancelTask({ demo }: DialogProps) {
  const id = useId();
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!reason.trim()) { setError("请填写取消原因。"); event.currentTarget.querySelector<HTMLTextAreaElement>("textarea")?.focus(); return; }
    if (demo.cancelTask(reason)) demo.closeModal();
  }
  return <form noValidate onSubmit={submit}><div className="demo-dialog__body"><p className="demo-lead">{demo.selectedTask.id} · {demo.selectedTask.title}</p><p className="demo-callout demo-callout--amber">提交后将阻止任务继续普通推进。物理停止仍待确认，相关资源会继续保留，已发生的变更不会自动撤销。</p>
    <label className="demo-field" htmlFor={id}><span>取消原因</span><textarea data-autofocus id={id} rows={4} value={reason} maxLength={500} placeholder="说明取消原因，便于后续核对与交接" onChange={(event) => { setReason(event.target.value); setError(""); }} aria-invalid={Boolean(error)} aria-describedby={error ? `${id}-error` : `${id}-hint`} />{error ? <small id={`${id}-error`} className="demo-error">{error}</small> : <small id={`${id}-hint`}>最多 500 个字，取消请求不会表示停止已完成。</small>}</label>
    {!demo.connected && <p className="demo-caption">连接已断开，恢复后可提交取消请求。</p>}
  </div><footer className="demo-dialog__footer"><button type="button" className="demo-button" onClick={demo.closeModal}>继续查看</button><button type="submit" className="demo-button demo-button--danger" disabled={!demo.connected || demo.selectedTask.status === "cancel_requested"}>提交取消请求</button></footer></form>;
}

export default function DemoDialogs({ demo }: DialogProps) {
  if (!demo.modal) return null;
  const { kind, reference } = demo.modal;
  const content = { create: <CreateTask demo={demo} />, connection: <Connection demo={demo} />, task: <TaskDetail demo={demo} />, operation: <Operation demo={demo} />, plan: <PlanDetail demo={demo} />, digest: <Digest demo={demo} />, input: <InputDetails demo={demo} />, cancel: <CancelTask demo={demo} /> };
  return <DialogShell key={`${kind}:${reference ?? ""}`} title={TITLES[kind]} onClose={demo.closeModal} wide={kind === "plan" || kind === "input"}>{content[kind]}</DialogShell>;
}
