# 桌面端控制台页面结构

> 来源：[设计书 13.1](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：定义 Control Console 的页面、面板和信息架构。
## UI 分层

- Project Sidebar：项目与仓库状态入口。
- Task Board / Task Detail：Agent 工作流主视图。
- Diff Viewer / Design Review Panel：开发审查主视图。
- Terminal Panel / Approval Panel：接管与审批主视图。

## M3 落地状态

- `apps/control-console` 已实现 Project Sidebar，调用真实 `GET /api/projects` 和 `POST /api/projects`。
- Task Board 已按后端 `status` 展示真实任务，并通过 `POST /api/tasks`、`pause`、`resume`、`cancel` 操作任务。
- Task Detail 已展示真实 Requirement Spec、Technical Design、AgentRun、ToolCall、Approval 和 Event Log 空态或记录。
- M3 不包含 Diff Viewer、Terminal Panel、真实 Git PR、真实 Tool Gateway 执行和远端接管；这些能力在后续 M5-M8 接入。

## M4 落地状态

- Task Detail 顶部新增 Agent 编排区，展示当前阶段、下一步动作、设计审批状态和计划是否存在。
- “启动编排”调用 `POST /api/tasks/{task_id}/start`。
- “推进一步”调用 `POST /api/tasks/{task_id}/run-next`，一次只推进 Requirement、Architect 或 Planner 的一个最小步骤。
- 新增 Development Plan 面板，读取 `GET /api/tasks/{task_id}/development-plans`，展示 Planner Agent 写入的任务图和风险 JSON。
- 控制台文案明确 M4 不执行代码修改、Tool Gateway 工具、Git PR、远端部署或监控告警。

## M5 落地状态

- Tool Calls 面板展示真实 `tool_calls` 的工具名、风险等级、状态、参数摘要、审计 JSON、幂等键、耗时、错误码、审批 ID、stdout/stderr 摘要和 `result_json`。
- 2026-07-10 根据最新界面要求重写为网页版 Gemini 式浅色信息架构：页面使用纯白主工作区和蓝灰侧栏，项目与最近任务整合在左侧导航，Task Detail 使用居中的宽松阅读流。
- 项目、任务、编排、评审、Timeline、ToolCall 和 Approval 仍读取真实 Platform API；视觉重写不引入静态示例、假任务或假工具结果。
- 容器采用柔和浅灰背景、大圆角和弱分隔，重要选择态使用浅蓝底色；日志和 JSON 继续使用等宽字体，但不再使用深色终端面板作为全局主题。
- 1280、1024、375 像素宽度下分别采用双栏、自适应双栏和纵向布局，禁止水平溢出。
- 任务状态分组和操作按钮使用中文；终态任务不再提供无效取消动作，暂停或终态任务的编排按钮按后端合法状态禁用。
- EventSource 显式监听 M2-M5 已落库的 `TaskPhaseChanged`、AgentRun、DevelopmentPlan、ToolCall 和 Approval 事件，事件类型与共享 JSON Schema 保持一致。
- 快速切换 Project 时立即清空旧 Task 选择和列表，Project/Task 请求只允许最后一次响应更新状态，避免旧响应覆盖新项目。
- Requirement/TechnicalDesign 只允许当前最新版执行评审：draft 可批准，draft/approved 可要求修改，历史版本和不可决策状态按钮禁用。
- SSE 回放结束后自动重连并按 event id 去重；旧连接回调不能关闭新连接，组件卸载时关闭连接和重连定时器，新事件同时刷新 Task Detail 和左侧 Task Board。
- 控制台不提供任意工具调用调试入口，避免用户从 UI 直接发起高风险动作；工具执行入口由 Platform API 和后续 Agent 流程控制。

## M6 落地状态

- Task Detail 新增本地开发控制区，读取后端 `current_phase/next_action` 并逐步
  调用 `local-development/start` 与 `local-development/run-next`。
- Development Evidence 展示 Artifact 安全预览和 PullRequestRecord 固化的
  diff/test/review/security 证据，不跨 evidence set 拼接最新记录。
- Diff Viewer 展示 unified patch、changed files 和 diff stat；长行只在 diff
  容器内部滚动，不造成 document 水平溢出。
- Test、Review、Security 面板展示真实结构化报告、ToolCall 与错误摘要。
- 本地等价 PR 显示 base/head、commit、changed files 和门禁 Artifact；
  `provider=local`、`url=null` 时明确显示无远端链接。
- EventSource 新增 M6 事件监听，收到事件后刷新 Task、Task Board 和 Development
  Evidence。

## 设计书摘录

### 13.1 页面结构

```text
Control Console
├── Project Sidebar
│   ├── 项目列表
│   ├── 仓库状态
│   └── 当前运行任务数
│
├── Task Board
│   ├── Created
│   ├── Requirement Clarifying
│   ├── Designing
│   ├── Planning
│   ├── Scaffolding
│   ├── Implementing
│   ├── Testing
│   ├── Reviewing
│   ├── Waiting Approval
│   └── Done / Failed
│
├── Task Detail
│   ├── Requirement Spec
│   ├── Acceptance Criteria
│   ├── Technical Design / ADR
│   ├── OpenAPI / DB Schema
│   ├── Agent Timeline
│   ├── Tool Calls
│   ├── Event Log
│   ├── Cost / Token
│   └── Artifacts
│
├── Diff Viewer
│   ├── Changed Files
│   ├── Side-by-side Diff
│   └── Review Comments
│
├── Design Review Panel
│   ├── Requirement Review
│   ├── Architecture Decision
│   ├── API Contract
│   ├── Database Migration
│   └── Request Changes
│
├── Terminal Panel
│   ├── Sandbox Command Output
│   ├── Test Logs
│   └── Human Takeover Shell
│
└── Approval Panel
    ├── Approve
    ├── Reject
    ├── Pause
    ├── Redirect
    └── Takeover
```
