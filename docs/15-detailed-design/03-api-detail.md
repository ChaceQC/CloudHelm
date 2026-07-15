# API 细化设计

> 来源：设计书 12 章  
> 目的：把端点清单细化为资源模型、请求响应、状态码和事件副作用。

## M2 落地状态

- 后端模块：`modules/platform-api`。
- API 根路径：`/api`，健康检查仍为 `/health`。
- 已实现接口：Project、Task、Requirement、Technical Design、AgentRun、ToolCall、Approval、Timeline、SSE。
- 响应契约：见 `packages/shared-contracts/openapi/cloudhelm.openapi.yaml`。
- 错误结构：`code`、`message`、`detail`、`trace_id`。
- 分页结构：`items` + `page.limit` + `page.next_cursor`；cursor 只接受 1 至 18 位非负十进制字符串。
- 列表默认最新记录优先；Timeline 先取最新页，再按页内时间正序返回。
- 未处理异常转换为 `500 internal_error`，响应体与 `X-Trace-Id` 使用同一 trace id。
- 事件副作用：创建/状态变更类写操作必须追加 `event_logs`。
- 边界：M2 不自动执行 Agent、不执行工具、不创建 Git PR、不部署远端环境。

## M4 落地状态

- 新增接口：`GET /api/tasks/{task_id}/orchestration`、`POST /api/tasks/{task_id}/start`、`POST /api/tasks/{task_id}/run-next`、`GET /api/tasks/{task_id}/development-plans`、`GET /api/development-plans/{plan_id}`。
- `run-next` 一次只推进 Requirement、Architect 或 Planner 的一个步骤。
- `start` / `run-next` 请求可携带调用方读取到的 `expected_phase`；服务端在
  Task 行锁内比较阶段，旧页面或重复点击导致的阶段漂移返回
  `409 orchestration_phase_changed`，不会顺带推进下一角色。
- 结构化输出写入 `agent_runs.structured_output_json`，并同步落到 `requirement_specs`、`technical_designs` 或 `development_plans`。
- 缺少外部 provider 配置、结构化输出校验失败和非法状态迁移均返回统一错误结构并写入可追溯事件。
- `openai_compatible` 使用 HTTP SSE Responses API；当前真实流程透传兼容端点提供的 `gpt-5.6-sol`、`reasoning.effort=xhigh`、Codex User-Agent 和 thread/session headers。瞬时请求与无效结构化响应执行有界重试，耗尽后可恢复错误暂停 Task。
- Requirement、Architect、Planner 跨独立 `run-next` 请求复用同一 Task root conversation、同一 `prompt_cache_key` 和完整有序 ResponseItem 历史；普通角色切换不得新建会话。
- 每个 Agent 步骤使用数据库 savepoint：业务产物、成功 AgentRun、conversation turn 和完成事件原子提交；晚期失败先回滚这些半成品，再单独记录失败 AgentRun。
- 暂停任务不能绕过 Task API 继续 start/run-next；Planning 只复用当前最新版已批准设计对应且未被要求修改的计划。
- 需求/设计返工会级联失效旧设计、旧计划和待审批记录；设计/计划审批只接受当前产物 AgentRun，过期审批返回 `409 stale_approval`。
- 边界：M4 不执行 Tool Gateway、Repo/Git/Docker/SSH、PR、部署或监控动作。

## M6 落地状态

- 新增 `local-development` state/start/run-next、Artifact 列表/详情和本地
  PullRequestRecord 列表/详情 API。
- `run-next` 每次推进 Scaffold、Coder、Tester、Reviewer、Security 或本地 PR
  收尾中的一个动作，HTTP 请求不接收 workspace、命令、分支或 Artifact root。
- M6 的“sandbox”是 Tool Gateway 管理的 allowlist 本地目录与受控
  `subprocess`，具备命令 profile、环境白名单、超时、进程树清理和有界输出；
  当前未交付 Docker CPU/内存/PID/网络隔离。
