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

## M4/M5 字段扩展

`agent_runs` 新增以下字段用于结构化输出和失败追踪：

- `summary`
- `structured_output_type`
- `structured_output_json`
- `error_code`
- `error_message`
- `conversation_id`
- `conversation_turn`
- `cached_input_tokens`
- `provider_request_count`
- `provider_requests`
- `provider_response_id`
- `prompt_cache_key`

`input_tokens`、`cached_input_tokens` 和 `output_tokens` 是一个 AgentRun 内所有
已完成供应商请求的真实总量。`provider_requests` 保留每次请求的
`response_id`、cache key、input/cached/output token 和由
`cached_input_tokens > 0` 推导的 `cache_hit`，因此结构化格式修复重试不会
被隐藏或误报成单次请求。

响应片段：

```json
{
  "conversation_id": "uuid",
  "conversation_turn": 2,
  "input_tokens": 38530,
  "cached_input_tokens": 11008,
  "provider_request_count": 2,
  "provider_requests": [
    {
      "response_id": "resp_...",
      "prompt_cache_key": "cloudhelm:uuid",
      "input_tokens": 18000,
      "cached_input_tokens": 5120,
      "output_tokens": 3200,
      "cache_hit": true
    }
  ]
}
```

同一 Task 的普通 Agent 角色必须返回同一 `conversation_id` 和
`prompt_cache_key`，成功 turn 依次递增。只有显式创建 subagent 时才使用新的
conversation/cache key。

M4 编排产生的 AgentRun 会写入 `AgentRunStarted`、`AgentRunCompleted` 或 `AgentRunFailed`。外部 provider 的 AgentRun 会在 `prompt_hash` 和启动事件中记录 API mode、reasoning effort 与 max attempts。缺少配置时错误码为 `missing_agent_provider_config`；HTTP 请求失败为 `agent_provider_request_failed`；响应或结构化输出无效为 `agent_provider_response_invalid`。

`openai_compatible` 通过 HTTP SSE Responses API 调用
`gpt-5.6-sol` / `xhigh`，并对瞬时网络错误、HTTP 408/409/429/5xx 和无效结构化
响应执行有界指数退避，默认总尝试 3 次。重试耗尽后的可恢复错误会把 Task
暂停在原阶段；认证等不可重试 4xx 不重复请求。Task 被取消时 active
AgentRun 会变为 `cancelled` 并写 `AgentRunCancelled`。

Prompt Cache 只以供应商 usage 为证据。稳定 Base Instructions、扁平跨角色
输出 schema、完整 ResponseItem 历史、Codex User-Agent、thread headers 和
稳定 cache key 共同保持前缀。官方显式协议启用时发送
`prompt_cache_options.mode=explicit` 和 content `prompt_cache_breakpoint`，
并随历史保留断点；当前兼容端点在 2026-07-11 的真实单请求探测返回 HTTP
502，因此配置默认关闭，不做静默字段降级、伪造命中或本地估算。

每个 Agent 步骤使用数据库 savepoint。若在产物、AgentRun 完成状态、
conversation turn 或完成事件写入阶段发生错误，savepoint 会整体回滚，再单独
提交失败 AgentRun；失败响应不能留下半成品或错误递增 turn。

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
