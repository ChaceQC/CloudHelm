# Tool Call API

> 来源：[设计书 12 章](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：给出该 API 分组的端点清单和实现注意点。

## M2 已实现接口

```text
POST   /api/tasks/{task_id}/tool-calls
GET    /api/tasks/{task_id}/tool-calls
GET    /api/tool-calls/{tool_call_id}
```

- `POST /api/tasks/{task_id}/tool-calls` 是内部联调用记录接口，不执行真实工具。
- ToolCall 响应暴露 `tool_name`、`risk_level`、`status`、`arguments_summary`、`result_json` 和关联审批 ID。
- 完整 `arguments_json` 保存在数据库审计字段；API 默认只返回摘要，避免控制台泄露潜在敏感参数。
- `retry` 需要真实 Tool Gateway 执行能力，M2 暂不实现。

## 实现注意点

- 请求和响应模型应写入 OpenAPI，并同步生成前端类型。
- 涉及任务状态、工具调用、审批和远端操作的接口必须写事件日志。
- 列表接口需要分页、过滤和按 project/environment/task 过滤。

## 设计书摘录

### 12.3 Tool Call API

```text
GET    /api/tasks/{task_id}/tool-calls
GET    /api/tool-calls/{tool_call_id}
POST   /api/tool-calls/{tool_call_id}/retry
```