- `diff_patch` / `format_patch` Artifact 保存原始 UTF-8 bytes 与真实 SHA，供
  `git apply --check` 和 Git 最终门禁；ToolCall 数据库结果、Reviewer 输入和
  Artifact API preview 使用保留 Git 结构的脱敏安全投影，不向 Reviewer/客户端
  暴露 raw secrets。
- 应用异常进入现有错误处理后，可依靠 ToolCall、Artifact 和 PR record 幂等证据
  重试。进程被强制终止时，`pending/running` AgentRun 或 ToolCall 尚无
  lease/heartbeat/stale reclaim，M6 不宣称自动恢复这类 hard crash。
- 完整字段、门禁、错误与事件见
  [08-m6-local-development-flow.md](08-m6-local-development-flow.md) 和
  [../08-api/11-local-development-api.md](../08-api/11-local-development-api.md)。

### M2 内部联调创建接口

以下接口用于 M4/M5 接入前写入真实数据库记录，不能表述为 Agent 或 Tool
Gateway 已经自动运行：

```text
POST /api/tasks/{task_id}/agent-runs
POST /api/tasks/{task_id}/tool-calls
POST /api/tasks/{task_id}/approvals
```

内部 AgentRun 创建接口不能伪造 `running`；内部 ToolCall 创建接口不接受
`audit_json`，审计字段由服务端生成。

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

成功响应直接返回 OpenAPI 声明的资源或分页对象，不额外包裹 `data`：

```json
{
  "id": "uuid"
}
```

错误响应为扁平稳定结构：

```json
{
  "code": "validation_error",
  "message": "请求参数校验失败。",
  "detail": [],
  "trace_id": "trace_..."
}
```

### 1.3 分页

列表接口统一支持：

```text
?limit=20&cursor=20
```

`cursor` 是非负十进制 offset，只接受 1 至 18 位数字。非法 cursor 返回
`422 validation_error`，不回退到第一页。

返回：

```json
{
  "items": [],
  "page": {
    "limit": 20,
    "next_cursor": "40"
  }
}
```

Project、Task、Requirement、TechnicalDesign、DevelopmentPlan、AgentRun、
ToolCall 和 Approval 按 `created_at/id` 最新优先。Timeline 为避免小页漏掉
最新事件，先倒序取页，再在当前页内恢复时间正序。

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

成功状态码：`201 Created`。

响应：

```json
{
  "id": "uuid",
  "name": "sample-repo-python",
  "repo_url": "http://gitea.local/cloudhelm/sample-repo-python.git",
  "default_branch": "main",
  "provider": "gitea",
  "created_at": "2026-07-07T10:00:00Z",
  "updated_at": "2026-07-07T10:00:00Z"
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
  "risk_level": "L1",
  "created_by": "control-console"
}
```

`constraints` 属于 RequirementSpec 的 `constraints_json`，不属于 Task 创建
DTO；Task 创建接口也不接受 `auto_start`。

成功状态码：`201 Created`。

响应：

```json
{
  "id": "uuid",
  "project_id": "uuid",
  "title": "增加用户注册登录和个人资料功能",
  "description": "使用 FastAPI + PostgreSQL + JWT，实现注册、登录、个人资料接口，并补充 pytest。",
  "source_type": "manual",
  "source_ref": null,
  "status": "created",
  "risk_level": "L1",
  "current_phase": "Created",
  "created_by": "control-console",
  "created_at": "2026-07-07T10:00:00Z",
  "updated_at": "2026-07-07T10:00:00Z"
}
```

副作用：

- 写入 `tasks`。
- 写入 `event_logs: TaskCreated`。
- 创建后保持 `created / Created`；调用方必须单独调用
  `POST /api/tasks/{task_id}/start`。

### POST /api/tasks/{task_id}/start 与 /run-next

请求：

