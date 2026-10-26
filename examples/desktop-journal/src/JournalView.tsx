import { useRef, useState, type UIEvent } from "react";
import {
  ArrowClockwise, BookmarkSimple, CaretDown, CaretRight, ClipboardText,
  Clock, DotsThree, FileText, Flask, Info, ListBullets, Plus, Pulse,
  ShieldCheck, CompassRose, Target, User, X,
} from "@phosphor-icons/react";
import type { DemoController } from "./contracts";
import "./journal.css";

const chapters = [
  { id: "goal", title: "任务目标", icon: Target },
  { id: "inputs", title: "固定输入", icon: FileText },
  { id: "plan", title: "交付计划", icon: ListBullets },
  { id: "facts", title: "进度事实", icon: Pulse },
  { id: "operations", title: "操作记录", icon: ClipboardText },
] as const;
type ChapterId = (typeof chapters)[number]["id"];
type DemoProps = { demo: DemoController };
const references = [
  { label: "源码快照", reference: "SRC-021" },
  { label: "需求", reference: "REQ-014 修订 r3" },
  { label: "验收", reference: "ACC-014 修订 r2" },
];
const archiveTask = (demo: DemoController) => /1042$/.test(demo.selectedTask.id);

function JournalHeader({ demo }: DemoProps) {
  return (
    <header className="journal-topbar">
      <div className="journal-topbar-left">
        <div className="journal-brand"><CompassRose size={35} aria-hidden="true" /><span>CloudHelm</span></div>
        <button className="journal-project journal-topbutton" onClick={() => demo.openModal("task")}>
          <BookmarkSimple size={23} aria-hidden="true" /><span>便签服务</span>
        </button>
        <button className="journal-hub journal-topbutton" onClick={() => demo.openModal("connection")}>
          <span className={`journal-status-dot ${demo.connected ? "is-connected" : ""}`} />
          <span>Hub{demo.connected ? "已连接" : "已断开"}</span>
        </button>
      </div>
      <div className="journal-topbar-right">
        <button className="journal-topbutton" onClick={() => demo.openModal("connection")}>
          <User size={23} aria-hidden="true" /><span>项目维护者</span><CaretDown size={13} aria-hidden="true" />
        </button>
        <span className="journal-topbar-divider" />
        <button className="journal-topbutton" onClick={() => demo.openModal("input", "本地演示数据")}>
          <Flask size={23} aria-hidden="true" /><span>演示数据</span><CaretDown size={13} aria-hidden="true" />
        </button>
        <div className="journal-clock"><Clock size={23} aria-hidden="true" /><time dateTime="2026-10-26T10:42:00+08:00">2026-10-26 10:42 CST</time></div>
      </div>
    </header>
  );
}

function TaskPicker({ demo, close }: DemoProps & { close: () => void }) {
  return (
    <div className="journal-task-picker" aria-label="选择本地任务">
      <label htmlFor="journal-task-search">选择本地任务</label>
      <input id="journal-task-search" type="search" placeholder="搜索任务名称或编号" value={demo.query} onChange={(event) => demo.setQuery(event.target.value)} />
      <div className="journal-task-options">
        {demo.visibleTasks.map((task) => (
          <button key={task.id} className={task.id === demo.selectedTask.id ? "is-selected" : ""} onClick={() => { demo.selectTask(task.id); close(); }}>
            <span>{task.title}</span><small>{task.id} · {task.status === "ready" ? "待启动" : task.status === "cancel_requested" ? "取消请求已记录" : "等待核对"}</small>
          </button>
        ))}
        {demo.visibleTasks.length === 0 && <p className="journal-picker-empty">没有找到匹配的本地任务</p>}
      </div>
      <button className="journal-link journal-picker-details" onClick={() => { demo.openModal("task"); close(); }}>查看当前任务详情</button>
    </div>
  );
}

function JournalSidebar({ demo, active, navigate }: DemoProps & { active: ChapterId; navigate: (id: ChapterId) => void }) {
  const [pickerOpen, setPickerOpen] = useState(false);
  return (
    <aside className="journal-sidebar">
      <div className="journal-sidebar-top" onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setPickerOpen(false); }} onKeyDown={(event) => { if (event.key === "Escape") setPickerOpen(false); }}>
        <button className="journal-tasklist-button" aria-expanded={pickerOpen} onClick={() => setPickerOpen(!pickerOpen)}>任务列表</button>
        <button className="journal-create" onClick={() => demo.openModal("create")}><Plus size={17} aria-hidden="true" />新建任务</button>
        {pickerOpen && <TaskPicker demo={demo} close={() => setPickerOpen(false)} />}
      </div>
      <h2 className="journal-sidebar-title">任务纪事册</h2>
      <nav className="journal-chapters" aria-label="任务手记章节">
        {chapters.map(({ id, title, icon: Icon }) => (
          <button key={id} className={`journal-chapter ${active === id ? "is-active" : ""}`} aria-current={active === id ? "location" : undefined} onClick={() => navigate(id)}>
            <Icon size={25} weight="regular" aria-hidden="true" /><span>{title}</span>
          </button>
        ))}
      </nav>
      <div className="journal-sidebar-footer">
        <button className="journal-sync" onClick={demo.refresh}><ArrowClockwise size={22} aria-hidden="true" /><span>最后同步 {demo.lastSync}</span></button>
        <button className="journal-identity" onClick={() => demo.openModal("connection")}><ShieldCheck size={24} aria-hidden="true" /><span>连接与身份</span><CaretRight size={18} aria-hidden="true" /></button>
      </div>
    </aside>
  );
}

