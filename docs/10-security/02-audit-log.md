# 审计记录

> 来源：[设计书 14.3](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：定义工具调用和远端操作的审计字段。
## 审计要求

审计记录应能回答：谁、何时、在哪个任务中、调用了什么工具、参数摘要是什么、风险等级是什么、是否审批、执行结果是什么。

## M5 已记录字段

- `tool_calls.idempotency_key`：任务内幂等键，用于避免重复执行同一工具调用。
- `tool_calls.arguments_summary`：脱敏参数摘要。
- `tool_calls.result_summary`：工具结果摘要。
- `tool_calls.stdout_summary` / `stderr_summary`：命令输出截断摘要。
- `tool_calls.duration_ms`：执行耗时。
- `tool_calls.error_code`：稳定失败码。
- `event_logs`：记录 `ToolCallStarted`、`ToolCallSucceeded`、`ToolCallFailed`、`ApprovalRequested`。

## 设计书摘录

### 14.3 审计记录

每次工具调用都记录：

```json
{
  "tool_call_id": "tc_001",
  "task_id": "task_001",
  "agent": "coder",
  "tool": "repo.write_file",
  "risk_level": "L1",
  "arguments_hash": "sha256:...",
  "status": "success",
  "started_at": "2026-07-07T10:00:00Z",
  "finished_at": "2026-07-07T10:00:02Z"
}
```

---