```json
{
  "actor_id": "control-console",
  "reason": "用户确认开始编排",
  "expected_phase": "Created"
}
```

`expected_phase` 为兼容旧调用方保留可选，但控制台应发送当前 Task 快照中的
阶段。服务端先锁定 Task 行再比较阶段；不一致返回：

```json
{
  "code": "orchestration_phase_changed",
  "message": "任务阶段已变化，请刷新后再推进编排。",
  "detail": {
    "expected_phase": "Created",
    "actual_phase": "RequirementClarifying"
  },
  "trace_id": "trace_..."
}
```

### POST /api/tasks/{task_id}/pause

请求：

```json
{
  "reason": "用户需要补充约束"
}
```

副作用：

- `tasks.status = paused`，保留 `current_phase`，并在 `TaskPaused.payload.from_status` 记录暂停前状态。
- 写入 `TaskPaused`。
- Orchestrator 停止调度新的工具调用；已运行的安全工具可允许自然结束。

### POST /api/tasks/{task_id}/resume

- 读取当前任务最近一次 `TaskPaused` 事件的 `from_status` 并恢复原状态。
- `created`、`running`、`waiting_approval` 暂停后分别恢复自身，不统一覆盖为 `running`；`current_phase` 始终保留。
- 写入 `TaskResumed`，非法状态返回 `409`。

### POST /api/tasks/{task_id}/cancel

- `tasks.status = cancelled`，保留当前业务阶段用于审计。
- 级联把 active AgentRun 和 pending/running/waiting ToolCall 标记为
  `cancelled`，把 pending Approval 标记为 `expired`。
- 对实际关闭的资源写入 `AgentRunCancelled`、`ToolCallCancelled`、
  `ApprovalExpired`，最后写入 `TaskCancelled`。

### POST /api/tasks/{task_id}/takeover（增强版规划接口，M7 不实现）

该接口及 `remote_sessions`/WebSocket terminal 属于 M7 之后的增强能力。M7
远端只提供服务状态、受限日志和固定只读 diagnostics。

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
  "remote_session_id": "uuid",
  "stream_url": "/api/remote-sessions/{session_id}/stream"
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

同一 Task 下 `version` 从 1 递增。新 Requirement 会使旧 TechnicalDesign、
DevelopmentPlan 和匹配的 pending Approval 失效。approve/request-changes
只能作用于当前最新版，历史版本返回 `409 stale_requirement`。

### POST /api/requirements/{requirement_id}/approve

副作用：

- `requirement_specs.status = approved`。
- 写入 `RequirementSpecApproved`。
- 非 paused Task 进入 `running / Designing`；paused Task 只更新业务阶段。

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

同一 Task 下技术设计版本递增。新设计使旧 DevelopmentPlan 和匹配 pending
Approval 失效；历史设计评审返回 `409 stale_technical_design`。批准当前设计
后，非 paused Task 进入 `running / Planning`。

## 4.1 Development Plan API

### GET /api/tasks/{task_id}/development-plans

返回 Planner Agent 生成的开发计划列表：

```json
{
  "items": [
    {
      "id": "uuid",
      "task_id": "uuid",
      "project_id": "uuid",
      "technical_design_id": "uuid",
      "summary": "M4 后续实现任务图",
      "steps_json": [],
      "risks_json": [],
      "status": "ready_for_review",
      "version": 1,
      "created_by_agent_run_id": "uuid"
    }
  ],
  "page": {
    "limit": 50,
    "next_cursor": null
  }
}
```

### GET /api/development-plans/{plan_id}

读取单个 DevelopmentPlan。M4 不提供外部创建接口；计划只能由 Planner Agent 经 Orchestrator 写入。

## 5. Agent Run API

### GET /api/tasks/{task_id}/agent-runs

返回：

