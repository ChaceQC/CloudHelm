# 审计记录

> 来源：[设计书 14.3](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：定义工具调用和远端操作的审计字段。
## 审计要求

审计记录应能回答：谁、何时、在哪个任务中、调用了什么工具、参数摘要是什么、风险等级是什么、是否审批、执行结果是什么。

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
