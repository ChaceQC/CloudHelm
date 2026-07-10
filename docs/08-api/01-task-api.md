# Task API

> 来源：[设计书 12 章](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：给出该 API 分组的端点清单和实现注意点。

## M2 已实现接口

```text
POST   /api/projects
GET    /api/projects
GET    /api/projects/{project_id}

POST   /api/tasks
GET    /api/tasks
GET    /api/tasks/{task_id}
POST   /api/tasks/{task_id}/pause
POST   /api/tasks/{task_id}/resume
POST   /api/tasks/{task_id}/cancel
```

- `POST /api/tasks` 必须校验 `project_id` 存在，初始状态为 `created`、阶段为 `Created`。
- 创建任务写入 `TaskCreated` 事件。
- 暂停、恢复、取消分别写入 `TaskPaused`、`TaskResumed`、`TaskCancelled`。
- `pause` 只修改任务运行状态，不覆盖 `current_phase`；`TaskPaused.payload.from_status` 记录暂停前状态。`resume` 从最近一次暂停事件恢复原状态；如果暂停期间最后一个待审批请求已经完成，则从 `waiting_approval` 恢复为 `running`，不会残留无审批可处理的等待状态。
- `cancel` 还会把 active AgentRun、active/waiting ToolCall 和 pending Approval 分别关闭为 `cancelled` / `expired`，并写入对应取消/过期事件。
- `GET /api/tasks` 支持 `limit`、严格非负十进制 `cursor` 和可选 `project_id` 过滤，按最新记录优先返回。
- `takeover` 属于远程接管能力，M2 暂不实现。

## M4 编排入口

```text
GET    /api/tasks/{task_id}/orchestration
POST   /api/tasks/{task_id}/start
POST   /api/tasks/{task_id}/run-next
```

- `start`：只允许从 `created` / `Created` 启动，进入 `running` / `RequirementClarifying`；重复调用已处于 M4 的任务返回幂等结果。
- `run-next`：按当前阶段推进一个 Agent 步骤；未 start、非法阶段或缺少外部 provider 配置返回统一错误结构和 `trace_id`。
- `paused` 任务必须先调用 `resume`；`done`、`failed`、`cancelled` 终态任务不能通过 Orchestration API 绕过任务状态机继续执行。
- Planning 只把“关联当前最新版已批准 TechnicalDesign，且状态不是 `changes_requested`”的 DevelopmentPlan 视为有效；设计或计划返工后会重新运行 Planner，而不是复用旧计划。
- 副作用：写入 `TaskPhaseChanged`、`AgentRunStarted`、`AgentRunCompleted`、`AgentRunFailed` 等事件。
- 外部 Agent provider 缺少配置、瞬时请求错误或无效结构化响应耗尽重试时，当前 AgentRun 记为失败，但 Task 进入可恢复的 `paused` 状态并保留当前阶段；认证等不可重试错误才进入 `failed`。

## 实现注意点

- 请求和响应模型应写入 OpenAPI，并同步生成前端类型。
- 涉及任务状态、工具调用、审批和远端操作的接口必须写事件日志。
- 列表接口需要分页、过滤和按 project/environment/task 过滤。

## 设计书摘录

### 12.1 Task API

```text
POST   /api/projects
GET    /api/projects
GET    /api/projects/{project_id}

POST   /api/tasks
GET    /api/tasks
GET    /api/tasks/{task_id}
POST   /api/tasks/{task_id}/pause
POST   /api/tasks/{task_id}/resume
POST   /api/tasks/{task_id}/cancel
POST   /api/tasks/{task_id}/takeover
```
