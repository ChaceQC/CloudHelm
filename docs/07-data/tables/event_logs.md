# event_logs

> 来源：[设计书 11.2](../../../云舵 CloudHelm 毕设设计书.md)

## 业务含义

保存平台业务事件和审计时间线。当前 M2-M7-1 以 UUID event id、可选 Task、
event type、actor string、JSONB payload 和时间为主。

## 当前 SQL 定义

```sql
CREATE TABLE event_logs (
    id UUID PRIMARY KEY,
    task_id UUID REFERENCES tasks(id),
    event_type TEXT NOT NULL,
    actor_type TEXT NOT NULL,
    actor_id TEXT,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## 当前实现说明

- 主键 UUID 用于事件唯一身份和客户端去重。
- 时间字段统一使用 `TIMESTAMPTZ`。
- 写业务状态和对应 EventLog 必须在同一 service 事务中提交。
- 当前任务 SSE 回放已有事件、追加 heartbeat 后关闭；Web 控制台重连并按 UUID
  去重，不具备 sequence-based Desktop 离线同步。

## M9 目标扩展（规划）

```text
sequence BIGINT
stream_kind TEXT
project_id UUID
aggregate_type TEXT
aggregate_id UUID
aggregate_version BIGINT
schema_version TEXT
actor_user_id UUID
actor_device_id UUID
actor_session_id UUID
subject_user_id UUID
```

要求：

- `sequence` 在单个 Ops Hub 内单调递增但不保证连续，并有唯一索引。
- `stream_kind` 固定为 `project | user_control | system_audit`。
- project 流要求 `project_id`；user_control 流要求 `subject_user_id`，并按
  `subject_user_id, sequence` 建索引。
- `project_id, sequence` 支持权限过滤后的增量读取。
- `aggregate_type/id/version` 防止旧事件覆盖新 read model。
- SSE `id` 使用 sequence；UUID `id` 继续用于事件身份。
- 权限过滤造成的 sequence 空洞正常。
- 游标超过保留期时返回 `event_cursor_reset_required`，Desktop 重建 snapshot。
- 调用方 `actor_id` 不作为用户授权身份；真实 user/device/session 从认证上下文
  写入。
- `actor_user_id` 记录执行者，`subject_user_id` 记录用户控制流受众。管理员撤权
  时二者通常不同；`/api/me/events*` 只按认证 user 匹配 subject，不从 payload
  猜受众。