```json
{
  "items": [
    {
      "id": "uuid",
      "task_id": "uuid",
      "conversation_id": "uuid",
      "conversation_turn": 2,
      "agent_type": "requirement",
      "status": "succeeded",
      "model_name": "gpt-5.6-sol",
      "input_tokens": 38530,
      "cached_input_tokens": 11008,
      "output_tokens": 4200,
      "provider_request_count": 2,
      "provider_requests": [
        {
          "response_id": "resp_...",
          "prompt_cache_key": "cloudhelm:uuid",
          "input_tokens": 20000,
          "cached_input_tokens": 6144,
          "output_tokens": 1900,
          "cache_hit": true
        }
      ],
      "provider_response_id": "resp_...",
      "prompt_cache_key": "cloudhelm:uuid",
      "cost_usd": "0.001200",
      "started_at": "2026-07-07T10:00:00Z",
      "finished_at": "2026-07-07T10:00:10Z"
    }
  ],
  "page": {
    "limit": 50,
    "next_cursor": null
  }
}
```

用途：

- 控制台 Agent Timeline。
- token/cache 证据和后续成本统计。
- 失败诊断。

外部 provider 的 `AgentRunStarted` 事件记录 model、API mode、
`reasoning_effort` 和 `max_attempts`。可恢复 provider 错误耗尽重试后，
AgentRun 为 `failed`，Task 为 `paused`，事件 payload 的 `recoverable=true`。

`input_tokens`、`cached_input_tokens` 和 `output_tokens` 是 AgentRun 内全部已完成
供应商请求的总量；`provider_requests` 保留每次结构化修复请求的原始 usage。
`cache_hit` 只能由该请求 `cached_input_tokens > 0` 推导，不能由 CloudHelm
估算。普通角色的 `conversation_id` 和 `prompt_cache_key` 必须相同，
`conversation_turn` 只在结构化输出、业务产物与事件均成功保存后递增。

模型请求始终使用 `stream=true` 的 HTTP SSE，不实现 WebSocket。官方显式缓存
断点配置启用时发送 `prompt_cache_options.mode=explicit` 和 content
`prompt_cache_breakpoint`；当前兼容端点于 2026-07-11 的真实探测返回 HTTP
502，因此默认关闭并依靠稳定前缀自动缓存。

## 6. Tool Call API

### GET /api/tasks/{task_id}/tool-calls

返回字段：

- tool_call_id
- agent_run_id
- tool_name
- risk_level
- arguments_summary
- audit_json
- status
- approval_id
- started_at
- finished_at
- result_summary
- error_code

`arguments_json` 与 `result_json` 数据库存储均为脱敏安全投影；文件正文只保存
长度和 SHA-256。`git.diff` / `git.format_patch` 的原始结果仅在同进程执行期
用于创建 lossless Artifact，不能从 ToolCall API 取回。
`audit_json` 由服务端生成，至少包含 tool、task、AgentRun、Agent 类型、
风险、幂等键、参数 hash、原因 hash、终态和错误码。

### POST /api/tool-calls/{tool_call_id}/retry（规划接口，M1-M6 未实现）

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
- M4 设计/计划审批由下一次 Orchestration 或 M6 local-development 请求重新读取；
  M5/M6 尚未实现审批后自动恢复通用高风险 ToolCall。

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
- 连接建立后服务端继续轮询/tail 新增 EventLog；M7 必须验证 CI、deployment 和
  heartbeat 状态事件能在同一连接中到达，而不只支持历史回放。

## 9. Deployment / Remote Ops API（M7 渐进实现）

M7-1 已实现 Environment、RemoteTarget 和 machine-auth heartbeat，并同步到
FastAPI/共享 OpenAPI。release candidate、CI、deployment、service/log API 仍是
后续 M7 契约，以
[09-m7-ci-remote-deployment-flow.md](09-m7-ci-remote-deployment-flow.md)
为权威细化设计。

已实现：

```text
POST /api/projects/{project_id}/environments
GET  /api/projects/{project_id}/environments
GET  /api/environments/{environment_id}
POST /api/environments/{environment_id}/remote-targets
GET  /api/environments/{environment_id}/remote-targets
POST /api/remote-agents/heartbeat
```

