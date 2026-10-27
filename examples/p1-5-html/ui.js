"use strict";
H.paths = {
  helm: "M12 3v18M3 12h18M5.6 5.6l12.8 12.8M5.6 18.4 18.4 5.6M12 6a6 6 0 1 0 0 12 6 6 0 0 0 0-12Z",
  grid: "M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z",
  layers: "m3 7 9-4 9 4-9 4-9-4Zm0 5 9 4 9-4M3 17l9 4 9-4",
  arrow: "M4 12h16m-6-6 6 6-6 6", plus: "M12 5v14M5 12h14",
  search: "M10.5 3a7.5 7.5 0 1 0 0 15 7.5 7.5 0 0 0 0-15ZM16 16l5 5",
  check: "m5 12 4 4L19 6", clock: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Zm0 4v5l3 2",
  bolt: "m13 2-9 12h7l-1 8 10-13h-8l1-7Z", file: "M5 3h9l5 5v13H5V3Zm9 0v6h5M8 13h8M8 17h5",
  link: "m10 13 4-4m-5-2 2-2a5 5 0 0 1 7 7l-2 2m-1 3-2 2a5 5 0 0 1-7-7l2-2",
  shield: "M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6l-8-3Zm-4 9 3 3 5-6",
  server: "M4 3h16v7H4zM4 14h16v7H4zM7 6h1M7 17h1M12 6h5M12 17h5",
  refresh: "M20 8a9 9 0 0 0-15-2L3 9m0-6v6h6m-5 7a9 9 0 0 0 15 2l2-3m0 6v-6h-6",
  close: "m6 6 12 12M6 18 18 6", terminal: "m4 6 6 6-6 6m9 0h7",
  pause: "M8 4v16M16 4v16", folder: "M3 6V4h7l2 3h9v13H3V6Z",
};
H.icon = name => `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${H.paths[name] || H.paths.file}"/></svg>`;
H.btn = (label, action, style = "", extra = "") => `<button type="button" class="btn ${style}" data-action="${action}" ${extra}>${label}</button>`;
H.go = (label, page, icon = "", extra = "") => `<button class="navlink ${H.state.page === page ? "selected" : ""}" data-page="${page}" ${extra}>${icon ? H.icon(icon) : ""}<span>${label}</span></button>`;
H.badge = (label, tone = "neutral") => `<span class="badge ${tone}"><i></i>${label}</span>`;
H.laneLabel = lane => ({ blocked: "等待核对", approval: "待批准", approved: "已批准 · 待执行", stopping: "停止待确认", queued: "等待资源", active: "推进中", ready: "待提交", done: "已完成" }[lane]);
H.laneTone = lane => ({ blocked: "warning", approval: "info", approved: "success", stopping: "warning", queued: "warning", active: "info", ready: "neutral", done: "success" }[lane]);
H.inLane = (task, lane) => task.lane === lane || (lane === "approval" && task.lane === "approved") || (lane === "blocked" && ["stopping", "queued"].includes(task.lane));
H.field = (name, value) => `<div class="field"><dt>${name}</dt><dd>${value}</dd></div>`;
H.writeAttr = () => H.lockReason() ? `disabled title="${H.lockReason()}"` : "";
H.queryAttr = () => !H.state.online ? 'disabled title="离线时无法查询最新结果"' : "";
H.brand = () => `<span class="brandmark">${H.icon("helm")}</span><b>CloudHelm</b>`;
H.connection = () => H.btn(`<i class="status-dot ${H.state.online ? "" : "offline"}"></i>${H.state.online ? "Hub 已连接" : "离线 · 只读"}`, "connection", "connection-btn");
H.rail = () => `<div class="concept-rail"><a href="index.html" class="rail-home">${H.icon("layers")} 方案总览</a><nav aria-label="界面方案">${H.concepts.map(([key, n, name]) => `<a href="${key}.html" class="${key === H.concept ? "current" : ""}" ${key === H.concept ? 'aria-current="page"' : ""}><span>${n}</span>${name}</a>`).join("")}</nav><span class="rail-note">本地演示</span></div>`;
H.notice = () => H.lockReason() ? `<div class="global-notice">${H.icon("shield")}<span>${H.lockReason()} · ${H.state.snapshot}</span>${H.btn("连接与同步", "sync", "small")}</div>` : "";
H.pageHeading = (overline, title, desc, action = "") => `<header class="page-heading"><div>${overline ? `<div class="eyebrow">${overline}</div>` : ""}<h1>${title}</h1>${desc ? `<p>${desc}</p>` : ""}</div>${action}</header>`;
H.panelHead = (title, action = "") => `<div class="panel-head"><h2>${title}</h2>${action}</div>`;
H.operation = (compact = false) => `<section class="operation-panel ${compact ? "compact" : ""}">
  <div class="op-top"><span class="eyebrow">当前阻塞</span>${H.badge(H.state.stopRequested ? "停止待确认" : "unknown", "warning")}</div>
  <div class="op-identity"><span class="op-symbol">${H.icon(H.state.stopRequested ? "pause" : "clock")}</span><div><h2>${H.state.stopRequested ? "取消已接收" : "归档传输待核对"}</h2><p>Op-218 · s2413 / 验证环境</p></div></div>
  <p class="op-description">${H.state.stopRequested ? "停止尚未确认" : H.state.queried ? "已查询，暂无新回执" : "传输中断，等待原操作结果"}</p>
  <div class="retained"><span>${H.icon("shield")} 资源仍保留</span><b>1 CPU</b><b>1 GiB</b><b>4 GiB 磁盘</b></div>
  <div class="actions">${H.btn(`${H.icon("refresh")}查询原操作`, "query", "primary", H.queryAttr())}${H.btn("取消任务", "cancel", "quiet", H.writeAttr() + ' data-selected="TASK-1042"' + (H.state.stopRequested ? " disabled" : ""))}</div>
</section>`;
H.taskCard = task => `<button class="task-card ${task.id === H.state.selected ? "focused" : ""}" data-task="${H.esc(task.id)}"><div class="card-id"><span>${H.esc(task.id)}</span><span>${task.time}</span></div><h3>${H.esc(task.title)}</h3><div class="task-card-bottom">${H.badge(H.laneLabel(task.lane), H.laneTone(task.lane))}<span>${task.plan !== "—" ? task.plan : "工程任务"}</span></div></button>`;
H.events = (limit = 8) => `<div class="event-list">${H.state.events.slice(0, limit).map((event, index) => `<button class="event" data-event-index="${index}" data-page="${event.page}" data-selected="${H.state.tasks.find(task => task.id === event.ref || task.plan === event.ref || task.command === event.ref)?.id || "TASK-1042"}"><span class="event-time">${event.time}</span><span class="event-node ${event.kind}"></span><span class="event-text"><small>${event.type}</small><b>${H.esc(event.title)}</b><span>${H.esc(event.detail)}</span><code>${H.esc(event.ref)}</code></span>${H.icon("arrow")}</button>`).join("")}</div>`;
H.boardInspector = () => {
  const t = H.task();
  if (t.id === "TASK-1042") return H.operation(true);
  return `<section class="task-inspector-body"><div class="op-top">${H.badge(H.laneLabel(t.lane), H.laneTone(t.lane))}</div><h2>${H.esc(t.title)}</h2><p class="body-copy">${H.esc(t.goal)}</p><dl class="fields single">${H.field("当前任务", t.id)}${H.field("原 Run", t.run)}${H.field("命令接收", t.command === "—" ? "尚未提交" : t.command + " · accepted")}${H.field("关联计划", t.plan)}</dl><div class="actions">${t.plan !== "—" ? H.go("审阅固定计划", "plan", "shield") : t.lane === "ready" ? H.btn("提交启动", "submit", "primary", H.writeAttr()) : ""}${t.lane !== "done" && !t.cancelled ? H.btn("取消任务", "cancel", "quiet", H.writeAttr()) : ""}</div></section>`;
};
H.tabs = pages => `<nav class="section-tabs" aria-label="内容导航">${pages.map(([label, page]) => H.go(label, page)).join("")}</nav>`;
H.resources = () => `<div class="resource-meter"><div><span>执行占用</span><b>1 / 2 槽</b></div><span class="meter-track"><i style="width:50%"></i></span></div><div class="resource-meter"><div><span>受管磁盘</span><b>4 / 16 GiB</b></div><span class="meter-track"><i style="width:25%"></i></span></div>`;
H.target = () => `<section class="panel"><div class="panel-head"><h2>环境版本</h2>${H.badge("最后观察 10:42", "neutral")}</div><div class="service-table"><div class="table-labels"><span>服务</span><span>期望版本</span><span>实际观察</span></div>${["frontend", "backend", "postgres"].map(name => `<div><strong>${name}</strong><code>v0.7.1</code><span>${H.badge(name === "postgres" ? "待观察" : "v0.7.0", name === "postgres" ? "warning" : "neutral")}</span></div>`).join("")}</div></section>`;
H.evidence = () => {
  const task = H.task();
  const items = [[task.id, task.title, "task"]];
  if (task.plan !== "—") items.push(["REL-071", "固定交付制品 v0.7.1", "release"], ["CFG-STAGING r4", "验证环境配置", "config"], [task.plan, "关联固定计划", "plan"]);
  if (task.id === "TASK-1042") items.push(["Op-218", "待核对的物理操作", "tracking"]);
  return `<section class="evidence"><div class="eyebrow">关联上下文</div>${items.map(([id, label, page]) => `<button data-page="${page}" data-selected="${task.id}">${H.icon("link")}<span><code>${id}</code><small>${H.esc(label)}</small></span>${H.icon("arrow")}</button>`).join("")}</section>`;
};
H.pages = {};
