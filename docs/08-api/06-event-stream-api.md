# Event Stream API

> 来源：[设计书 12 章](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：给出该 API 分组的端点清单和实现注意点。

## M2 已实现接口

```text
GET    /api/tasks/{task_id}/timeline
GET    /api/tasks/{task_id}/events/stream
```

- Timeline 分页先按 `created_at`、`id` 倒序取得最新记录，再把当前页恢复为时间正序，保证小页不会永久漏掉最新事件。
- SSE 端点基于真实事件回放当前已有事件并追加 heartbeat，随后关闭本次响应。
- 控制台按固定退避重连 SSE、按 event id 去重，并在出现新事件时同步刷新详情和 Task Board；后续事件总线阶段再升级为真正长连接推送。

## M4 新增事件

M4 编排会追加以下事件：

- `TaskPhaseChanged`
- `AgentRunStarted`
- `AgentRunCompleted`
- `AgentRunFailed`
- `DevelopmentPlanCreated`

Requirement、Technical Design 和 Approval 继续复用 M2 已有事件类型。任务取消还会按实际资源写入 `AgentRunCancelled`、`ToolCallCancelled` 和 `ApprovalExpired`。当前 SSE 仍基于 `event_logs` 回放已有事件并追加 heartbeat，不实现生产级事件总线。

## 实现注意点

- 请求和响应模型应写入 OpenAPI，并同步生成前端类型。
- 涉及任务状态、工具调用、审批和远端操作的接口必须写事件日志。
- 列表接口需要分页、过滤和按 project/environment/task 过滤。

## 设计书摘录

### 12.5 Event Stream API

桌面端需要实时刷新任务状态，推荐使用 SSE 或 WebSocket。

```text
GET    /api/tasks/{task_id}/events/stream
GET    /api/tasks/{task_id}/timeline
```
