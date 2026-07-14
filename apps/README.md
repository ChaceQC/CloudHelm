# apps

本目录保存面向用户的应用入口。CloudHelm MVP 中主要应用是 `control-console`，负责需求输入、任务视图、方案审查、diff、审批、日志、监控面板和远程接管。

当前 `apps/control-console` 已完成 M6 Web 控制台主流程：使用 React +
TypeScript + Vite 接入真实 Platform API，展示 Requirement、Technical Design、
DevelopmentPlan、AgentRun、ToolCall、Timeline、Artifact、diff、测试、审查、
安全扫描和本地等价 PR record。

当前仍未初始化 `src-tauri`。Tauri 桌面壳、远端部署、监控和人工接管页面按
M7-M9 计划接入，不能把目标页面描述为已实现能力。
