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

- Tool Calls 面板展示真实 `tool_calls` 的工具名、风险等级、状态、参数摘要、幂等键、耗时、错误码、审批 ID、stdout/stderr 摘要和 `result_json`。
- UI 继续参考 Codex 桌面端：低饱和深色面板、紧凑按钮、清晰边框和真实空态，不加入营销式大视觉。
- 控制台不提供任意工具调用调试入口，避免用户从 UI 直接发起高风险动作；工具执行入口由 Platform API 和后续 Agent 流程控制。

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
