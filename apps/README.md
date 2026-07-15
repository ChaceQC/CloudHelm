# apps

本目录保存面向用户的应用入口。CloudHelm MVP 中主要应用是 `control-console`，负责需求输入、任务视图、方案审查、diff、审批、日志、监控面板和远程接管。

当前 `apps/control-console` 已完成 M6 Web 控制台主流程：使用 React +
TypeScript + Vite 接入真实 Platform API，展示 Requirement、Technical Design、
DevelopmentPlan、AgentRun、ToolCall、Timeline、Artifact、diff、测试、审查、
安全扫描和本地等价 PR record。

当前仍未初始化 `src-tauri`。M9 接入 Tauri、Local Runtime、运行时 Ops Hub
profile、Desktop SQLite、OS credential store、用户登录/RBAC 和权限化 UI；
M10 生成 Windows setup `.exe`、Linux AppImage/`.deb` 并完成安装验收。远端
部署属于 M7，监控属于 M8，人工 remote session 仍是增强版。
