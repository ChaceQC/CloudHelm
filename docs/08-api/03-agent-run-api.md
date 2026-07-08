# Agent Run API

> 来源：[设计书 12 章](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：给出该 API 分组的端点清单和实现注意点。

## M2 已实现接口

```text
POST   /api/tasks/{task_id}/agent-runs
GET    /api/tasks/{task_id}/agent-runs
GET    /api/agent-runs/{run_id}
```

- `POST /api/tasks/{task_id}/agent-runs` 是内部联调用记录接口，只写入数据库和 `AgentRunRecorded` 事件。
- M2 不实现 Agent 自动执行、消息流、模型调用或工具调用编排。
- `messages` 和 `agent-runs/{run_id}/tool-calls` 聚合视图在后续 Agent 编排与 Tool Gateway 阶段实现。

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
