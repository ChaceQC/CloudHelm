# Agent Run API

> 来源：[设计书 12 章](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：给出该 API 分组的端点清单和实现注意点。

## M2 已实现接口

```text
POST   /api/tasks/{task_id}/agent-runs
GET    /api/tasks/{task_id}/agent-runs
GET    /api/agent-runs/{run_id}
```

- `POST /api/tasks/{task_id}/agent-runs` 是内部联调用记录接口，只写入数据库和 `AgentRunRecorded` 事件；不能创建 `running`，该状态只允许 Orchestrator 使用。
- M4 已实现 Requirement / Architect / Planner 的同步 `run-next` 编排；M4 仍不执行工具调用。
- `messages` 和 `agent-runs/{run_id}/tool-calls` 聚合视图在后续 Agent 编排与 Tool Gateway 阶段实现。

## M4 字段扩展

`agent_runs` 新增以下字段用于结构化输出和失败追踪：

- `summary`
- `structured_output_type`
- `structured_output_json`
- `error_code`
- `error_message`

M4 编排产生的 AgentRun 会写入 `AgentRunStarted`、`AgentRunCompleted` 或 `AgentRunFailed`。外部 provider 的 AgentRun 会在 `prompt_hash` 和启动事件中记录 API mode、reasoning effort 与 max attempts。缺少配置时错误码为 `missing_agent_provider_config`；HTTP 请求失败为 `agent_provider_request_failed`；响应或结构化输出无效为 `agent_provider_response_invalid`。

`openai_compatible` 对瞬时网络错误、HTTP 408/409/429/5xx 和无效结构化
响应执行有界指数退避，默认总尝试 3 次。重试耗尽后的可恢复错误会把 Task
暂停在原阶段；认证等不可重试 4xx 不重复请求。Task 被取消时 active
AgentRun 会变为 `cancelled` 并写 `AgentRunCancelled`。

## 实现注意点

- 请求和响应模型应写入 OpenAPI，并同步生成前端类型。
- 涉及任务状态、工具调用、审批和远端操作的接口必须写事件日志。
- 列表接口需要分页、过滤和按 project/environment/task 过滤。

## 设计书摘录

### 12.2 Agent Run API

```text
GET    /api/tasks/{task_id}/agent-runs
GET    /api/agent-runs/{run_id}
GET    /api/agent-runs/{run_id}/messages
GET    /api/agent-runs/{run_id}/tool-calls
```
