import { useState } from "react";
import {
  Archive,
  ArrowClockwise,
  ArrowRight,
  ArrowSquareOut,
  ArrowsClockwise,
  CaretDown,
  CheckCircle,
  CheckSquare,
  Circle,
  Clock,
  Cube,
  Database,
  FileCode,
  Funnel,
  HardDrives,
  Heartbeat,
  Info,
  LockKey,
  MagnifyingGlass,
  ShieldCheck,
  SteeringWheel,
  Tag,
  User,
  X,
} from "@phosphor-icons/react";
import type { DemoController } from "./contracts";
import "./approvals.css";

type DemoProps = { demo: DemoController };

const phases = [
  { title: "归档传输", Icon: Archive },
  { title: "数据库迁移", Icon: Database },
  { title: "服务更新", Icon: ArrowsClockwise },
  { title: "健康检查", Icon: Heartbeat },
];

function demoTarget(target: string) {
  return target.includes("演示") ? target : `${target}（演示）`;
}

function compactDigest(digest: string) {
  return digest.length > 23 ? `${digest.slice(0, 12)}…${digest.slice(-4)}` : digest;
}

function TopNavigation({ demo }: DemoProps) {
  return (
    <header className="approvals-topbar">
      <a className="approvals-brand" href="#approval-inbox" aria-label="CloudHelm 审批收件箱">
        <SteeringWheel size={35} weight="regular" aria-hidden="true" />
        <span>CloudHelm</span>
      </a>
      <button className="approvals-project" onClick={() => demo.openModal("input", "便签服务")}>
        <span>便签服务</span><CaretDown size={18} aria-hidden="true" />
      </button>
      <nav className="approvals-navigation" aria-label="项目导航">
        <button onClick={() => demo.openModal("input", "项目工作台")}>工作台</button>
        <button onClick={() => demo.openModal("task", demo.selectedTask.id)}>任务</button>
        <button onClick={() => demo.openModal("plan", demo.plan.id)}>交付</button>
        <button className="is-active" aria-current="page" onClick={() => demo.openModal("plan", demo.plan.id)}>审批</button>
        <button onClick={() => demo.openModal("connection")}>连接与身份</button>
      </nav>
      <div className="approvals-account">
        <button className={`approvals-connection ${demo.connected ? "is-connected" : "is-disconnected"}`} onClick={() => demo.openModal("connection")}>
          <Circle size={13} weight="fill" aria-hidden="true" />
          <span>Hub {demo.connected ? "已连接" : "已断开"}</span>
        </button>
        <span className="approvals-account-divider" aria-hidden="true" />
        <button className="approvals-maintainer" aria-label="项目维护者身份" onClick={() => demo.openModal("connection", "identity")}>
          <User size={26} aria-hidden="true" /><span>项目维护者</span><CaretDown size={15} aria-hidden="true" />
        </button>
      </div>
    </header>
  );
}

function PlanListItem({ demo }: DemoProps) {
  return (
    <button className="approval-list-item is-selected" onClick={() => demo.openModal("plan", demo.plan.id)} aria-label={`查看 ${demo.plan.id} 部署计划`}>
      <span className="approval-list-item__heading">
        <Circle size={13} weight="fill" aria-hidden="true" /><strong>{demo.plan.id}</strong>
        <span className="approval-list-item__status">{demo.plan.approved ? "已批准" : "待人类批准"}</span>
      </span>
      <span className="approval-list-item__description">便签服务 / {demoTarget(demo.plan.target)} / Release {demo.plan.release}</span>
      <span className="approval-list-item__time"><Clock size={16} aria-hidden="true" />{(demo.approvedAt || demo.checkedAt).replace(/ CST$/, "")}</span>
    </button>
  );
}

function ApprovalInbox({ demo }: DemoProps) {
  const [query, setQuery] = useState("");
  const [pendingOnly, setPendingOnly] = useState(true);
  const searchText = `${demo.plan.id} 便签服务 ${demo.plan.target} ${demo.plan.environment} Release ${demo.plan.release}`.toLocaleLowerCase();
  const matchesSearch = searchText.includes(query.trim().toLocaleLowerCase());
  const showPlan = matchesSearch && (!pendingOnly || !demo.plan.approved);

  return (
    <aside className="approval-inbox" aria-label="审批计划列表">
      <div className="approval-inbox__heading">
        <CheckSquare size={19} aria-hidden="true" /><h2>{pendingOnly ? "待我批准" : "全部审批"}</h2>
        <span className="approval-inbox__count">{showPlan ? 1 : 0}</span>
        <button className={`approval-filter ${pendingOnly ? "is-active" : ""}`} aria-label={pendingOnly ? "显示全部审批" : "只显示待我批准"} aria-pressed={pendingOnly} onClick={() => setPendingOnly(!pendingOnly)} title={pendingOnly ? "显示全部审批" : "只显示待我批准"}>
          <Funnel size={19} aria-hidden="true" />
        </button>
      </div>
      <label className="approval-search">
        <MagnifyingGlass size={21} aria-hidden="true" />
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索计划 ID / 目标环境 / Release" aria-label="搜索审批计划" />
        {query && <button type="button" aria-label="清空搜索" onClick={() => setQuery("")}><X size={15} aria-hidden="true" /></button>}
      </label>
      {showPlan ? <PlanListItem demo={demo} /> : (
        <div className="approval-inbox__empty" role="status">
          <MagnifyingGlass size={30} aria-hidden="true" />
          <strong>{query ? "没有找到审批计划" : "暂时没有待批准计划"}</strong>
          <p>{query ? "尝试计划 ID、目标环境或 Release。" : "已批准的计划可以在全部审批中查看。"}</p>
          {!query && <button className="approvals-text-link" onClick={() => setPendingOnly(false)}>查看全部审批</button>}
        </div>
      )}
    </aside>
  );
}

