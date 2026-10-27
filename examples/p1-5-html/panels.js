"use strict";
H.plan = () => H.task().id === "TASK-1041" ? {
  id: "PLAN-083", approved: H.state.approved,
  digest: "8c4cce846e1e36c7d4ef10f275307b861176c6e270d2f9c815bd29aaedb34f20",
} : { id: "PLAN-082", approved: true, digest: "7a2f0b19c3d4e5f60817293a4b5c6d7e8f9012a3b4c5d6e7f8091a2b3c4d5e6f" };
H.pages.tasks = () => `${H.pageHeading("", "任务", "", H.btn(`${H.icon("plus")}创建任务`, "create", "primary", H.writeAttr()))}
  <div class="toolbar"><label class="search-field">${H.icon("search")}<input data-input="search" placeholder="搜索任务、编号或目标" aria-label="搜索任务" value="${H.esc(H.state.search)}"></label><div class="filter-group">${[["all", "全部"], ["blocked", "需要处理"], ["active", "推进中"], ["ready", "待提交"]].map(([id, name]) => H.btn(name, "filter", H.state.filter === id ? "small active" : "small quiet", `data-filter="${id}"`)).join("")}</div></div>
  <div class="task-grid">${H.filteredTasks().map(H.taskCard).join("") || '<div class="empty-state">没有匹配的任务，试试其他关键词。</div>'}</div>`;
H.filteredTasks = () => H.state.tasks.filter(t => (H.state.filter === "all" || H.inLane(t, H.state.filter)) && (t.title + t.id + t.goal).toLowerCase().includes(H.state.search.toLowerCase()));
H.pages.task = () => {
  const t = H.task();
  return `${H.pageHeading(t.id, H.esc(t.title), "", H.badge(t.cancelled ? "停止待确认" : H.laneLabel(t.lane), t.cancelled ? "warning" : H.laneTone(t.lane)))}
    <div class="content-grid"><div class="stack"><section class="panel">${H.panelHead("目标与推进", H.badge("控制修订 r3", "neutral"))}<p class="body-copy">${H.esc(t.goal)}</p><dl class="fields">${H.field("Task", `<code>${t.id}</code>`)}${H.field("原 Run", `<code>${t.run}</code>`)}${H.field("命令接收", t.command === "—" ? "尚未提交" : `<code>${t.command}</code> · accepted`)}${H.field("模型预算上限", `¥ ${t.budget}`)}${H.field("供应商费用", "待核对 · usage 尚不完整")}${H.field("关联计划", t.plan)}</dl>
    <div class="actions">${t.lane === "ready" && !t.cancelled ? H.btn("提交启动", "submit", "primary", H.writeAttr()) : ""}${t.plan !== "—" ? H.go("查看固定计划", "plan", "file") : ""}${!t.cancelled && t.lane !== "done" ? H.btn("取消任务", "cancel", "quiet", H.writeAttr()) : ""}</div></section>
    ${t.id === "TASK-1042" ? H.operation() : `<section class="panel">${H.panelHead("当前事实")}<div class="fact-row">${H.icon(t.cancelled ? "pause" : "clock")}<p>${t.cancelled ? "取消已接收 · 停止待确认 · 资源保留" : t.command !== "—" ? "命令已接收" : "暂无执行回执"}</p></div></section>`}</div><div class="stack"><section class="panel">${H.panelHead("固定输入")}<dl class="fields single">${H.field("需求", "REQ-014 · r3")}${H.field("候选", "CAND-071 · 4a04b84")}${H.field("验收资产", "ACC-014 · r2")}${H.field("输入集", "INPUT-071 · 已固定")}</dl></section>${t.id === "TASK-1042" ? H.evidence() : ``}</div></div>`;
};
H.pages.release = () => `${H.pageHeading("", "交付制品", "", H.badge("REL-071 · 已归档", "success"))}
  <div class="release-hero"><span class="release-monogram">R</span><div><h2>v0.7.1</h2><p>客户服务工作台 · 固定候选 4a04b84</p></div>${H.go("查看部署计划", "plan", "arrow", 'data-selected="TASK-1041"')}</div>
  <div class="triple-grid">${[["frontend", "React · 静态站点", "65.6 MB", "65a7…e21b"], ["backend", "FastAPI · 应用服务", "26.1 MB", "30bd…492c"], ["postgres", "PostgreSQL · 数据服务", "160.2 MB", "98fc…b270"]].map(([name, desc, size, digest]) => `<section class="panel artifact"><span class="artifact-icon">${H.icon(name === "postgres" ? "server" : "layers")}</span><h2>${name}</h2><p>${desc}</p><dl class="fields single">${H.field("归档大小", size)}${H.field("内容摘要", `<code>${digest}</code>`)}</dl>${H.badge("内容已固定", "success")}</section>`).join("")}</div>
  <section class="panel">${H.panelHead("运行契约与适用证据")}<dl class="fields">${H.field("Compose", "受限子集 · 解析通过")}${H.field("配置 schema", "app-config/v1")}${H.field("迁移策略", "线性迁移 · 需后置核验")}${H.field("自动验证", "固定候选的演示验证报告")}${H.field("人工产品验收", "待执行")}${H.field("适用环境", "Linux x86_64 · 验证环境")}</dl></section>`;