Environment `base_url` 在 M7-1 只保存/展示，后续健康检查不得直接使用调用方
host，必须经过服务端 profile/allowlist。RemoteTarget 注册只接受 profile key，
读取隐藏 credential ref 和完整 endpoint。

### PUT /api/projects/{project_id}/repository-binding

请求体严格为：

```json
{
  "profile_key": "demo-gitea-repository"
}
```

- 服务端 profile 派生 provider、repository external id/owner/name、clone URL、
  default branch、credential ref、workflow id 和 release ref prefix。
- URL、token、credential、workflow、remote、refspec 或其他额外字段返回 422。
- response 不返回 clone URL、credential ref、profile 文件路径或 credential map。
- PUT 先比较 old/new internal snapshot hash。相同 profile key、物化字段和 active
  状态返回原 binding，不改 `updated_at`、不写事件、不失效 Candidate。
- 只有 internal snapshot hash 变化或 binding 变为 disabled 时，旧
  `pending_approval|approved` Candidate 与 pending Approval 才在同一事务
  stale/expired；published 历史记录不改写。
- PUT 先锁 Binding，再按 UUID 顺序锁 Candidate/Approval；Candidate POST 按
  `Task -> Binding -> PullRequestRecord -> existing Candidate` 加锁并持有
  Binding `FOR UPDATE` 到事务提交，关闭 snapshot 读取与 Candidate 插入之间的
  并发空窗。
- `(provider, repository_external_id)` 与
  `(provider, lower(owner), lower(name))` 冲突返回 409。

### GET /api/projects/{project_id}/repository-binding

返回 public repository identity、profile key、default branch、workflow id、
release ref prefix、status 和审计时间。Project 或 binding 不存在时分别返回稳定
404。

### POST /api/tasks/{task_id}/release-candidate

请求体固定为严格空对象：

```json
{}
```

行为：

- 服务端读取最新版 open PullRequestRecord 与 active ProjectRepositoryBinding。
- PullRequestRecord 必须存在 `created_by_agent_run_id`；Approval 的
  `requested_by_agent_run_id` 固定使用该实现 AgentRun，缺失时返回
  `409 m6_pull_request_creator_required`。
- 重新核验 M6 四类 Artifact 仍可用且属于同一 plan/recipe/evidence set。
- 持久化不含 secret 的 binding snapshot JSON，以及覆盖内部 clone URL 与
  credential ref、profile key 的 snapshot hash。
- 服务端派生完整 commit、candidate ref、idempotency key 和 request hash。
- 在同一短事务原子创建 ReleaseCandidate、L2 ApprovalRequest 与无外部副作用的
  `release_candidate_reconcile` WorkflowJob。
- `approve_release_candidate` 是保留 action；通用 Approval create endpoint
  返回 `422 approval_action_reserved`，只能由 CandidateService 内部事务创建。
- approve/reject 将 plain UUID 或 `agent-run:<UUID>` actor id 规范化后与实现
  AgentRun 比较，相同返回 `403 approval_self_decision_forbidden`。
- 提交后通过 durable dispatcher 同一 reserve 入口 best-effort 投递；broker
  失败由周期扫描补投。
- 不 push、不触发 CI、不创建外部副作用 WorkflowJob。
- M7-2 不修改 Task status/current phase；完整 Orchestrator 状态推进留到后续纵切。
- 调用方提交 URL、credential、workflow、ref、commit 或其他额外字段时返回 422。

canonical 固定为：

```text
safe snapshot schema=m7.repository-binding.snapshot.v1
internal snapshot schema=m7.repository-binding.internal-snapshot.v1
candidate request schema=m7.release-candidate.request.v1
candidate request action=approve_release_candidate
target_ref={release_ref_prefix}/{task_id}/{full_commit_sha}/{snapshot_hash_hex}
idempotency_key=release_candidate:v1:<request_hash hex>
```

