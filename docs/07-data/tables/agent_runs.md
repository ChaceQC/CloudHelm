# agent_runs

> 来源：[设计书 11.2](../../../云舵 CloudHelm 毕设设计书.md)、
> `modules/platform-api` 当前 ORM 与 migration

## 业务含义

记录某个 Agent 的一次运行。M4-M6 普通角色共享 Task root conversation；
M6 运行额外绑定 workflow step、attempt 和任务内幂等键。

## 当前字段

|字段|类型/约束|说明|
|---|---|---|
|`id`|UUID PK|运行 ID。|
|`task_id`|UUID FK, not null|所属 Task。|
|`conversation_id`|UUID FK nullable|root 或显式 subagent conversation。|
|`conversation_turn`|integer nullable|本次成功输出或 M6 失败工具证据保存后的 turn。|
|`agent_type`|text not null|Agent 角色。|
|`status`|text not null|pending/running/succeeded/failed/cancelled。|
|`workflow_step`|text nullable|M6 `run_scaffold` 等步骤；M4 为 null。|
|`attempt`|integer nullable, `> 0`|同一步骤重试序号。|
|`idempotency_key`|text nullable|M6 Agent 步骤任务内幂等键。|
|`model_name` / `prompt_hash`|text nullable|Provider 与 prompt 版本证据。|
|`summary`|text nullable|成功或失败摘要。|
|`structured_output_type`|text nullable|角色输出 contract 名。|
|`structured_output_json`|jsonb nullable|通过角色 Pydantic 校验的输出。|
|`error_code` / `error_message`|text nullable|失败证据。|
|`input_tokens` / `cached_input_tokens` / `output_tokens`|integer not null|供应商真实 usage 汇总。|
|`provider_request_count`|integer not null|已完成供应商请求数量。|
|`provider_requests`|jsonb array not null|逐请求 response/cache/token 证据。|
|`provider_response_id` / `prompt_cache_key`|text nullable|Responses 与缓存路由证据。|
|`cost_usd`|numeric(12,6) not null|估算成本。|
|`started_at` / `finished_at`|timestamptz|生命周期时间。|

## 约束与索引

- `workflow_step`、`attempt`、`idempotency_key` 必须同时为空或同时非空。
- `(task_id, idempotency_key)` 在 key 非空时唯一。
- `(task_id, workflow_step, attempt)` 用于重试与审计查询。
- partial unique index
  `ux_agent_runs_task_active_workflow(task_id) WHERE workflow_step IS NOT NULL
  AND status IN ('pending','running')` 防止并发 `run-next` 双执行。
- `(conversation_id, conversation_turn)` 支持同一会话 turn 审计。

## 失败语义

成功业务产物、AgentRun、conversation turn 和完成事件使用 savepoint 原子保存。
M6 工具步骤若已产生真实 ToolCall，基础设施失败时仍保存配对 provider call/output
与 `<failed_step_context>`，失败 AgentRun 引用该 turn，但不保存成功角色产物。
