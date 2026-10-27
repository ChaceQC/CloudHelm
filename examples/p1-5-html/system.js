"use strict";
H.pages.connection = () => `${H.pageHeading("", "连接与身份", "", H.connection())}
  <div class="content-grid"><section class="panel">${H.panelHead("当前控制会话", H.icon("shield"))}<dl class="fields">${H.field("操作者", "Chace · 本地示例")}${H.field("权限", H.state.role === "operator" ? "提交 / 查询 / 批准 / 取消" : "查看 / 查询")}${H.field("项目范围", "客户服务工作台")}${H.field("目标身份", "s2413 · 验证环境")}${H.field("控制通道", H.state.online ? "已连接 · 认证展示" : "已离线 · 只读")}${H.field("业务健康", "待独立观察")}${H.field("最后观察", "2026-10-26 10:42:18 CST")}${H.field("本机应急", "未配置 · 不可用")}</dl><div class="actions">${H.btn(H.state.online ? "模拟断开连接" : "重新连接并同步", H.state.online ? "offline" : "reconnect", "primary")}${H.btn(H.state.role === "operator" ? "模拟权限收回" : "恢复演示操作者", "toggle-role", "quiet")}</div></section>
  <div class="stack"><section class="panel"><h2>操作资格</h2><div class="permission-row"><span>读取最后快照</span>${H.badge("允许", "success")}</div><div class="permission-row"><span>控制查询</span>${H.badge(H.state.online ? "允许" : "离线不可用", H.state.online ? "success" : "warning")}</div><div class="permission-row"><span>提交、批准与取消</span>${H.badge(H.lockReason() ? "暂停" : "允许", H.lockReason() ? "warning" : "success")}</div><div class="permission-row"><span>启用本机应急</span>${H.badge("不可用", "neutral")}</div></section></div></div>`;
H.pages.sync = () => `${H.pageHeading("", "快照与事件", "", H.badge(H.state.gap ? "事件缺口 · 写入暂停" : H.state.online ? "快照已同步" : "最后同步快照", H.state.gap || !H.state.online ? "warning" : "success"))}
  <div class="sync-metrics"><div><span>快照身份</span><b>${H.state.snapshot}</b></div><div><span>业务流身份</span><b>${H.state.stream}</b></div><div><span>分发游标</span><b>${H.state.cursor}</b></div><div><span>写入资格</span><b>${H.lockReason() ? "暂停" : "可提交"}</b></div></div>
  <div class="toolbar"><div class="actions">${H.btn("模拟事件缺口", "gap", "quiet")}${H.btn(`${H.icon("refresh")}重建完整快照`, "snapshot", "primary", H.queryAttr())}</div></div>
  <section class="panel">${H.panelHead("业务事件", `<span class="muted">当前范围 · 客户服务工作台</span>`)}${H.events(12)}</section>`;
H.scenarios = [
  ["offline", "控制通道断开", "最后快照 · 只读", "link"],
  ["permission", "当前权限收回", "只读 · 可查询", "shield"],
  ["gap", "事件序列缺口", "暂停写入 · 重建快照", "layers"],
  ["worker", "单 worker 重启", "恢复原 Run", "server"],
  ["checkpoint", "提交后检查点缺失", "核对原命令", "file"],
  ["receipt", "接收回执丢失", "查询原接收记录", "refresh"],
  ["capacity", "模型与执行槽已满", "启动排队 · 查询与取消可用", "pause"],
  ["backup", "从旧备份恢复", "自动执行关闭", "clock"],
];
H.pages.recovery = () => `${H.pageHeading("", "同步与恢复", "", H.btn("恢复初始示例", "reset", "quiet"))}
  <div class="recovery-summary"><span>${H.icon("shield")}</span><div><h2>${H.state.backup ? "自动执行保持关闭" : H.state.capacity ? "容量已满 · 控制可用" : H.state.scenario === "normal" ? "正常" : "场景已应用"}</h2><p>RUN-1042 · Op-218 · ${H.state.stopRequested ? "停止待确认" : "结果 unknown"} · 资源保留</p></div>${H.btn("查询原操作", "query", "primary", H.queryAttr())}</div>
  <div class="scenario-grid">${H.scenarios.map(([id, title, desc, icon], i) => `<button class="scenario ${H.state.scenario === id ? "active" : ""}" data-scenario="${id}"><div><span class="scenario-icon">${H.icon(icon)}</span><small>0${i + 1}</small></div><h3>${title}</h3><p>${desc}</p><span class="scenario-action">${H.state.scenario === id ? "当前场景" : "模拟"}${H.icon("arrow")}</span></button>`).join("")}</div>
`;