function TaskControls({ demo }: DemoProps) {
  const [open, setOpen] = useState(false);
  const openDialog = (kind: "task" | "cancel") => { setOpen(false); demo.openModal(kind); };
  return (
    <div className="journal-controls" onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false); }} onKeyDown={(event) => { if (event.key === "Escape") setOpen(false); }}>
      <button className="journal-controls-trigger" aria-expanded={open} aria-haspopup="menu" onClick={() => setOpen(!open)}>任务控制<DotsThree size={22} weight="bold" aria-hidden="true" /></button>
      {open && <div className="journal-control-menu" role="menu" aria-label="任务控制">
        <button role="menuitem" onClick={() => openDialog("task")}>查看任务详情</button>
        <button role="menuitem" disabled={demo.selectedTask.status !== "ready" || !demo.connected} onClick={() => { setOpen(false); demo.startTask(); }}>启动任务</button>
        <button role="menuitem" disabled={demo.selectedTask.status === "cancel_requested"} onClick={() => openDialog("cancel")}>请求取消…</button>
      </div>}
    </div>
  );
}

function GoalSection({ demo }: DemoProps) {
  return (
    <section id="journal-goal" className="journal-section journal-goal" data-chapter="goal">
      <h2>任务目标</h2>
      <p>{demo.selectedTask.goal}</p>
      <dl className="journal-budget"><dt>预算上限</dt><dd>¥{demo.selectedTask.budget.toFixed(2)}</dd></dl>
    </section>
  );
}

function InputsSection({ demo }: DemoProps) {
  return (
    <section id="journal-inputs" className="journal-section journal-inputs" data-chapter="inputs">
      <h2>固定输入</h2>
      {archiveTask(demo) ? <table aria-label="任务固定输入"><tbody>
        {references.map(({ label, reference }) => <tr key={label}>
          <th scope="row">{label}</th><td>{reference}</td>
          <td><button className="journal-link" onClick={() => demo.openModal("input", reference)}>查看引用</button></td>
        </tr>)}
      </tbody></table> : <p className="journal-muted">尚未固定输入。启动任务前可在任务详情中核对。</p>}
    </section>
  );
}

function PlanSection({ demo }: DemoProps) {
  return (
    <section id="journal-plan" className="journal-section journal-plan" data-chapter="plan">
      <h2>交付计划</h2>
      {archiveTask(demo) ? <>
        <p><button className="journal-link" onClick={() => demo.openModal("plan")}>{demo.plan.id}</button> 将 Release {demo.plan.release} 交付至 {demo.plan.target}</p>
        <p>{demo.plan.approved ? "已批准，执行结果待核对" : "等待摘要核对与批准，后续执行尚未启动"}</p>
        <button className="journal-link" onClick={() => demo.openModal("plan")}>查看计划与批准记录</button>
      </> : <p className="journal-muted">当前任务尚无已绑定的交付计划。</p>}
    </section>
  );
}

function ProgressSection({ demo }: DemoProps) {
  const cancelled = demo.selectedTask.status === "cancel_requested";
  return (
    <section id="journal-facts" className="journal-section journal-facts" data-chapter="facts">
      <h2>进度事实</h2>
      {archiveTask(demo) ? <>
        <div className="journal-unknown">
          <h3><span className="journal-unknown-dot" />Op-218 归档传输结果<span className="journal-unknown-label">未知</span></h3>
          <p>尚未取得确定结果；后续步骤尚未启动。</p>
          <div className="journal-fact-actions"><button className="journal-primary" onClick={() => demo.openModal("operation")}>查询原操作</button><button className="journal-link" onClick={() => demo.openModal("operation")}>操作记录</button></div>
        </div>
        <ol className="journal-step-facts" aria-label="部署步骤实际状态">
          {["归档传输", "数据库迁移", "服务更新", "健康检查"].map((step, index) => <li key={step}><span>{step}</span><span>{index === 0 ? "待核对" : "未启动"}</span></li>)}
        </ol>
      </> : <div className="journal-pending-fact"><h3>{demo.selectedTask.status === "ready" ? "任务尚未启动" : "等待后续事实"}</h3><p>尚无执行回执，后续进度将在取得事实后记录。</p></div>}
      {cancelled && <div className="journal-cancel-fact"><strong>取消请求已记录</strong><p>原因：{demo.selectedTask.cancelReason || "已提交取消请求"}</p><p>物理停止待确认，未确认释放的资源继续保留。</p></div>}
      <p className="journal-fact-footnote">接收不等于完成，批准不等于执行。</p>
    </section>
  );
}

