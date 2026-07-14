# tool_calls

> 来源：[设计书 11.2](../../../云舵 CloudHelm 毕设设计书.md)、
> `modules/platform-api` 当前 ORM 与 migration

## 业务含义

记录一次 Tool Gateway 调用的主体、provider call 身份、脱敏参数、风险、结果、
审批和耗时。外部文件/Git/进程副作用执行前先用短事务抢占该记录。

## 当前字段

|字段|类型/约束|说明|
|---|---|---|
|`id`|UUID PK|ToolCall ID。|
|`task_id`|UUID FK, not null|所属 Task。|
|`agent_run_id`|UUID FK nullable|触发调用的 AgentRun。|
|`tool_name`|text not null|注册工具名。|
|`provider_call_id`|text nullable|Responses function/custom call ID。|
|`provider_item_type`|text nullable|`function_call` 或 `custom_tool_call`。|
|`risk_level`|text not null|L0-L4。|
|`arguments_json`|jsonb not null|脱敏参数快照；正文只保留长度和 hash。|
|`audit_json`|jsonb not null|主体、风险、幂等、参数/原因 hash、终态与策略指纹。|
|`result_json`|jsonb nullable|脱敏结构化结果。|
|`status`|text not null|pending/running/waiting_approval/succeeded/failed/cancelled。|
|`idempotency_key`|text nullable|Task 内工具调用幂等键。|
|`arguments_summary` / `result_summary`|text nullable|控制台摘要。|
|`stdout_summary` / `stderr_summary`|text nullable|截断并脱敏的进程输出。|
|`duration_ms`|integer nullable|执行耗时。|
|`error_code`|text nullable|稳定失败码。|
|`approval_id`|UUID FK nullable|关联 ApprovalRequest。|
|`started_at` / `finished_at`|timestamptz|生命周期时间。|

## 约束与幂等

- `provider_call_id` 与 `provider_item_type` 必须同时为空或同时存在；存在时还必须
  有 `agent_run_id`。
- `(agent_run_id, provider_call_id)` 在 provider call 非空时唯一。
- `(task_id, idempotency_key)` 在 key 非空时唯一。
- 同键或同 provider call 重放只有工具名、风险和参数 hash 完全一致才复用；
  不一致返回 `idempotency_conflict`。
- 已抢占但仍在执行的记录返回 `tool_call_in_progress`，不会重复进入 handler。

## M6 execution recipe

带 `workflow_step` 的 AgentRun 只接受内部 Agent executor。executor 按工具名、
移除服务端绑定字段后的 Pydantic 规范化参数和允许次数校验；未批准或超额调用保存
失败 ToolCall 与 `execution_policy_fingerprint`，不执行工具副作用。