function PlanHeading({ demo }: DemoProps) {
  return (
    <div className="approval-plan-heading">
      <h2>{demo.plan.id} 部署计划</h2>
      <div className="approval-plan-statuses">
        <button className={`approval-state ${demo.checkedAt ? "approval-state--checked" : "approval-state--pending"}`} onClick={() => demo.openModal("input", "条件检查")}>
          {demo.checkedAt ? <CheckCircle size={18} weight="fill" aria-hidden="true" /> : <Clock size={18} aria-hidden="true" />}
          <span>{demo.checkedAt ? "条件检查已通过" : "条件待检查"}</span>
          {demo.checkedAt && <time>{demo.checkedAt.replace(/ CST$/, "")}</time>}
        </button>
        <span className="approval-state approval-state--human">
          {demo.plan.approved ? <CheckCircle size={18} aria-hidden="true" /> : <Clock size={18} aria-hidden="true" />}
          {demo.plan.approved ? "人类已批准" : "待人类批准"}
        </span>
        <button className="approval-state approval-state--execution" onClick={() => demo.openModal("operation", demo.plan.id)}>
          <Circle size={13} weight="fill" aria-hidden="true" />执行尚未开始
        </button>
        <button className="approvals-text-link approval-full-plan" onClick={() => demo.openModal("plan", demo.plan.id)}>
          查看完整计划<ArrowSquareOut size={17} aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}

function PlanComparison({ demo }: DemoProps) {
  const rows = [
    { label: "Release", Icon: Tag, before: demo.plan.currentRelease, after: demo.plan.release },
    { label: "配置修订", Icon: FileCode, before: demo.plan.configFrom, after: demo.plan.configTo },
    { label: "目标主机", Icon: HardDrives, before: demoTarget(demo.plan.target), after: demoTarget(demo.plan.target) },
    { label: "资源声明（示例）", Icon: Cube, before: "2 核 CPU / 2 GiB 内存 / 8 GiB 磁盘", after: "2 核 CPU / 2 GiB 内存 / 8 GiB 磁盘" },
  ];

  return (
    <div className="approval-comparison">
      <table>
        <colgroup><col className="comparison-label" /><col className="comparison-before" /><col className="comparison-direction" /><col className="comparison-after" /></colgroup>
        <thead><tr><th aria-label="变更项" /><th scope="col">当前环境记录</th><th aria-label="变更方向" /><th scope="col">本计划目标</th></tr></thead>
        <tbody>
          {rows.map(({ label, Icon, before, after }) => (
            <tr key={label}>
              <th scope="row"><span className="comparison-field"><Icon size={19} aria-hidden="true" /><span>{label}</span></span></th>
              <td>{before}</td><td className="comparison-arrow"><ArrowRight size={18} aria-hidden="true" /></td><td className="comparison-target">{after}</td>
            </tr>
          ))}
          <tr>
            <th scope="row"><span className="comparison-field"><Database size={19} aria-hidden="true" /><span>数据库影响</span></span></th>
            <td colSpan={3}><span className="comparison-migration">迁移 0007 <ArrowRight size={16} aria-hidden="true" /> 0008（示例）</span><span className="comparison-inline-divider" aria-hidden="true" /><button className="approvals-text-link" onClick={() => demo.openModal("input", "migration")}>查看迁移说明<ArrowSquareOut size={16} aria-hidden="true" /></button></td>
          </tr>
          <tr>
            <th scope="row"><span className="comparison-field"><LockKey size={19} aria-hidden="true" /><span>配置变更要点</span></span></th>
            <td colSpan={3}>secret 引用: notes-db（仅引用，不含实际值）</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

function PlanStages({ demo }: DemoProps) {
  return (
    <section className="approval-stages" aria-labelledby="approval-stages-title">
      <h3 id="approval-stages-title">计划阶段 <span>（共 4 个）</span></h3>
      <ol className="approval-stage-flow">
        {phases.map(({ title, Icon }, index) => (
          <li key={title}>
            <button className="approval-stage" onClick={() => demo.openModal("operation", `${demo.plan.id} / ${title}`)}>
              <Icon size={25} aria-hidden="true" />
              <span><strong>{index + 1} {title}</strong><span className="approval-stage__status"><Circle size={10} weight="fill" aria-hidden="true" />未启动</span></span>
            </button>
            {index < phases.length - 1 && <ArrowRight className="approval-stage-arrow" size={20} aria-hidden="true" />}
          </li>
        ))}
      </ol>
    </section>
  );
}

function ApprovalFacts({ demo }: DemoProps) {
  return (
    <div className="approval-facts">
      <h3 id="approval-information-title">批准信息</h3>
      <dl>
        <div><dt>批准对象</dt><dd>{demo.plan.id}</dd></div>
        <div className="approval-facts__digest"><dt>计划摘要</dt><dd>
          <button className="approval-digest-value" title={demo.plan.digest} onClick={() => demo.openModal("digest", demo.plan.id)}>{compactDigest(demo.plan.digest)}<ArrowSquareOut size={15} aria-hidden="true" /></button>
          <button className="approvals-text-link" onClick={() => demo.openModal("digest", demo.plan.id)}>查看完整摘要<ArrowSquareOut size={15} aria-hidden="true" /></button>
        </dd></div>
        <div><dt>目标环境</dt><dd>{demo.plan.environment} · {demoTarget(demo.plan.target)}</dd></div>
        <div><dt>批准有效期至</dt><dd>{demo.plan.expiresAt}</dd></div>
      </dl>
    </div>
  );
}

function ApprovalActions({ demo }: DemoProps) {
  const approvalDisabled = !demo.approvalConfirmed || !demo.connected || !demo.checkedAt || demo.plan.approved;
  const explanation = !demo.connected ? "Hub 已断开；恢复连接后再核对并批准。" : demo.plan.approved ? "批准已记录，执行尚未开始。" : "批准仅授权此计划，不表示部署已执行。";

  return (
    <>
      <div className="approval-confirmation-check">
        <label><input type="checkbox" checked={demo.approvalConfirmed} disabled={demo.plan.approved} onChange={(event) => demo.setApprovalConfirmed(event.target.checked)} /><span>我已核对完整摘要、目标环境与有效期</span></label>
        <button className="approvals-icon-link" aria-label="查看完整摘要、目标环境与有效期" onClick={() => demo.openModal("digest", demo.plan.id)}><ArrowSquareOut size={16} aria-hidden="true" /></button>
      </div>
      <div className="approval-actions">
        <button className="approval-approve-button" disabled={approvalDisabled} onClick={demo.approvePlan}>
          {demo.plan.approved ? <CheckCircle size={20} aria-hidden="true" /> : <LockKey size={20} aria-hidden="true" />}
          {demo.plan.approved ? "已批准此计划" : "批准此计划"}
        </button>
        <button className="approval-check-button" disabled={!demo.connected} onClick={demo.checkPlan}>检查当前条件</button>
        <div className="approval-action-explanation">
          <p><Info size={19} aria-hidden="true" /><span>{explanation}</span></p>
          <p><ShieldCheck size={19} aria-hidden="true" /><span>Approval binds this immutable full digest; changes require reconfirmation.</span></p>
        </div>
      </div>
    </>
  );
}

function PlanDetail({ demo }: DemoProps) {
  return (
    <article className="approval-plan" aria-label={`${demo.plan.id} 部署计划详情`}>
      <PlanHeading demo={demo} />
      <PlanComparison demo={demo} />
      <PlanStages demo={demo} />
      <div className="approval-related-task"><strong>关联任务</strong><button className="approvals-text-link" onClick={() => demo.openModal("task", demo.selectedTask.id)}>{demo.selectedTask.id} {demo.selectedTask.title}<ArrowSquareOut size={17} aria-hidden="true" /></button></div>
      <section className="approval-confirmation" aria-labelledby="approval-information-title">
        <ApprovalFacts demo={demo} />
        <ApprovalActions demo={demo} />
      </section>
    </article>
  );
}

export default function ApprovalsView({ demo }: DemoProps) {
  return (
    <div className="approvals-app">
      <TopNavigation demo={demo} />
      <main className="approvals-page" id="approval-inbox">
        <div className="approvals-page-heading"><h1>审批收件箱</h1><p>核对目标变更，再批准指定计划。</p></div>
        <div className="approvals-content"><ApprovalInbox demo={demo} /><PlanDetail demo={demo} /></div>
      </main>
      <footer className="approvals-footer"><button onClick={demo.refresh} aria-label="刷新本地演示状态"><ArrowClockwise size={18} aria-hidden="true" />最后同步：{demo.lastSync}</button></footer>
      {demo.notice && <div className="approvals-notice" role="status"><Info size={21} aria-hidden="true" /><span>{demo.notice}</span><button aria-label="关闭通知" onClick={demo.dismissNotice}><X size={18} aria-hidden="true" /></button></div>}
    </div>
  );
}
