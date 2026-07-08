# API 细化设计

> 来源：设计书 12 章  
> 目的：把端点清单细化为资源模型、请求响应、状态码和事件副作用。

## M2 落地状态

- 后端模块：`modules/platform-api`。
- API 根路径：`/api`，健康检查仍为 `/health`。
- 已实现接口：Project、Task、Requirement、Technical Design、AgentRun、ToolCall、Approval、Timeline、SSE。
- 响应契约：见 `packages/shared-contracts/openapi/cloudhelm.openapi.yaml`。
- 错误结构：`code`、`message`、`detail`、`trace_id`。
- 分页结构：`items` + `page.limit` + `page.next_cursor`。
- 事件副作用：创建/状态变更类写操作必须追加 `event_logs`。
- 边界：M2 不自动执行 Agent、不执行工具、不创建 Git PR、不部署远端环境。

### M2 内部联调创建接口

以下接口用于 M4/M5 接入前写入真实数据库记录，不能表述为 Agent 或 Tool
Gateway 已经自动运行：

```text
POST /api/tasks/{task_id}/agent-runs
POST /api/tasks/{task_id}/tool-calls
POST /api/tasks/{task_id}/approvals
```

## 1. API 通用规范

### 1.1 URL 与版本

MVP 使用：

```text
/api/*
```

后续可扩展为：

```text
/api/v1/*
```

### 1.2 通用响应

成功响应：

```json
{
  "data": {},
  "meta": {
    "request_id": "req_...",
    "trace_id": "trace_..."
  }
}
```

