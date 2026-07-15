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

当前 UUID event id 只用于事件身份，不是连续同步游标；当前接口也没有项目级
snapshot、sequence retention 或 Desktop 长时间离线补齐能力。

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

## M9 Desktop 离线同步目标（规划）

### EventLog envelope

服务端 PostgreSQL 后续增加：

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

- `sequence` 在单个 Ops Hub 内单调递增但不承诺连续；权限过滤导致的空洞正常。
- SSE `id` 固定为十进制 sequence，UUID `event_id` 继续用于去重和审计。
- `aggregate_version` 防止旧事件覆盖新 read model。
- `stream_kind` 固定为 `project | user_control | system_audit`；project 流必须有
  `project_id`，user_control 流必须有 `subject_user_id`。
- `actor_user_id` 是执行者，`subject_user_id` 是用户控制流受众。事件响应按认证
  用户的 project/environment scope 过滤；撤销/过期 binding 时，被影响用户仍收到
  最小化的 self/control event，以触发权限刷新和缓存清理。
- `/api/me/events*` 只返回 `stream_kind=user_control` 且
  `subject_user_id=authenticated_user_id` 的事件，不从 payload 或 actor 推断受众。

### 计划接口

```text
GET /api/me/security-snapshot
GET /api/me/events?after_sequence=<n>&limit=<n>
GET /api/me/events/stream

GET /api/projects/{project_id}/sync-snapshot
GET /api/projects/{project_id}/events?after_sequence=<n>&limit=<n>
GET /api/projects/{project_id}/events/stream
```

`/api/me/*` 是登录用户的最小控制流，独立于 project subscription，承载
User/Device/Session/RoleBinding/permission-version 变化。project 流只承载调用者
当前 scope 可见的业务资源事件。

security snapshot 至少返回：

```json
{
  "as_of_sequence": 4812,
  "auth_version": 4,
  "permission_version": 19,
  "user": {},
  "devices": [],
  "sessions": [],
  "role_bindings": []
}
```

project snapshot 至少返回：

```json
{
  "project_id": "uuid",
  "as_of_sequence": 1234,
  "resource_versions": {},
  "tasks": [],
  "approvals": [],
  "environments": [],
  "deployments": []
}
```

重连顺序：

1. Desktop 按 `ops_hub_id + user_id + stream_kind + scope_id` 分别读取用户
   控制流和各 project 流游标。
2. 首次同步、cursor reset 或本地 read model 不可信时，在同一一致性读事务生成
   snapshot 与 `as_of_sequence`；普通重连且 cursor 有效时只读取
   `after_sequence` 增量。
3. 按 event id 去重，按 aggregate version 拒绝旧覆盖。
4. 使用 snapshot 时从 `as_of_sequence` 打开 SSE；只走增量时从最后成功应用的
   sequence 打开 SSE，补齐建连窗口。
5. 成功应用后才更新 Desktop SQLite cursor。

如果 sequence 已超过服务端保留窗口，返回
`409 event_cursor_reset_required`，并提供当前最小可用 sequence；Desktop 清除
对应 cached read model 后重新获取 snapshot。审批、部署、取消、回滚和远端命令
不得作为离线队列自动重放。

## 设计书摘录

### 12.5 Event Stream API

当前任务级事件使用 SSE；交互式 WebSocket 只保留给后续受控远程 session。

```text
GET    /api/tasks/{task_id}/events/stream
GET    /api/tasks/{task_id}/timeline
```