function OperationsSection({ demo }: DemoProps) {
  return (
    <section id="journal-operations" className="journal-section journal-operations" data-chapter="operations">
      <h2>操作记录</h2>
      {archiveTask(demo) ? <><p>Op-218 · 归档传输</p><p className="journal-muted">原操作结果未知；查询与刷新均保留当前事实。</p><button className="journal-link" onClick={() => demo.openModal("operation")}>查看原操作与核对记录</button></> : <p className="journal-muted">尚无可核对的执行操作。</p>}
      {demo.selectedTask.status === "cancel_requested" && <p>取消请求与物理停止分别记录，停止状态仍待确认。</p>}
    </section>
  );
}

function JournalDocument({ demo }: DemoProps) {
  return (
    <article className="journal-document">
      <div className="journal-document-date"><time dateTime="2026-10-26">2026年10月26日</time><span>·</span><span>Asia/Shanghai</span></div>
      <div className="journal-document-heading"><div><h1>{archiveTask(demo) ? "验证构建与交付" : demo.selectedTask.title}</h1><button className="journal-task-id" onClick={() => demo.openModal("task")}>{demo.selectedTask.id}</button></div><TaskControls demo={demo} /></div>
      <GoalSection demo={demo} />
      <InputsSection demo={demo} />
      <PlanSection demo={demo} />
      <ProgressSection demo={demo} />
      <OperationsSection demo={demo} />
    </article>
  );
}

function EvidenceIndex({ demo }: DemoProps) {
  const original = archiveTask(demo);
  return (
    <aside className="journal-evidence" aria-label="证据索引">
      <h2>证据索引</h2>
      <div className="journal-evidence-list">
        <button className="journal-evidence-item" onClick={() => demo.openModal("input", original ? "固定输入" : demo.selectedTask.id)}><FileText size={29} aria-hidden="true" /><span><strong>任务输入</strong><small>来自 <span className="journal-reference">固定输入</span></small></span></button>
        {original && <>
          <button className="journal-evidence-item" onClick={() => demo.openModal("plan")}><ClipboardText size={29} aria-hidden="true" /><span><strong>计划快照 <span className="journal-reference">{demo.plan.id}</span></strong><small>来自 <span className="journal-reference">交付计划</span></small></span></button>
          <button className="journal-evidence-item" onClick={() => demo.openModal("operation")}><Clock size={29} aria-hidden="true" /><span><strong>Op-218 操作记录</strong><small>来自 <span className="journal-reference">操作记录</span></small></span></button>
        </>}
      </div>
      <div className="journal-completion-empty"><FileText size={29} aria-hidden="true" /><span>暂无完成证据</span></div>
      <div className="journal-physical-note"><Info size={25} aria-hidden="true" /><p>取消请求与物理停止分别记录，未确认释放的资源继续保留。</p></div>
      {demo.selectedTask.status === "cancel_requested" && <p className="journal-stop-state">取消请求：已记录<br />物理停止：待确认</p>}
      <p className="journal-deployment-note">独立部署按原操作核对，<br />任务取消不替代部署控制。</p>
      {original && <button className="journal-deployment-link" onClick={() => demo.openModal("plan")}><span>部署详情</span><CaretRight size={21} aria-hidden="true" /></button>}
    </aside>
  );
}

export default function JournalView({ demo }: DemoProps) {
  const [active, setActive] = useState<ChapterId>("facts");
  const documentRef = useRef<HTMLElement | null>(null);
  const navigate = (id: ChapterId) => {
    setActive(id);
    documentRef.current?.querySelector<HTMLElement>(`#journal-${id}`)?.scrollIntoView({ block: "start" });
  };
  const trackChapter = (event: UIEvent<HTMLElement>) => {
    if (event.currentTarget.scrollTop + event.currentTarget.clientHeight >= event.currentTarget.scrollHeight - 2) {
      setActive("operations");
      return;
    }
    const top = event.currentTarget.getBoundingClientRect().top;
    const visible = Array.from(event.currentTarget.querySelectorAll<HTMLElement>("[data-chapter]")).filter((section) => section.getBoundingClientRect().top <= top + 170);
    const chapter = chapters.find(({ id }) => id === visible[visible.length - 1]?.dataset.chapter);
    if (chapter) setActive(chapter.id);
  };
  return (
    <div className="journal-shell">
      <JournalHeader demo={demo} />
      <div className="journal-body">
        <JournalSidebar demo={demo} active={active} navigate={navigate} />
        <main className="journal-main" ref={documentRef} onScroll={trackChapter} aria-label="任务手记正文"><JournalDocument demo={demo} /></main>
        <EvidenceIndex demo={demo} />
      </div>
      {demo.notice && <div className="journal-notice" role="status"><span>{demo.notice}</span><button aria-label="关闭提示" onClick={demo.dismissNotice}><X size={18} aria-hidden="true" /></button></div>}
    </div>
  );
}
