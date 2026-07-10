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

## API 约定

- REST 用于创建和查询资源。
- SSE/WebSocket 用于任务事件流、日志流和远程终端。
- 高风险动作返回审批状态，而不是直接静默执行。
- 所有 API 错误响应应包含 code、message、detail、trace_id。

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

桌面端需要实时刷新任务状态，推荐使用 SSE 或 WebSocket。

```text
GET    /api/tasks/{task_id}/events/stream
GET    /api/tasks/{task_id}/timeline
```

### 12.6 Environment / Deployment API

```text
POST   /api/projects/{project_id}/environments
GET    /api/projects/{project_id}/environments
GET    /api/environments/{environment_id}

POST   /api/environments/{environment_id}/remote-targets
GET    /api/environments/{environment_id}/remote-targets
POST   /api/remote-targets/{target_id}/test-connection

POST   /api/deployments
GET    /api/projects/{project_id}/deployments
GET    /api/deployments/{deployment_id}
POST   /api/deployments/{deployment_id}/health-check
POST   /api/deployments/{deployment_id}/rollback-request
```

### 12.7 Remote Ops API

这些接口的操作对象都是远端部署的业务项目。

```text
GET    /api/environments/{environment_id}/services
GET    /api/services/{service_id}/status
GET    /api/services/{service_id}/logs
GET    /api/services/{service_id}/metrics
POST   /api/services/{service_id}/restart-request
POST   /api/services/{service_id}/collect-diagnostics

POST   /api/remote-sessions
GET    /api/remote-sessions/{session_id}
GET    /api/remote-sessions/{session_id}/stream
POST   /api/remote-sessions/{session_id}/close
```

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

---