H.pages.config = () => `${H.pageHeading("", "环境配置", "", H.badge(`CFG-STAGING · r${H.state.configRevision}`, "info"))}
  <div class="content-grid"><section class="panel">${H.panelHead("验证环境 / s2413")}
  <dl class="fields">${H.field("配置修订", `r${H.state.configRevision}`)}${H.field("关联制品", "REL-071 · v0.7.1")}${H.field("服务监听", "8080 / 受控入口")}${H.field("副本数", "frontend 1 · backend 1")}${H.field("CPU / 内存", "1 CPU / 1 GiB")}${H.field("数据保留", "4 GiB")}</dl>
  <form id="config-form"><div class="form-row"><label>应用日志级别<select name="level">${["info", "warning", "error"].map(level => `<option ${H.state.configLevel === level ? "selected" : ""}>${level}</option>`).join("")}</select></label><label>连接池上限<input name="pool" type="number" min="1" max="20" value="${H.state.configPool}" required></label></div><p class="fineprint">新修订需重新生成部署计划。</p>${H.btn("创建配置修订", "save-config", "primary", H.writeAttr())}</form></section>
  <div class="stack"><section class="panel">${H.panelHead("受管秘密引用", H.icon("shield"))}<dl class="fields single">${H.field("DATABASE_PASSWORD", "数据库凭据 · 受管引用")}${H.field("APP_SIGNING_KEY", "应用签名 · 受管引用")}</dl></section><section class="panel"><h2>关联计划</h2><dl class="fields single">${H.field("PLAN-082 / PLAN-083", "CFG-STAGING r4")}</dl>${H.go("查看固定计划", "plan", "arrow")}</section></div></div>`;
H.pages.plan = () => {
  const p = H.plan();
  return `${H.pageHeading("", "部署计划", "", H.badge(p.approved ? "已批准" : "待批准", p.approved ? "success" : "warning"))}
  <div class="plan-picker">${H.btn("PLAN-082 · 已批准 / 待核对", "pick-plan", H.task().id !== "TASK-1041" ? "active" : "quiet", 'data-selected="TASK-1042"')}${H.btn("PLAN-083 · 通知中心更新", "pick-plan", H.task().id === "TASK-1041" ? "active" : "quiet", 'data-selected="TASK-1041"')}</div>
  <div class="content-grid"><div class="stack"><section class="panel">${H.panelHead(p.id + " · 验证环境", H.badge("固定输入", "neutral"))}
  <div class="version-diff"><div><small>环境起点</small><strong>v0.7.0</strong><span>配置 r3 · generation 12</span></div>${H.icon("arrow")}<div><small>期望状态</small><strong>v0.7.1</strong><span>配置 r4 · 新部署代次</span></div></div>
  <dl class="fields">${H.field("目标", "s2413 / 验证环境")}${H.field("制品", "REL-071 · 已固定")}${H.field("配置", "CFG-STAGING r4")}${H.field("迁移", "0007 → 0008 · 需核对")}${H.field("计划有效期", "2026-10-26 18:00 CST")}${H.field("批准人", p.approved ? "Chace · 当前计划摘要" : "等待当前有权操作者")}</dl></section>
  <section class="panel"><h2>变更影响</h2><div class="impact-row"><b>短暂停机</b><p>backend 替换期间暂不可用。</p></div><div class="impact-row"><b>数据迁移</b><p>线性迁移，完成后核验数据库修订。</p></div><div class="impact-row"><b>补偿范围</b><p>应用可回退，数据不自动回滚。</p></div></section></div>
  <section class="panel approval-panel"><div class="eyebrow">${p.id}</div><h2>${p.approved ? "批准记录" : "批准计划"}</h2><label class="digest-label">完整计划摘要</label><code class="digest">${p.digest}</code>
  ${p.approved ? `<div class="approval-record">${H.icon("check")}<div><b>当前摘要已批准</b><p>${p.id} · CFG-STAGING r4</p></div></div>${H.go("查看执行跟踪", "tracking", "arrow", 'data-selected="TASK-1042"')}` : `<label class="checkbox-label"><input id="approve-check" type="checkbox" ${H.writeAttr()}>我已核对目标、环境起点、配置、迁移影响和完整摘要</label>${H.btn("批准计划", "approve", "primary full", 'disabled data-digest="' + p.digest + '"')}`}</section></div>`;
};
H.pages.tracking = () => `${H.pageHeading("", "部署跟踪", "", H.badge("PLAN-082 · Op-218", "neutral"))}
  <div class="step-strip"><div class="complete"><b>01</b><span>命令接收<small>CMD-1042 · accepted</small></span></div><div class="complete"><b>02</b><span>计划批准<small>PLAN-082 · 已批准</small></span></div><div class="current"><b>03</b><span>物理执行<small>${H.state.stopRequested ? "停止待确认" : "Op-218 · unknown"}</small></span></div><div><b>04</b><span>后置核验<small>尚未开始</small></span></div></div>
  <div class="content-grid"><div class="stack">${H.operation()}${H.target()}</div><section class="panel">${H.panelHead("事实与回执")}${H.events(5)}</section></div>`;
