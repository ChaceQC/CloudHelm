# apps/control-console

CloudHelm 控制台前端，使用 React + TypeScript + Vite。当前 M3 已接入真实 Platform API，可创建 Project、创建 Task、暂停/恢复/取消任务，并展示 Task Detail、Requirement、Technical Design、Timeline、ToolCall 和 Approval 的真实数据或空状态；不提供静态假任务、假 Agent 或假部署数据。

## 命令

```powershell
npm.cmd install
$env:VITE_CLOUDHELM_API_BASE_URL='http://127.0.0.1:18080'
npm.cmd run dev
npm.cmd run build
```

## 配置

- `VITE_CLOUDHELM_API_BASE_URL`：平台 API 地址，例如 `http://127.0.0.1:18080`。

## Tauri 说明

当前仍保留 React/TypeScript 工程边界，未初始化 `src-tauri`。Tauri 桌面壳会在控制台功能进入可交互主流程后再接入，避免提前扩大依赖和验证范围。

## M3 功能边界

- Project Sidebar 调用 `GET /api/projects`、`POST /api/projects`。
- Task Board 调用 `GET /api/tasks?project_id=...`、`POST /api/tasks`、`pause`、`resume`、`cancel`。
- Task Detail 并发读取 Requirement、Technical Design、AgentRun、ToolCall、Approval 和 Timeline。
- SSE 优先使用 `EventSource` 连接 M2 事件流；因 M2 只回放已有事件和 heartbeat，界面在任务操作后重新读取 Timeline。
- Agent 自动规格化、Tool Gateway 执行、Git PR、远端部署和监控告警留到 M4 及后续阶段。
