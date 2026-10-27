"use strict";
window.Helm = {
  concept: document.body.dataset.concept,
  concepts: [
    ["board", "01", "任务看板"],
    ["voyage", "02", "部署航线"],
    ["atlas", "03", "对象工作台"],
    ["dossier", "04", "事件卷宗"],
    ["command", "05", "命令中心"],
  ],
  state: {
    page: "home", selected: "TASK-1042", filter: "all", search: "", role: "operator",
    online: true, gap: false, backup: false, capacity: false, cursor: 1842,
    snapshot: "SNAP-042", stream: "stream-A", scenario: "normal", queried: false,
    stopRequested: false, approved: false, configRevision: 4, configLevel: "info", configPool: 5,
    tasks: [
      { id: "TASK-1042", title: "交付客户服务工作台", goal: "核对归档传输的原操作结果，再决定后续交付。", lane: "blocked", plan: "PLAN-082", run: "RUN-1042", command: "CMD-1042", time: "10:42", budget: "12.00" },
      { id: "TASK-1041", title: "发布通知中心更新", goal: "审阅通知中心 v0.7.1 的固定部署计划。", lane: "approval", plan: "PLAN-083", run: "—", command: "—", time: "10:30", budget: "8.50" },
      { id: "TASK-1040", title: "构建订单管理模块", goal: "按固定输入构建独立候选，等待当前构建结果。", lane: "active", plan: "—", run: "RUN-1040", command: "CMD-1040", time: "10:26", budget: "6.00" },
      { id: "TASK-1039", title: "补充数据导出验收说明", goal: "补充实际结果、输入与支持范围。", lane: "ready", plan: "—", run: "—", command: "—", time: "09:58", budget: "4.00" },
      { id: "TASK-1038", title: "更新登录页文案", goal: "已归档候选与验证报告，任务完成。", lane: "done", plan: "—", run: "RUN-1038", command: "CMD-1038", time: "09:20", budget: "3.00" },
    ],
    events: [
      { time: "10:42:18", kind: "warning", title: "归档传输结果未知", detail: "连接中断 · 资源保留", ref: "Op-218", page: "tracking", type: "操作事实" },
      { time: "10:41:03", kind: "success", title: "固定计划已获批准", detail: "CFG-STAGING r4", ref: "PLAN-082", page: "plan", type: "人类决定" },
      { time: "10:40:56", kind: "info", title: "启动命令已接收", detail: "RUN-1042 · accepted", ref: "CMD-1042", page: "task", type: "命令回执" },
      { time: "10:38:10", kind: "success", title: "交付制品已归档", detail: "v0.7.1 · frontend / backend / postgres", ref: "REL-071", page: "release", type: "交付事实" },
      { time: "10:35:24", kind: "info", title: "环境配置修订已固定", detail: "验证环境 · r4", ref: "CFG-STAGING", page: "config", type: "配置修订" },
    ],
  },
};
const H = window.Helm;
H.esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
H.task = () => H.state.tasks.find(task => task.id === H.state.selected) || H.state.tasks[0];
H.lockReason = () => !H.state.online ? "离线 · 只读" : H.state.role !== "operator" ? "当前身份只读" : H.state.gap ? "事件缺口 · 请重建快照" : H.state.backup ? "旧备份 · 执行关闭" : "";
H.event = (title, detail, ref, page, kind = "info") => {
  H.state.cursor += 1;
  H.state.events.unshift({ time: new Date().toLocaleTimeString("zh-CN", { hour12: false, timeZone: "Asia/Shanghai" }), title, detail, ref, page, kind, type: "本次操作" });
};
H.nav = (page, selected) => {
  if (selected) H.state.selected = selected;
  H.state.page = page;
  H.state.search = "";
  H.render();
  window.scrollTo({ top: 0, behavior: "instant" });
};
H.applyScenario = id => {
  const s = H.state;
  s.scenario = id;
  if (id === "offline") s.online = false;
  if (id === "permission") s.role = "reader";
  if (id === "gap") s.gap = true;
  if (id === "backup") { s.backup = true; s.stream = "stream-B"; }
  if (id === "capacity") s.capacity = true;
  const notices = {
    normal: ["正常控制通道", "原操作待核对。"],
    offline: ["控制通道已断开", "已离线，写入暂停。"],
    permission: ["当前权限已收回", "权限已收回，当前只读。"],
    gap: ["增量事件出现缺口", "事件缺口，等待重建快照。"],
    worker: ["单 worker 重启后恢复原 Run", "RUN-1042 / Op-218 已恢复关联。"],
    checkpoint: ["业务已提交，检查点待核对", "CMD-1042 已提交，等待检查点核对。"],
    receipt: ["接收回执丢失", "CMD-1042 回执待查询。"],
    capacity: ["普通执行容量已满", "启动等待资源；查询和取消可用。"],
    backup: ["检测到旧备份恢复", "自动执行关闭，等待管理员核对。"],
  };
  const notice = notices[id];
  H.event(notice[0], notice[1], "RUN-1042", "recovery", id === "normal" ? "info" : "warning");
  H.render();
  H.toast(notice[1]);
};
