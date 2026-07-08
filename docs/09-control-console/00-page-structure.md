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