错误响应：

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "invalid request body",
    "detail": {},
    "trace_id": "trace_..."
  }
}
```

### 1.3 分页

列表接口统一支持：

```text
?limit=20&cursor=xxx
```

返回：

```json
{
  "data": [],
  "page": {
    "next_cursor": "string|null",
    "has_more": false
  }
}
```

## 2. Project API

### POST /api/projects

请求：

```json
{
  "name": "sample-repo-python",
  "repo_url": "http://gitea.local/cloudhelm/sample-repo-python.git",
  "default_branch": "main",
  "provider": "gitea"
}
```

响应：

```json
{
  "data": {
    "id": "uuid",
    "name": "sample-repo-python",
    "repo_url": "http://gitea.local/cloudhelm/sample-repo-python.git",
    "default_branch": "main",
    "provider": "gitea",
    "created_at": "2026-07-07T10:00:00Z"
  }
}
```

副作用：

- 写入 `projects`。
- 写入 `event_logs: ProjectCreated`。

## 3. Task API

### POST /api/tasks

请求：

```json
{
  "project_id": "uuid",
  "title": "增加用户注册登录和个人资料功能",
  "description": "使用 FastAPI + PostgreSQL + JWT，实现注册、登录、个人资料接口，并补充 pytest。",
  "source_type": "manual",
  "source_ref": null,
  "constraints": [
    "数据库迁移必须可回滚",
    "必须运行 pytest"
  ],
  "auto_start": true
}
```

响应：

```json
{
  "data": {
    "id": "uuid",
    "project_id": "uuid",
    "status": "created",
    "current_phase": "Created",
    "risk_level": "L1"
  }
}
```

副作用：

- 写入 `tasks`。
- 写入 `event_logs: TaskCreated`。
- 如果 `auto_start=true`，发送 Orchestrator 启动消息。

### POST /api/tasks/{task_id}/pause

请求：

```json
{
  "reason": "用户需要补充约束"
}
```

副作用：

- `tasks.status = paused`。
- 写入 `TaskPaused`。
- Orchestrator 停止调度新的工具调用；已运行的安全工具可允许自然结束。

### POST /api/tasks/{task_id}/takeover

请求：

```json
{
  "target": "sandbox",
  "reason": "人工检查测试失败原因"
}
```

响应：

```json
{
  "data": {
    "remote_session_id": "uuid",
    "stream_url": "/api/remote-sessions/{session_id}/stream"
  }
}
```

## 4. Requirement / Design API

### POST /api/tasks/{task_id}/requirements

请求：

```json
{
  "raw_input": "用户原始需求",
  "source_type": "manual"
}
```

响应字段：

- `id`
- `task_id`
- `user_story`
- `constraints_json`
- `acceptance_criteria_json`
- `status`
- `version`

### POST /api/requirements/{requirement_id}/approve

副作用：

- `requirement_specs.status = approved`。
- 写入 `RequirementApproved`。
- Orchestrator 可进入 Designing。

### POST /api/tasks/{task_id}/technical-designs

请求：

```json
{
  "requirement_spec_id": "uuid",
  "design_type": "feature",
  "content_markdown": "...",
  "openapi_json": {},
  "db_schema_json": {},
  "mermaid_diagram": "flowchart LR ..."
}
```

副作用：

- 写入 `technical_designs`。
- 写入 `TechnicalDesignProposed`。
- 如果风险等级高，创建 ApprovalRequest。

## 5. Agent Run API

### GET /api/tasks/{task_id}/agent-runs

返回：

```json
{
  "data": [
    {
      "id": "uuid",
      "agent_type": "requirement",
      "status": "succeeded",
      "model_name": "gpt-...",
      "input_tokens": 1200,
      "output_tokens": 800,
      "cost_usd": "0.001200",
      "started_at": "2026-07-07T10:00:00Z",
      "finished_at": "2026-07-07T10:00:10Z"
    }
  ]
}
```

用途：

- 控制台 Agent Timeline。
- 成本统计。
- 失败诊断。

## 6. Tool Call API

### GET /api/tasks/{task_id}/tool-calls

返回字段：

- tool_call_id
- agent_run_id
- tool_name
- risk_level
- arguments_summary
- status
- approval_id
- started_at
- finished_at
- result_summary
- error_code

### POST /api/tool-calls/{tool_call_id}/retry

约束：

- 只允许 retryable error。
- L3/L4 工具重试仍需审批有效。
- 重试需要新的 idempotency key 或 retry index。

## 7. Approval API

### POST /api/approvals/{approval_id}/approve

请求：

```json
{
  "comment": "同意部署 staging"
}
```

副作用：

- `approval_requests.status = approved`。
- 写入 `ApprovalApproved`。
- Orchestrator 恢复等待中的工具调用或状态迁移。

### POST /api/approvals/{approval_id}/reject

请求：

```json
{
  "reason": "需要先补充回滚方案"
}
```

副作用：

- `approval_requests.status = rejected`。
- 写入 `ApprovalRejected`。
- Orchestrator 回到 Designing / Planning / Implementing 或 WaitingOpsApproval 的拒绝分支。

## 8. Event Stream API

### GET /api/tasks/{task_id}/events/stream

SSE 事件类型：

|event|payload|
|---|---|
|task.phase_changed|task_id、from、to、reason|
|agent.started|agent_run_id、agent_type|
|agent.completed|agent_run_id、status、summary|
|tool.started|tool_call_id、tool_name、risk_level|
|tool.completed|tool_call_id、status、summary|
|approval.requested|approval_id、action、risk_level|
|artifact.created|artifact_id、artifact_type|
|deployment.updated|deployment_id、status|
|alert.fired|alert_id、severity|

断线恢复：

- 客户端保存 last_event_id。
- 重连时使用 `Last-Event-ID`。
- 服务端从 `event_logs` 回放缺失事件。

## 9. Deployment / Remote Ops API

### POST /api/deployments

请求：

```json
{
  "project_id": "uuid",
  "environment_id": "uuid",
  "version": "20260707-001",
  "commit_sha": "abc123",
  "image_tag": "registry.local/sample:abc123"
}
```

行为：

- 创建 `deployment`，初始状态 `pending_approval` 或 `queued`。
- L3 默认创建审批。
- 审批后由 Release / Deploy Agent 经 Tool Gateway 调用 Deployment Controller。

### GET /api/services/{service_id}/logs

查询参数：

```text
?since=15m&query=error&limit=200
```

返回：

```json
{
  "data": [
    {
      "ts": "2026-07-07T10:00:00Z",
      "level": "error",
      "service": "api",
      "message": "database connection failed"
    }
  ]
}
```

### POST /api/services/{service_id}/restart-request

必须创建 ApprovalRequest，不能直接重启。

## 10. Monitoring / Incident API

### POST /api/alerts/{alert_id}/create-incident

副作用：

- 写入 Incident。
- 写入 `ProjectIncidentCreated`。
- 触发 SRE Agent 分析。

### POST /api/incidents/{incident_id}/runbook-proposal

响应：

```json
{
  "data": {
    "incident_id": "uuid",
    "summary": "staging api 服务 5xx 升高，疑似最近发布引入",
    "evidence": [
      "错误率从 0.2% 升至 12%",
      "最近部署版本 20260707-002",
      "日志出现 database timeout"
    ],
    "proposed_actions": [
      {
        "action": "rollback",
        "risk_level": "L3",
        "requires_approval": true
      }
    ]
  }
}
```