三类 hash 均复用
`cloudhelm_tool_gateway.audit.stable_json_hash`，其 JSON 序列化固定为
`ensure_ascii=False + sort_keys=True + default=str`，结果格式为
`sha256:<64 lowercase hex>`。

顺序或并发重复请求按
`(pull_request_record_id, binding_snapshot_sha256)` 返回同一 Candidate、Approval
与内部 reconcile job。首次创建返回 201，幂等命中返回 200。已 rejected 时仍返回
原记录且不创建新审批；重新申请必须产生新 PR 或新 binding snapshot。最新版 PR
或 binding snapshot 变化后，旧 pending/approved Candidate 转 stale。

reconcile job 只核验 PR、snapshot、request hash 与 Approval freshness；检测到
漂移时原子 stale/expired，但 job 自身 succeeded。它不替代 approve/reject 时的
同步 freshness 校验，job id 只进入 EventLog/测试证据，不提供调用方 CRUD API。

### POST /api/tasks/{task_id}/remote-deployment/start

请求：

```json
{
  "environment_id": "uuid"
}
```

行为：

- 服务端要求已有 approved ReleaseCandidate，再读取 Environment 和 active
  RemoteTarget。
- 不重复创建第一道 release candidate approval。
- 不在 HTTP 事务中等待 CI、Git 或远端副作用。
- 调用方不得提交 commit、image、target endpoint、workflow path 或 credential。

### POST /api/tasks/{task_id}/remote-deployment/run-next

- 每次只推进 publish candidate、workflow dispatch、CI poll、Release Agent、
  deployment approval、dispatch、health verification 或 Monitoring handoff 中
  的一个动作。
- 外部动作通过 PostgreSQL WorkflowJob + Redis/Celery 执行，不在 HTTP 事务内
  等待 Git、CI、HTTP 或 Compose。
- deployment approval 前禁止任何 Remote Agent 副作用。

### POST /api/remote-agents/heartbeat

- 原始 body 默认限制 16384 bytes，超限在 JSON 解析前返回 413。
- 使用 machine credential 签名；签名覆盖 method、path、timestamp、nonce 和
  body SHA-256。
- 固定请求头为 `X-CloudHelm-Target-Id`、`X-CloudHelm-Agent-Id`、
  `X-CloudHelm-Key-Id`、`X-CloudHelm-Timestamp`、`X-CloudHelm-Nonce` 和
  `X-CloudHelm-Signature`。
- canonical string 精确为
  `METHOD\nPATH\nTIMESTAMP\nNONCE\nBODY_SHA256`，无末尾换行；signature 为
  lowercase hex HMAC-SHA256。
- body hash 必须基于实际发送的原始 UTF-8 bytes，签名后不得重新序列化 JSON。
- credential 绑定 target/agent/key id；跨 target、过期、撤销和 replay 返回
  稳定认证错误。
- nonce 在独立短事务中消费，保留时间覆盖完整 timestamp 容差窗口；同步
  SQLAlchemy/psycopg 工作在线程池执行，不阻塞 ASGI event loop。
- secret fingerprint 漂移返回脱敏配置错误；轮换使用新的 key/ref。
- 响应不返回 credential ref、完整 endpoint 或 secret。

M7-1 的 online/offline/recovery 事件已写入 PostgreSQL，但 `task_id=null`；
项目/环境事件查询与实时 SSE 尚未实现，仍属于后续 M7。

### GET /api/tasks/{task_id}/release-candidate

- M7-2 返回 candidate、binding snapshot/hash、审批状态/expiry/consumed 和远端
  ref 校验字段；CI 关联状态在后续 CIRun 纵切补充。
- commit 使用完整 SHA，credential 和原始 provider token 不返回。
- 查询优先返回 `pending_approval|approved` 当前 Candidate；没有审批/发布前记录时，
  返回 `created_at,id` 最新历史 Candidate。

