# apps/control-console

CloudHelm 控制台前端，使用 React + TypeScript + Vite。当前 M6 已接入真实
Platform API，可创建 Project、Task，完成 Requirement、Architect、Planner
编排与审批，再逐步推进 Scaffold、Coder、Tester、Reviewer、Security 和本地
PR 收尾。页面展示 Task Detail、Timeline、ToolCall、Artifact、diff、测试、
审查、安全结果和 PullRequestRecord 的真实数据或空状态，不构造静态假任务、
假 Agent、假扫描或假部署数据。

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

## M6 功能边界

- Project Sidebar 调用 `GET /api/projects`、`POST /api/projects`。
- Task Board 调用 `GET /api/tasks?project_id=...`、`POST /api/tasks`、`pause`、`resume`、`cancel`。
- Task Detail 并发读取 Requirement、Technical Design、DevelopmentPlan、AgentRun、ToolCall、Approval、Timeline 和 Orchestration State。
- M4 编排区调用 `POST /api/tasks/{task_id}/start` 和 `POST /api/tasks/{task_id}/run-next`，一次只推进一个 Agent 步骤。
- Development Plan 面板展示 `GET /api/tasks/{task_id}/development-plans` 的真实任务图和风险 JSON。
- ToolCall 面板展示真实 `tool_calls` 的工具名、脱敏参数摘要、审计 JSON、风险等级、状态、幂等键、耗时、输出摘要、错误码和审批 ID。
- 本地开发控制区读取 `GET /api/tasks/{task_id}/local-development`，并通过
  `local-development/start`、`local-development/run-next` 每次推进一个 M6
  动作；按钮只由后端 `next_action`、Task 状态、计划审批和 active AgentRun
  决定。
- Development Evidence 读取 Artifact 列表/详情与 PullRequestRecord；已有 PR
  record 时固定使用其 diff/test/review/security 四类证据 ID，避免跨轮次拼接。
- Diff 只在自身容器内横向滚动；Artifact 截断预览显示
  `bytes_returned`。`provider=local` 且 `url=null` 时显示本地等价 PR，无远端链接。
- Project/Task 请求使用最新请求门禁；切换 Project 立即清空旧 Task 与详情，避免旧响应覆盖新状态。
- Requirement/TechnicalDesign 只有当前最新版可执行评审；历史版本保持只读。
- SSE 使用 `EventSource` 连接事件流并显式监听 M2-M6 事件；端点回放结束后固定退避重连、按 event id 去重，M6 事件同步刷新 Task Detail、Task Board 与 Development Evidence。
- 控制台不提供任意工具调用调试入口，不执行远端 push、CI/CD、SSH、部署或监控告警。
- `npm.cmd test` 使用 Node 内置测试运行器覆盖任务/编排/M6 操作策略、证据映射、最新请求门禁和 SSE 事件。
