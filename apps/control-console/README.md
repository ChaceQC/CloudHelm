# apps/control-console

CloudHelm 控制台前端，使用 React + TypeScript + Vite。当前 M5 已接入真实 Platform API，可创建 Project、Task，启动/推进 Requirement、Architect、Planner 编排，并展示 Task Detail、Requirement、Technical Design、DevelopmentPlan、Timeline、ToolCall、Tool Gateway 输出摘要和 Approval 的真实数据或空状态；不提供静态假任务、假 Agent 或假部署数据。

当前界面采用网页版 Gemini 式浅色布局：蓝灰左侧导航整合项目和最近任务，白色主工作区展示居中的任务详情阅读流；此说明仅指信息架构、留白和浅色视觉语言，不复制 Gemini 品牌资产或产品功能。

## 命令

```powershell
npm.cmd install
$env:VITE_CLOUDHELM_API_BASE_URL='http://127.0.0.1:18080'
npm.cmd run dev
npm.cmd test
npm.cmd run build
```

## 配置

- `VITE_CLOUDHELM_API_BASE_URL`：平台 API 地址，例如 `http://127.0.0.1:18080`。

## Tauri 说明

当前仍保留 React/TypeScript 工程边界，未初始化 `src-tauri`。Tauri 桌面壳会在控制台功能进入可交互主流程后再接入，避免提前扩大依赖和验证范围。

## M5 功能边界

- Project Sidebar 调用 `GET /api/projects`、`POST /api/projects`。
- Task Board 调用 `GET /api/tasks?project_id=...`、`POST /api/tasks`、`pause`、`resume`、`cancel`。
- Task Detail 并发读取 Requirement、Technical Design、DevelopmentPlan、AgentRun、ToolCall、Approval、Timeline 和 Orchestration State。
- M4 编排区调用 `POST /api/tasks/{task_id}/start` 和 `POST /api/tasks/{task_id}/run-next`，一次只推进一个 Agent 步骤。
- Development Plan 面板展示 `GET /api/tasks/{task_id}/development-plans` 的真实任务图和风险 JSON。
- ToolCall 面板展示真实 `tool_calls` 的工具名、参数摘要、风险等级、状态、幂等键、耗时、输出摘要、错误码和审批 ID。
- SSE 优先使用 `EventSource` 连接事件流，并显式监听 M2-M5 已落库的任务、AgentRun、DevelopmentPlan、ToolCall 和 Approval 事件；因当前端点只回放已有事件和 heartbeat，界面在任务操作后仍会重新读取 Timeline。
- M5 只覆盖本地 Tool Gateway 展示，不提供任意工具调用调试入口，不执行远端部署和监控告警。
- `npm.cmd test` 使用 Node 内置测试运行器覆盖任务操作/编排按钮状态策略，以及需求、设计、审批成功后刷新任务列表且失败时不误刷新的回调边界。
