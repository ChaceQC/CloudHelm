"use strict";
H.pages.connection = () => `${H.pageHeading("CONTROL / CONNECTION & IDENTITY", "连接与身份", "管理连接、权限与最后观察时间；控制通道和业务健康分别显示。", H.connection())}
  <div class="content-grid"><section class="panel">${H.panelHead("当前控制会话", H.icon("shield"))}<dl class="fields">${H.field("操作者", "Chace · 本地示例")}${H.field("权限", H.state.role === "operator" ? "提交 / 查询 / 批准 / 取消" : "查看 / 查询")}${H.field("项目范围", "客户服务工作台")}${H.field("目标身份", "s2413 · 验证环境")}${H.field("控制通道", H.state.online ? "已连接 · 认证展示" : "已离线 · 只读")}${H.field("业务健康", "待独立观察")}${H.field("最后观察", "2026-10-26 10:42:18 CST")}${H.field("本机应急", "未配置 · 不可用")}</dl><div class="actions">${H.btn(H.state.online ? "模拟断开连接" : "重新连接并同步", H.state.online ? "offline" : "reconnect", "primary")}${H.btn(H.state.role === "operator" ? "模拟权限收回" : "恢复演示操作者", "toggle-role", "quiet")}</div></section>
  <div class="stack"><section class="panel"><h2>操作资格</h2><div class="permission-row"><span>读取最后快照</span>${H.badge("允许", "success")}</div><div class="permission-row"><span>控制查询</span>${H.badge(H.state.online ? "允许" : "离线不可用", H.state.online ? "success" : "warning")}</div><div class="permission-row"><span>提交、批准与取消</span>${H.badge(H.lockReason() ? "暂停" : "允许", H.lockReason() ? "warning" : "success")}</div><div class="permission-row"><span>启用本机应急</span>${H.badge("不可用", "neutral")}</div></section><section class="panel"><h2>离线时的界面</h2><p class="body-copy">展示最后同步快照和时间；停止普通写入。重连后先重建授权范围与快照，再接收增量事件。</p>${H.go("查看同步状态", "sync", "arrow")}</section></div></div>`;
H.pages.sync = () => `${H.pageHeading("CONTROL / SNAPSHOT & EVENTS", "快照与事件", "先取得一致快照，再接续同一业务流的增量事件。", H.badge(H.state.gap ? "事件缺口 · 写入暂停" : H.state.online ? "快照已同步" : "最后同步快照", H.state.gap || !H.state.online ? "warning" : "success"))}
  <div class="sync-metrics"><div><span>快照身份</span><b>${H.state.snapshot}</b><small>授权业务状态 · 已固定</small></div><div><span>业务流身份</span><b>${H.state.stream}</b><small>${H.state.backup ? "旧备份恢复后已变化" : "当前分发流"}</small></div><div><span>分发游标</span><b>${H.state.cursor}</b><small>${H.state.gap ? "检测到不连续" : "聚合版本去重"}</small></div><div><span>写入资格</span><b>${H.lockReason() ? "暂停" : "可提交"}</b><small>${H.lockReason() || "仍按操作复核权限"}</small></div></div>
  <div class="toolbar"><p class="body-copy">重建快照不会改变未知操作的物理结果。</p><div class="actions">${H.btn("模拟事件缺口", "gap", "quiet")}${H.btn(`${H.icon("refresh")}重建完整快照`, "snapshot", "primary", H.queryAttr())}</div></div>
  <section class="panel">${H.panelHead("业务事件", `<span class="muted">当前范围 · 客户服务工作台</span>`)}${H.events(12)}</section>`;
H.scenarios = [
  ["offline", "控制通道断开", "保留最后快照和观察时间，禁止离线写入。", "link"],
  ["permission", "当前权限收回", "重建授权缓存，只保留当前允许的读取与查询。", "shield"],
  ["gap", "事件序列缺口", "暂停增量应用和写入，取得新快照后再接续。", "layers"],
  ["worker", "单 worker 重启", "继续使用原 RUN-1042 / Op-218，业务不重复推进。", "server"],
  ["checkpoint", "提交后检查点缺失", "从原命令查回已提交业务事实，不重放业务写入。", "file"],
  ["receipt", "接收回执丢失", "查询原 CMD-1042 的接收记录，不生成第二次命令。", "refresh"],
  ["capacity", "模型与执行槽已满", "普通启动等待；控制查询和取消仍可提交。", "pause"],
  ["backup", "从旧备份恢复", "更换业务流身份；自动执行默认关闭，等待授权核对。", "clock"],
];
H.pages.recovery = () => `${H.pageHeading("CONTROL / RECOVERY LAB", "同步与恢复", "选择一个本地场景，观察状态提示、操作资格与原身份如何保留。", H.btn("恢复初始示例", "reset", "quiet"))}
  <div class="recovery-summary"><span>${H.icon("shield")}</span><div><h2>${H.state.backup ? "自动执行保持关闭" : H.state.capacity ? "容量紧张，控制入口仍可用" : H.state.scenario === "normal" ? "当前没有注入恢复场景" : "当前场景已应用"}</h2><p>原 Run：RUN-1042 · 原操作：Op-218 · ${H.state.stopRequested ? "停止待确认" : "结果 unknown"} · 冲突资源继续保留</p></div>${H.btn("查询原操作", "query", "primary", H.queryAttr())}</div>
  <div class="scenario-grid">${H.scenarios.map(([id, title, desc, icon], i) => `<button class="scenario ${H.state.scenario === id ? "active" : ""}" data-scenario="${id}"><div><span class="scenario-icon">${H.icon(icon)}</span><small>0${i + 1}</small></div><h3>${title}</h3><p>${desc}</p><span class="scenario-action">${H.state.scenario === id ? "当前场景" : "应用本地场景"}${H.icon("arrow")}</span></button>`).join("")}</div>
  <div class="inline-note">所有状态均为浏览器内存演示。旧备份场景无法通过“重建快照”解除执行门禁；本机应急入口不开放。</div>`;
