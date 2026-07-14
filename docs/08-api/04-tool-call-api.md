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
- ToolCall 响应暴露 `tool_name`、`risk_level`、`status`、`arguments_summary`、脱敏 `audit_json`、`result_json` 和关联审批 ID。
- 数据库只保存脱敏后的 `arguments_json`；文件 `content` 只保留长度和 SHA-256，密码、Token、Cookie、私钥字段不保存原值。
- 内部记录请求不接受 `audit_json`，额外字段返回 `422 validation_error`；审计主体由服务端生成。
- `retry` 需要真实 Tool Gateway 执行能力，M2 暂不实现。

## M5 新增 Tool Gateway 执行入口

```text
GET    /api/tool-gateway/tools
POST   /api/tasks/{task_id}/tool-gateway/call
```

- `GET /api/tool-gateway/tools` 返回工具名、描述、风险等级、是否需要审批、允许的 Agent 类型、是否允许系统调用、审计字段、参数 JSON Schema 和统一结果 JSON Schema。
- `POST /api/tasks/{task_id}/tool-gateway/call` 通过 Tool Gateway 执行低风险本地工具，或为 L3/L4 工具创建审批请求。
- 请求体包含 `agent_run_id`、可选且必须成对出现的
  `provider_call_id` / `provider_item_type`、`tool_name`、`risk_level`、
  `idempotency_key`、`arguments`、`reason`。
- 响应复用 `ToolCallRead`，包含 `audit_json`、`result_summary`、`stdout_summary`、`stderr_summary`、`duration_ms`、`error_code`、`idempotency_key`。
- 每次有效调用写入 `ToolCallStarted`，随后写入 `ToolCallSucceeded`、`ToolCallFailed` 或 `ApprovalRequested`。
- Platform API 会先提交 `pending` ToolCall，并依靠数据库唯一索引原子抢占
  `idempotency_key`；只有抢占成功的请求才执行真实副作用。相同 Task 下完全
  相同且已经结束的调用会返回已有 ToolCall，不重复写文件或提交 Git；相同
  `idempotency_key` 或 `provider_call_id` 对应不同工具、风险或参数时返回
  `409 idempotency_conflict`，已有调用仍在执行时返回
  `409 tool_call_in_progress`。
- 除明确声明 `allow_system_call=true` 的工具外，所有副作用工具必须绑定属于当前任务且状态为 `running` 的 AgentRun；Agent 类型还必须位于工具声明的 `allowed_agent_types` 白名单中。
- 带 `workflow_step` 的 M6 AgentRun 只能由本地开发执行器提交工具调用；公开
  HTTP 入口直接绑定该 AgentRun 时返回
  `403 m6_agent_tool_executor_required`。执行器还会校验工具名称、规范化参数和
  调用次数是否属于当前已审批 execution recipe，未命中时只保存失败
  ToolCall，不执行工具副作用。
- Tool Gateway 内部请求要求 `agent_run_id` 与由 Platform API 解析出的 `agent_type` 同时存在或同时为空，防止不完整 Agent 上下文绕过系统调用限制。
- 绑定 AgentRun 时，AgentRun 与 Task 都必须为 `running`；暂停、等待审批和终态任务不能创建新的 Agent 副作用。
- Repo、Sandbox、Git 的 `workspace_root` 必须位于 `CLOUDHELM_TOOL_WORKSPACE_ROOTS`；空配置默认拒绝，越界返回 `workspace_not_allowed`。
- `audit_json` 至少记录 tool、task、AgentRun、Agent 类型、风险、幂等键、参数 hash、原因 hash、终态和错误码。失败路径与成功路径使用同一审计主体。
- stdout、stderr 和结果 JSON 返回前会移除常见 API Token、Bearer 凭据与私钥块。
- `agent_run_id`、关联 Approval 和 ToolCall 路径参数均执行任务归属校验，跨任务引用返回资源不存在或校验错误，不进入工具 handler。
- 调用频率按 `agent_run_id`（存在时）或 `task_id` 使用进程内滑动窗口限制；默认 60 秒 60 次，超额调用仍写入失败 ToolCall，`error_code=rate_limit_exceeded`，`result_json.retry_after_seconds` 给出建议等待时间。
- 限流参数由 `CLOUDHELM_TOOL_RATE_LIMIT_CALLS`、`CLOUDHELM_TOOL_RATE_LIMIT_WINDOW_SECONDS` 配置；M5 仅保证单实例一致性。

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
