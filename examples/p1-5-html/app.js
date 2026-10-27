"use strict";
H.pageName = () => ({ home: "工作台", tasks: "任务", task: H.task().id, release: "交付制品", config: "环境配置", plan: "部署计划", tracking: "执行跟踪", connection: "连接与身份", sync: "快照与事件", recovery: "同步与恢复" }[H.state.page]);
H.content = () => (H.pages[H.state.page] || H.pages.task)();
H.render = () => { document.getElementById("app").innerHTML = H.rail() + H.notice() + H.layouts[H.concept](); };
H.toast = message => {
  const toast = document.getElementById("toast");
  toast.textContent = message;
  toast.classList.add("visible");
  clearTimeout(H.toastTimer);
  H.toastTimer = setTimeout(() => toast.classList.remove("visible"), 4700);
};
H.modal = document.getElementById("modal");
H.dialog = (title, body, overline = "") => {
  H.modal.innerHTML = `<header class="dialog-heading"><div>${overline ? `<div class="eyebrow">${overline}</div>` : ""}<h2>${title}</h2></div>${H.btn(H.icon("close"), "close", "quiet", 'aria-label="关闭对话框"')}</header>${body}`;
  if (!H.modal.open) H.modal.showModal();
};
H.create = () => {
  if (H.lockReason()) return H.toast(H.lockReason());
  H.dialog("创建任务", `<form id="create-form"><label>任务名称<input name="title" required maxlength="64" placeholder="例如：完善客户筛选条件" autofocus></label><label>目标与完成依据<textarea name="goal" required maxlength="500" placeholder="说明期望行为，以及如何确认它已完成"></textarea></label><div class="form-row"><label>项目<input value="客户服务工作台" readonly></label><label>模型预算上限 / 元<input name="budget" type="number" required min="0.01" max="9999" step="0.01" value="10.00"></label></div><div class="dialog-actions">${H.btn("返回", "close", "quiet")}<button class="btn primary" type="submit">创建任务草稿</button></div></form>`);
};
H.submitTask = () => {
  if (H.lockReason()) return H.toast(H.lockReason());
  const task = H.task();
  if (task.lane !== "ready" || task.command !== "—" || task.cancelled) return H.toast("当前任务不可重复启动。");
  task.command = "CMD-" + task.id.slice(5);
  task.run = "RUN-" + task.id.slice(5);
  task.lane = H.state.capacity ? "queued" : "active";
  if (H.state.capacity) task.goal = "命令已接收，等待资源。";
  H.event("启动命令已接收", task.command + " · accepted", task.id, "task");
  H.render();
  H.toast("命令已接收 · accepted");
};
H.cancel = () => {
  if (H.lockReason()) return H.toast(H.lockReason());
  const task = H.task();
  if (task.cancelled || task.lane === "done") return H.toast("当前任务不可再次取消。");
  H.dialog("取消任务", `<p class="dialog-body">取消后等待停止确认，资源暂时保留。</p><div class="dialog-fact"><b>${H.esc(task.id)}</b> · ${H.esc(task.title)}<br>${task.id === "TASK-1042" ? "关联 Op-218 · 当前结果 unknown" : "无关联 Operation"}</div><form id="cancel-form" data-task-id="${task.id}"><label>取消原因<textarea name="reason" required minlength="3" maxlength="300" placeholder="说明取消原因，至少 3 个字"></textarea></label><div class="dialog-actions">${H.btn("继续等待", "close", "quiet")}<button type="submit" class="btn primary">提交取消请求</button></div></form>`);
};
H.query = () => {
  if (!H.state.online) return H.toast("当前离线，只能查看最后快照。");
  H.state.queried = true;
  H.event("原操作核对已返回", "暂无新回执 · 资源保留", "Op-218", "tracking", "warning");
  H.render();
  H.dialog("Op-218 查询结果", `<div class="dialog-fact">${H.badge(H.state.stopRequested ? "停止待确认" : "unknown", "warning")}<p class="dialog-body">暂无新回执 · 资源保留</p></div><dl class="fields">${H.field("原 Run", "RUN-1042")}${H.field("可靠接收记录", "CMD-1042 · accepted")}${H.field("原 Operation", "Op-218")}${H.field("物理停止", "尚未确认")}</dl><div class="dialog-actions">${H.btn("关闭", "close", "quiet")}${H.btn("查看完整跟踪", "open-tracking", "primary")}</div>`);
};
H.approve = button => {
  if (H.lockReason()) return H.toast(H.lockReason());
  const plan = H.plan();
  if (plan.approved || !document.getElementById("approve-check")?.checked || button.dataset.digest !== plan.digest || plan.id !== "PLAN-083") return;
  H.state.approved = true;
  H.state.tasks.find(task => task.id === "TASK-1041").lane = "approved";
  H.event("PLAN-083 的固定摘要已批准", "REL-071 / CFG-STAGING r4 · 待执行", "PLAN-083", "plan", "success");
  H.render();
  H.toast("计划已批准 · 待执行");
};
H.reconnect = () => {
  H.state.online = true;
  H.state.gap = false;
  H.state.snapshot = "SNAP-" + String(Number(H.state.snapshot.slice(5)) + 1).padStart(3, "0");
  H.event("重连后取得完整快照", "Op-218 仍待核对 · 资源保留", H.state.snapshot, "sync");
  H.render();
  H.toast(H.state.backup ? "快照已重建 · 自动执行仍关闭" : "快照已重建");
};
H.palette = () => {
  H.dialog("搜索", '<input id="palette-input" class="palette-input" placeholder="搜索任务、计划、连接或恢复…" aria-label="搜索对象与操作" autofocus><div id="palette-results" class="palette-results"></div><p class="fineprint">按 Tab 选择结果，Enter 打开，Esc 返回。</p>', "Ctrl K");
  H.paletteResults("");
};
H.paletteResults = query => {
  const items = [
    ...H.state.tasks.map(task => ({ name: task.title, detail: task.id, page: "task", selected: task.id, icon: "file" })),
    ...[["PLAN-083 · 待审阅计划", "plan", "shield", "TASK-1041"], ["PLAN-082 · 原操作计划", "plan", "shield", "TASK-1042"], ["Op-218 · 原操作跟踪", "tracking", "clock"], ["REL-071 · 交付制品", "release", "layers"], ["CFG-STAGING · 环境配置", "config", "server"], ["连接与身份", "connection", "link"], ["快照与事件", "sync", "file"], ["同步与恢复场景", "recovery", "refresh"]].map(([name, page, icon, selected]) => ({ name, detail: "客户服务工作台", page, icon, selected })),
  ];
  document.getElementById("palette-results").innerHTML = items.filter(item => (item.name + item.detail).toLowerCase().includes(query.toLowerCase())).map(item => `<button class="palette-item" data-page="${item.page}" ${item.selected ? `data-selected="${item.selected}"` : ""}>${H.icon(item.icon)}<span><b>${H.esc(item.name)}</b><small>${H.esc(item.detail)}</small></span>${H.icon("arrow")}</button>`).join("") || '<p class="empty-state">没有匹配对象。</p>';
};
H.readEvent = button => {
  const item = H.state.events[Number(button.dataset.eventIndex)];
  H.dialog(H.esc(item.title), `<div class="dialog-fact">${H.esc(item.type)} · ${item.time} CST<br><code>${H.esc(item.ref)}</code></div><p class="dialog-body">${H.esc(item.detail)}</p><div class="dialog-actions">${H.btn("返回卷宗", "close", "quiet")}<button class="btn primary" data-page="${item.page}">打开关联对象 ${H.icon("arrow")}</button></div>`);
};
H.actions = {
  close: () => H.modal.close(), create: H.create, submit: H.submitTask, cancel: H.cancel, query: H.query,
  palette: H.palette, approve: H.approve, reset: () => location.reload(),
  "review-next": () => H.nav("plan", "TASK-1041"),
  "pick-plan": () => H.nav("plan"),
  "open-tracking": () => { H.modal.close(); H.nav("tracking", "TASK-1042"); },
  "scroll-events": () => document.getElementById("today-events")?.scrollIntoView({ behavior: "smooth" }),
  offline: () => H.applyScenario("offline"), gap: () => H.applyScenario("gap"), reconnect: H.reconnect,
  snapshot: () => H.state.online ? H.reconnect() : H.toast("请先重新连接 Hub。"),
  "toggle-role": () => { H.state.role = H.state.role === "operator" ? "reader" : "operator"; H.render(); H.toast("权限已更新"); },
  "save-config": () => {
    if (H.lockReason()) return H.toast(H.lockReason());
    const form = document.getElementById("config-form");
    if (!form.reportValidity()) return;
    const data = new FormData(form);
    H.state.configLevel = String(data.get("level"));
    H.state.configPool = Number(data.get("pool"));
    H.state.configRevision += 1;
    H.event("新配置修订已建立", `CFG-STAGING r${H.state.configRevision} · 待生成计划`, "CFG-STAGING", "config");
    H.render(); H.toast("配置修订已创建");
  },
  completed: () => { H.state.filter = "done"; H.nav("tasks"); },
  filter: button => { H.state.filter = button.dataset.filter; H.render(); },
};
document.addEventListener("click", event => {
  const button = event.target.closest("button");
  if (!button || button.disabled) return;
  if (button.dataset.selected) H.state.selected = button.dataset.selected;
  if (H.concept === "dossier" && H.state.page === "home" && button.dataset.eventIndex !== undefined) return H.readEvent(button);
  if (button.dataset.page) { if (H.modal.open) H.modal.close(); return H.nav(button.dataset.page); }
  if (button.dataset.task) {
    if (H.concept === "board" && H.state.page === "home") { H.state.selected = button.dataset.task; return H.render(); }
    return H.nav(H.concept === "atlas" ? "home" : "task", button.dataset.task);
  }
  if (button.dataset.scenario) return H.applyScenario(button.dataset.scenario);
  const action = button.dataset.action;
  if (H.actions[action]) return H.actions[action](button);
  if (H.pages[action] || action === "home") H.nav(action);
});
document.addEventListener("input", event => {
  const input = event.target;
  if (input.id === "palette-input") return H.paletteResults(input.value);
  if (input.dataset.input === "search") {
    H.state.search = input.value;
    const caret = input.selectionStart;
    H.render();
    const next = document.querySelector('[data-input="search"]');
    next.focus(); next.setSelectionRange(caret, caret);
  }
});
document.addEventListener("change", event => {
  if (event.target.id === "approve-check") document.querySelector('[data-action="approve"]').disabled = !event.target.checked || !!H.lockReason();
});
document.addEventListener("submit", event => {
  const form = event.target;
  event.preventDefault();
  if (H.lockReason()) { H.modal.close(); return H.toast(H.lockReason()); }
  const data = new FormData(form);
  if (form.id === "create-form") {
    const id = "TASK-" + (Math.max(...H.state.tasks.map(task => Number(task.id.slice(5)))) + 1);
    H.state.tasks.unshift({ id, title: String(data.get("title")).trim(), goal: String(data.get("goal")).trim(), lane: "ready", plan: "—", run: "—", command: "—", time: "刚刚", budget: Number(data.get("budget")).toFixed(2) });
    H.event("新任务草稿已创建", "待提交", id, "task");
    H.modal.close(); H.nav("task", id); H.toast("任务草稿已创建");
  }
  if (form.id === "cancel-form") {
    const task = H.state.tasks.find(item => item.id === form.dataset.taskId);
    if (!task || task.cancelled) return;
    task.cancelled = true;
    task.lane = "stopping";
    if (task.id === "TASK-1042") H.state.stopRequested = true;
    H.event("取消请求已接收", String(data.get("reason")) + "；停止待确认 · 资源保留", task.id, "task", "warning");
    H.modal.close(); H.render(); H.toast("取消已接收 · 停止待确认");
  }
});
document.addEventListener("keydown", event => {
  const editing = event.target.matches("input,textarea,select");
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") { event.preventDefault(); H.palette(); }
  if (!editing && !H.modal.open && event.key.toLowerCase() === "n") { event.preventDefault(); H.create(); }
  if (!editing && !H.modal.open && event.key === "/") { event.preventDefault(); H.palette(); }
});
H.modal.addEventListener("click", event => { if (event.target === H.modal) { const r = H.modal.getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) H.modal.close(); } });
H.render();
