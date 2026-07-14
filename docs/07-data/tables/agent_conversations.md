# agent_conversations

## 业务含义

保存可重放的 Task root conversation 与显式 subagent conversation。Requirement、
Architect、Planner、Scaffold、Coder、Tester、Reviewer、Security 共享同一个
root；角色切换只增加 turn。

## 关键字段

- `task_id`
- `parent_conversation_id`
- `spawned_by_agent_run_id`
- `source_type`: `root` / `subagent`
- `agent_role`、`nickname`、`objective`
- `depth`、`status`、`fork_mode`
- `provider_name`、`model_name`、`prompt_cache_key`
- `items_json`、`turn_count`、`revision`
- `last_response_id`、`completed_at`
- `created_at`、`updated_at`

## 约束

- 每个 Task 通过 partial unique index 只能有一个 root。
- root 的 parent/spawn/role/objective/fork 均为空且 `depth=0`。
- subagent 必须有 parent、spawn AgentRun、role、objective、fork mode 且
  `depth>0`。
- `prompt_cache_key` 全局唯一；`revision>=0` 用于乐观并发。
- `items_json` 保存可重放 ResponseItem，包括 encrypted reasoning、工具 call 与
  output；不保存明文思维链。
