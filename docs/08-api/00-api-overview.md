# API 总览

> 来源：[设计书 12 章](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：汇总平台对桌面端、Agent、部署和远端运维提供的 API 分组。

## M2 实现状态

M2 已在 `modules/platform-api` 接入真实 PostgreSQL 数据库，完成 Project、
Task、Requirement、Technical Design、AgentRun、ToolCall、Approval 和 Event
Timeline API。所有业务写操作由 service 层在同一事务中写业务表和
`event_logs`；路由层不直接访问数据库。

## M4 实现状态

M4 在 M2/M3 基础上新增 Orchestration 与 DevelopmentPlan API：

```text
GET    /api/tasks/{task_id}/orchestration
POST   /api/tasks/{task_id}/start
POST   /api/tasks/{task_id}/run-next
GET    /api/tasks/{task_id}/development-plans
GET    /api/development-plans/{plan_id}
```

`start` 只负责把任务从 `Created` 推到 `RequirementClarifying`；`run-next`
一次只推进 Requirement、Architect 或 Planner 的一个最小步骤。所有 Agent
输出写入真实 `agent_runs`、`requirement_specs`、`technical_designs`、
`development_plans` 和 `event_logs`。M4 不执行 Tool Gateway、Git、部署
或监控动作。

M2 统一错误响应：

```json
{
  "code": "task_not_found",
  "message": "任务不存在。",
  "detail": null,
  "trace_id": "请求链路 ID"
}
```

分页响应使用 offset cursor 最小实现：

```json
{
  "items": [],
  "page": {
    "limit": 50,
    "next_cursor": null
  }
}
```

cursor 只接受 1 至 18 位非负十进制字符串；非法值返回
`422 validation_error`，不会静默回到第一页。Project、Task、Requirement、
TechnicalDesign、DevelopmentPlan、AgentRun、ToolCall 和 Approval 列表按最新
记录优先；Timeline 先取得最新一页，再在页内按时间正序展示。未处理异常也会
转换为 `internal_error`，响应体和 `X-Trace-Id` 使用同一 `trace_id`。

## M5 实现状态

M5 新增 Tool Gateway API：

```text
GET    /api/tool-gateway/tools
POST   /api/tasks/{task_id}/tool-gateway/call
```

低风险工具调用会通过 `modules/tool-gateway` 完成参数校验、工作区 allowlist、策略检查和本地执行，并写入 `tool_calls` 与 `event_logs`。L3/L4 或工具声明要求审批时，只创建 `approval_requests`，不执行 handler。ToolCall 参数和结果落库前脱敏，Gateway 审计保存在 `audit_json`。`POST /api/tasks/{task_id}/tool-calls` 仍保留为内部联调用记录接口，不建议作为真实工具执行入口；其审计字段同样只能由服务端生成。

## M6 实现状态

M6 新增本地开发单步编排、Artifact 和本地等价 PR record API：

```text
GET    /api/tasks/{task_id}/local-development
POST   /api/tasks/{task_id}/local-development/start
POST   /api/tasks/{task_id}/local-development/run-next
GET    /api/tasks/{task_id}/artifacts
GET    /api/artifacts/{artifact_id}
GET    /api/tasks/{task_id}/pull-request-records
GET    /api/pull-request-records/{record_id}
```

`run-next` 每次只推进 Scaffold、Coder、Tester、Reviewer、Security 或 Git
收尾中的一个动作。所有文件、命令和 Git 副作用经过 Tool Gateway；工作区由
服务端配置和 Task 派生，HTTP 请求不能传入任意本机路径。Artifact 详情先校验
SHA-256，再返回最多 65536 bytes 的安全预览。没有远端 Git 服务时只保存
`provider=local`、`url=null` 的等价 PR record，不构造远端链接。

完整字段、门禁、错误和事件见
[11-local-development-api.md](11-local-development-api.md)。

## M7-M10 渐进实现与目标 API 边界

当前 `0.5.1` 没有真实用户登录、session、role binding、effective permission
或 sequence-based Desktop sync。M7-1 与 M7-2B1/B2 已渐进实现 Environment、
RemoteTarget、machine heartbeat、RepositoryBinding、ReleaseCandidate 和第一道
审批；其余后续接口分组为：

```text
Authentication / Device / Session
User / Role / Permission / RoleBinding
Project snapshot / incremental events / SSE live tail
Local Runtime device channel
Ops Hub workflow / deployment / monitoring
```

详细规划见：

- [12-auth-user-permission-api.md](12-auth-user-permission-api.md)
- [06-event-stream-api.md](06-event-stream-api.md)
- [../15-detailed-design/10-desktop-ops-hub-standalone-project.md](../15-detailed-design/10-desktop-ops-hub-standalone-project.md)
- [../15-detailed-design/11-identity-access-control.md](../15-detailed-design/11-identity-access-control.md)

目标受保护 API 必须：

- 只通过 HTTPS 暴露，使用服务端认证上下文派生
  `user_id/device_id/session_id`。
- 按 system/project/environment scope、资源属性和职责分离逐请求鉴权。
- 不相信请求体中的 `actor_id`、role 或 permission。
- 对写命令使用 `Idempotency-Key`，状态敏感资源使用 `If-Match` 或
  `expected_resource_version`。
- 允许 Desktop 根据 effective permissions 做页面/按钮门禁，但服务端仍独立
  校验并返回 401/403。

Ops Hub 的正常远端工作流由 PostgreSQL WorkflowJob 和服务端 worker 持续推进。
M4/M6 当前存在的 `run-next` 保留为实现事实；M7/M8 目标中的同名入口只用于开发
调试、答辩逐步展示或人工恢复，不是 Desktop 在线点击依赖。

## API 约定

- REST 用于创建和查询资源。
- SSE 用于任务/项目事件流和 M7 受限日志流；WebSocket 远程终端属于 M8 之后的
  增强能力，不纳入 M7。
- 高风险动作返回审批状态，而不是直接静默执行。
- 所有 API 错误响应应包含 code、message、detail、trace_id。
- 当前未接入用户认证的 API 只允许在受控开发入口运行，不得作为公网授权边界。

## 设计书摘录

## 12. API 设计

### 12.1 Task API

```text
POST   /api/projects
GET    /api/projects
GET    /api/projects/{project_id}

POST   /api/tasks
GET    /api/tasks
GET    /api/tasks/{task_id}
POST   /api/tasks/{task_id}/pause
POST   /api/tasks/{task_id}/resume
POST   /api/tasks/{task_id}/cancel
POST   /api/tasks/{task_id}/takeover
```

### 12.1.1 Requirement / Design API

```text
POST   /api/tasks/{task_id}/requirements
GET    /api/tasks/{task_id}/requirements
GET    /api/requirements/{requirement_id}
POST   /api/requirements/{requirement_id}/clarify
POST   /api/requirements/{requirement_id}/acceptance-criteria
POST   /api/requirements/{requirement_id}/approve
POST   /api/requirements/{requirement_id}/request-changes

POST   /api/tasks/{task_id}/technical-designs
GET    /api/tasks/{task_id}/technical-designs
GET    /api/technical-designs/{design_id}
POST   /api/technical-designs/{design_id}/approve
POST   /api/technical-designs/{design_id}/request-changes
POST   /api/technical-designs/{design_id}/generate-openapi
POST   /api/technical-designs/{design_id}/generate-db-schema
```

### 12.2 Agent Run API

```text
GET    /api/tasks/{task_id}/agent-runs
GET    /api/agent-runs/{run_id}
GET    /api/agent-runs/{run_id}/messages
GET    /api/agent-runs/{run_id}/tool-calls
```

### 12.3 Tool Call API

```text
GET    /api/tasks/{task_id}/tool-calls
GET    /api/tool-calls/{tool_call_id}
POST   /api/tool-calls/{tool_call_id}/retry
```

### 12.4 Approval API

```text
GET    /api/approvals
GET    /api/approvals/{approval_id}
POST   /api/approvals/{approval_id}/approve
POST   /api/approvals/{approval_id}/reject
```

### 12.5 Event Stream API

当前任务级接口：

```text
GET    /api/tasks/{task_id}/events/stream
GET    /api/tasks/{task_id}/timeline
```

M9 Desktop 离线补齐规划：

```text
GET    /api/projects/{project_id}/sync-snapshot
GET    /api/projects/{project_id}/events?after_sequence=<n>&limit=<n>
GET    /api/projects/{project_id}/events/stream
```

SSE 使用 `sequence` 作为 `id`，Desktop 先 snapshot，再补增量并打开 live tail；
游标超过保留期返回 `event_cursor_reset_required`。
用户安全控制流使用 `/api/me/security-snapshot` 与 `/api/me/events*`，按
`subject_user_id` 而非 actor 过滤；本地 cursor 按 Ops Hub/user/stream/scope
分区。

### 12.6 M7 Environment / Deployment API

```text
POST   /api/projects/{project_id}/environments
GET    /api/projects/{project_id}/environments
GET    /api/environments/{environment_id}

PUT    /api/projects/{project_id}/repository-binding
GET    /api/projects/{project_id}/repository-binding

POST   /api/environments/{environment_id}/remote-targets
GET    /api/environments/{environment_id}/remote-targets
POST   /api/remote-targets/{target_id}/test-connection

POST   /api/remote-agents/heartbeat
POST   /api/tasks/{task_id}/release-candidate
GET    /api/tasks/{task_id}/release-candidate
GET    /api/tasks/{task_id}/ci-runs
POST   /api/webhooks/ci/gitea
GET    /api/tasks/{task_id}/remote-deployment
POST   /api/tasks/{task_id}/remote-deployment/start
POST   /api/tasks/{task_id}/remote-deployment/run-next
GET    /api/projects/{project_id}/deployments
GET    /api/deployments/{deployment_id}
POST   /api/deployments/{deployment_id}/health-check
POST   /api/deployments/{deployment_id}/rollback-request
```

M7 的 `POST /api/tasks/{task_id}/release-candidate` 是第一道审批的唯一创建入口，
请求体固定为 `{}`；最新版 PullRequestRecord、完整 commit、repository binding
snapshot/hash、candidate ref、幂等键和 request hash 均由服务端派生，并在同一
事务创建 Candidate、L2 Approval 与 pending `release_candidate_reconcile`
WorkflowJob。当前 B2 只完成该原子持久化，不发布 ref 或触发 CI。
`remote-deployment/start` 只接受
`environment_id`，要求已有 approved candidate，并由服务端选择 active
RemoteTarget，不重复创建第一道审批。审批通过后才发布受控 ref，并对固定
workflow 执行唯一一次 `workflow_dispatch`。CI 只生成测试、安全、构建、
manifest 和不可变 OCI digest；Release / Deploy Agent 随后生成 ReleasePlan，
第二道 deployment approval 通过后才允许 Deployment Controller 调用 Remote
Agent。`rollback-request` 只生成候选与审批请求，不自动执行回滚。

`remote-deployment/run-next` 只用于调试、逐步演示和人工恢复。M7-2C 完成后，
正式 Ops Hub 才在命令/审批事务提交后由 durable dispatcher 与 worker 自动继续，
Desktop 退出不停止已持久化且无需新审批的工作。

### 12.7 M7 Remote Ops API

这些接口的操作对象都是远端部署的业务项目。

```text
GET    /api/environments/{environment_id}/services
GET    /api/services/{service_id}/status
GET    /api/services/{service_id}/logs
GET    /api/services/{service_id}/logs/stream
POST   /api/services/{service_id}/collect-diagnostics
```

M7 日志和 diagnostics 必须限制时间、行数、字节数并执行脱敏；任意 shell、
WebSocket terminal、服务重启、集中日志与指标查询属于后续增强能力。

M8 再接入 Prometheus/Loki/Alertmanager、metrics、集中日志检索、告警和
runbook proposal；交互式 remote session 属于 M8 之后的增强版。

### 12.8 Monitoring / Incident API

```text
GET    /api/projects/{project_id}/alerts
GET    /api/alerts/{alert_id}
POST   /api/alerts/{alert_id}/ack
POST   /api/alerts/{alert_id}/create-incident

GET    /api/projects/{project_id}/incidents
GET    /api/incidents/{incident_id}
POST   /api/incidents/{incident_id}/runbook-proposal
POST   /api/incidents/{incident_id}/resolve
```

### 12.9 Auth / User / Permission API（M9 规划）

```text
POST   /api/auth/bootstrap
POST   /api/auth/login-challenges
POST   /api/auth/login
POST   /api/auth/refresh
POST   /api/auth/logout
GET    /api/auth/me
GET    /api/auth/sessions
DELETE /api/auth/sessions/{session_id}
GET    /api/auth/devices
POST   /api/auth/devices/pairing-challenges
POST   /api/auth/devices/pair
POST   /api/auth/device-session-challenges
POST   /api/auth/device-sessions
GET    /api/me/security-snapshot
GET    /api/me/events?after_sequence=<n>
GET    /api/me/events/stream
POST   /api/auth/devices/{device_id}/revoke

GET    /api/users
POST   /api/users/invitations
POST   /api/auth/invitations/accept
GET    /api/users/{user_id}
PATCH  /api/users/{user_id}
POST   /api/users/{user_id}/disable
POST   /api/users/{user_id}/enable
POST   /api/users/{user_id}/sessions/revoke

GET    /api/roles
GET    /api/permissions
GET    /api/role-bindings
POST   /api/role-bindings
POST   /api/role-bindings/{binding_id}/revoke
GET    /api/me/effective-permissions
```

当前版本未实现以上接口。角色、scope、Desktop 能力映射和职责分离见
[12-auth-user-permission-api.md](12-auth-user-permission-api.md)。

---
