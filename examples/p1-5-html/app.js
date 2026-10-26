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
H.dialog = (title, body, overline = "CLOUDHELM / CONTROL") => {
  H.modal.innerHTML = `<header class="dialog-heading"><div><div class="eyebrow">${overline}</div><h2>${title}</h2></div>${H.btn(H.icon("close"), "close", "quiet", 'aria-label="关闭对话框"')}</header>${body}`;
  if (!H.modal.open) H.modal.showModal();
};
H.create = () => {
  if (H.lockReason()) return H.toast(H.lockReason());
  H.dialog("从一个清晰的目标开始", `<form id="create-form"><label>任务名称<input name="title" required maxlength="64" placeholder="例如：完善客户筛选条件" autofocus></label><label>目标与完成依据<textarea name="goal" required maxlength="500" placeholder="说明期望行为，以及如何确认它已完成"></textarea></label><div class="form-row"><label>项目<input value="客户服务工作台" readonly></label><label>模型预算上限 / 元<input name="budget" type="number" required min="0.01" max="9999" step="0.01" value="10.00"></label></div><p class="fineprint">先创建任务草稿，再显式提交启动。每个任务使用独立命令与执行身份。</p><div class="dialog-actions">${H.btn("返回", "close", "quiet")}<button class="btn primary" type="submit">创建任务草稿</button></div></form>`, "NEW TASK / 01");
};
H.submitTask = () => {
  if (H.lockReason()) return H.toast(H.lockReason());
  const task = H.task();
  if (task.lane !== "ready" || task.command !== "—" || task.cancelled) return H.toast("当前任务已有命令或不满足启动条件，请核对原对象。");
  task.command = "CMD-" + task.id.slice(5);
  task.run = "RUN-" + task.id.slice(5);
  task.lane = H.state.capacity ? "queued" : "active";
  if (H.state.capacity) task.goal = "启动命令已接收，等待执行资源；尚无物理执行。";
  H.event("启动命令已接收", task.command + " · accepted；等待业务推进与独立执行结果。", task.id, "task");
  H.render();
  H.toast("命令已接收（accepted），任务尚未完成。");
};
H.cancel = () => {
  if (H.lockReason()) return H.toast(H.lockReason());
  const task = H.task();
  if (task.cancelled || task.lane === "done") return H.toast("当前任务无法再次提交取消。");
  H.dialog("申请取消当前任务", `<p class="dialog-body">取消将阻止普通推进，已启动的执行仍需确认停止。未知占用继续保留。</p><div class="dialog-fact"><b>${H.esc(task.id)}</b> · ${H.esc(task.title)}<br>${task.id === "TASK-1042" ? "关联 Op-218 · 当前结果 unknown" : "仅操作当前任务，不关联其他任务的 Operation"}</div><form id="cancel-form" data-task-id="${task.id}"><label>取消原因<textarea name="reason" required minlength="3" maxlength="300" placeholder="说明取消原因，至少 3 个字"></textarea></label><div class="dialog-actions">${H.btn("继续等待", "close", "quiet")}<button type="submit" class="btn primary">提交取消请求</button></div></form>`, "CANCELLATION / REQUEST");
};
H.query = () => {
  if (!H.state.online) return H.toast("当前离线，只能查看最后快照。");
  H.state.queried = true;
  H.event("原操作核对已返回", "Op-218 仍未取得物理结果；原 RUN-1042 与冲突占用保持不变。", "Op-218", "tracking", "warning");
  H.render();
  H.dialog("已查询原操作 Op-218", `<div class="dialog-fact">${H.badge(H.state.stopRequested ? "停止待确认" : "unknown", "warning")}<p class="dialog-body">暂无新的物理回执。原执行身份、请求摘要和资源占用均保留。</p></div><dl class="fields">${H.field("原 Run", "RUN-1042")}${H.field("可靠接收记录", "CMD-1042 · accepted")}${H.field("原 Operation", "Op-218")}${H.field("物理停止", "尚未确认")}</dl><p class="dialog-body">本次没有创建新 Operation，也没有重放传输。${H.state.capacity ? "模型/执行槽已满，控制查询仍然可用。" : ""}</p><div class="dialog-actions">${H.btn("关闭", "close", "quiet")}${H.btn("查看完整跟踪", "open-tracking", "primary")}</div>`, "RECONCILIATION / ORIGINAL IDENTITY");
};
H.approve = button => {
  if (H.lockReason()) return H.toast(H.lockReason());
  const plan = H.plan();
  if (plan.approved || !document.getElementById("approve-check")?.checked || button.dataset.digest !== plan.digest || plan.id !== "PLAN-083") return;
  H.state.approved = true;
  H.state.tasks.find(task => task.id === "TASK-1041").lane = "approved";
  H.event("PLAN-083 的固定摘要已批准", "批准绑定 REL-071 / CFG-STAGING r4；尚无物理执行，部署未完成。", "PLAN-083", "plan", "success");
  H.render();
  H.toast("当前固定计划已批准。部署尚未启动，执行结果仍需单独核对。");
};
H.reconnect = () => {
  H.state.online = true;
  H.state.gap = false;
  H.state.snapshot = "SNAP-" + String(Number(H.state.snapshot.slice(5)) + 1).padStart(3, "0");
  H.event("重连后取得完整快照", "授权范围已重新投影，原 Op-218 的未知与资源保留不变。", H.state.snapshot, "sync");
  H.render();
  H.toast(H.state.backup ? "新快照已取得；旧备份执行门禁仍然关闭。" : "完整快照已重建，接续当前业务流。未知结果保持原状。");
};
H.palette = () => {
  H.dialog("转到对象，或执行一个动作", '<input id="palette-input" class="palette-input" placeholder="搜索任务、计划、连接或恢复…" aria-label="搜索对象与操作" autofocus><div id="palette-results" class="palette-results"></div><p class="fineprint">按 Tab 选择结果，Enter 打开，Esc 返回。</p>', "COMMAND / CTRL K");
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
  H.dialog(H.esc(item.title), `<div class="dialog-fact">${H.esc(item.type)} · ${item.time} CST<br><code>${H.esc(item.ref)}</code></div><p class="dialog-body">${H.esc(item.detail)}</p><p class="fineprint">从原记录查看关联对象；记录中的命令、决定与物理事实各自保留。</p><div class="dialog-actions">${H.btn("返回卷宗", "close", "quiet")}<button class="btn primary" data-page="${item.page}">打开关联对象 ${H.icon("arrow")}</button></div>`, "RECORD / SOURCE FACT");
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
  "toggle-role": () => { H.state.role = H.state.role === "operator" ? "reader" : "operator"; H.render(); H.toast("本地示例权限已更新，操作资格重新核对。"); },
  "save-config": () => {
    if (H.lockReason()) return H.toast(H.lockReason());
    const form = document.getElementById("config-form");
    if (!form.reportValidity()) return;
    const data = new FormData(form);
    H.state.configLevel = String(data.get("level"));
    H.state.configPool = Number(data.get("pool"));
    H.state.configRevision += 1;
    H.event("新配置修订已建立", `CFG-STAGING r${H.state.configRevision}；原计划继续固定 r4，未重新部署。`, "CFG-STAGING", "config");
    H.render(); H.toast("已创建新配置修订，原计划的固定输入不变。");
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
    H.event("新任务草稿已创建", "尚未提交命令，没有创建物理执行。", id, "task");
    H.modal.close(); H.nav("task", id); H.toast("任务草稿已创建。确认目标后可提交启动。");
  }
  if (form.id === "cancel-form") {
    const task = H.state.tasks.find(item => item.id === form.dataset.taskId);
    if (!task || task.cancelled) return;
    task.cancelled = true;
    task.lane = "stopping";
    if (task.id === "TASK-1042") H.state.stopRequested = true;
    H.event("取消请求已接收", String(data.get("reason")) + "；停止仍待确认，相关资源保留。", task.id, "task", "warning");
    H.modal.close(); H.render(); H.toast("取消请求已接收。物理停止尚未确认，资源继续保留。");
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