### GET /api/services/{service_id}/logs

查询参数：

```text
?since=15m&query=error&limit=200
```

返回：

```json
[
  {
    "ts": "2026-07-07T10:00:00Z",
    "level": "error",
    "service": "api",
    "message": "database connection failed"
  }
]
```

### POST /api/services/{service_id}/restart-request

必须创建 ApprovalRequest，不能直接重启。

## 10. Monitoring / Incident API（M8 以后规划）

本节是后续契约草案，不在 M1-M7-1 FastAPI OpenAPI 中。

### POST /api/alerts/{alert_id}/create-incident

副作用：

- 写入 Incident。
- 写入 `ProjectIncidentCreated`。
- 触发 SRE Agent 分析。

### POST /api/incidents/{incident_id}/runbook-proposal

响应：

```json
{
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
```
## M5 实现同步：Tool Gateway API

### `GET /api/tool-gateway/tools`

- 调用方：控制台、Agent Runtime、调试脚本。
- 返回：分页结构，`items` 中包含工具名、描述、风险等级、是否需要审批、`allowed_agent_types`、`allow_system_call`、审计字段和参数 JSON Schema。
- 权限：M5 单用户演示环境默认可读；后续按项目/角色过滤。

### `POST /api/tasks/{task_id}/tool-gateway/call`

- 调用方：Platform API 内部 Agent executor 或受控开发调试脚本。
- 请求：`agent_run_id`、成对出现的 `provider_call_id/provider_item_type`、
  `tool_name`、`risk_level`、`idempotency_key`、`arguments`、`reason`。
  `agent_type` 由 Platform API 从 AgentRun 解析，不由公开请求提交。
- 成功响应：`ToolCallRead`，包含状态、参数摘要、结果摘要、stdout/stderr 摘要、耗时、错误码和审批 ID。
- 幂等：先写入并提交 `pending` ToolCall，依靠数据库唯一索引原子抢占同一
  `task_id` 下的 `idempotency_key`。完全相同且已经结束的重放返回已有
  ToolCall；相同 `idempotency_key` 或 `provider_call_id` 对应不同调用时返回
  `409 idempotency_conflict`，已有调用仍在执行时返回
  `409 tool_call_in_progress`，所有冲突路径都不会重复执行真实副作用。
- M6 execution recipe：带 `workflow_step` 的 AgentRun 只能由 Platform API
  内部本地开发执行器提交调用；公开 Tool Gateway HTTP 入口不能绕过该边界。
  执行器按工具名、Pydantic 默认值规范化后的参数和允许调用次数进行精确绑定，
  未批准调用写入失败 ToolCall 和审计指纹，但不进入工具 handler。
- 权限：副作用工具必须绑定当前任务 AgentRun，且 Agent 类型必须在工具白名单内；仅工具显式声明 `allow_system_call=true` 时允许无 AgentRun 的平台内部调用。
- AgentRun 必须处于 `running`；Tool Gateway 内部 `agent_run_id` 和 `agent_type` 必须同时存在或同时为空。
- 事件副作用：写入 `ToolCallStarted`，随后写入 `ToolCallSucceeded`、`ToolCallFailed` 或 `ApprovalRequested`。
- 审批：L3/L4 或声明 `requires_approval=true` 时创建 `approval_requests`，ToolCall 状态为 `waiting_approval`，不执行工具。
- 限流：按 `agent_run_id` 或 `task_id` 执行单实例滑动窗口限流，默认 60 秒 60 次；超额结果为失败 ToolCall，错误码 `rate_limit_exceeded`，并写入 `ToolCallFailed`。

### `GET /api/approvals`

- 查询参数：可选 `task_id`、`status`、`limit`、`cursor`。
- 控制台任务详情必须传入 `task_id` 由数据库查询过滤，不允许先读取全局分页结果再在前端筛选。
