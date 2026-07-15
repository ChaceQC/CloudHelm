# Environment / Deployment API

> 来源：[设计书 12 章](../../云舵 CloudHelm 毕设设计书.md)  
> 运行时契约：`packages/shared-contracts/openapi/cloudhelm.openapi.yaml`

## 1. 实现状态

M7-1 已实现并进入共享 OpenAPI：

```text
POST /api/projects/{project_id}/environments
GET  /api/projects/{project_id}/environments
GET  /api/environments/{environment_id}
POST /api/environments/{environment_id}/remote-targets
GET  /api/environments/{environment_id}/remote-targets
POST /api/remote-agents/heartbeat
```

M7-2 已冻结、尚待本轮代码实现的契约：

```text
PUT  /api/projects/{project_id}/repository-binding
GET  /api/projects/{project_id}/repository-binding
POST /api/tasks/{task_id}/release-candidate
GET  /api/tasks/{task_id}/release-candidate
```

Candidate POST 请求体固定为严格空对象 `{}`，是第一道 approval 的唯一创建入口。
后续 `remote-deployment/start` 只选择 Environment/RemoteTarget 并要求已有 approved
candidate，不再重复创建第一道审批。

以下端点仍是后续 M7 契约：

```text
POST /api/remote-targets/{target_id}/test-connection
GET  /api/tasks/{task_id}/ci-runs
POST /api/webhooks/ci/gitea
GET  /api/tasks/{task_id}/remote-deployment
POST /api/tasks/{task_id}/remote-deployment/start
POST /api/tasks/{task_id}/remote-deployment/run-next
GET  /api/projects/{project_id}/deployments
GET  /api/deployments/{deployment_id}
POST /api/deployments/{deployment_id}/health-check
POST /api/deployments/{deployment_id}/rollback-request
```

M7 完整闭环仍要求 release candidate、真实 CI、不可变 digest、第二道审批、
Deployment Controller、Remote Agent deployment operation 和 Monitoring 交接。

## 2. 调用边界

- Environment/RemoteTarget 管理端点沿用当前本地控制面的调用边界；M7-1 尚未新增
  面向公网的用户认证层，因此只能部署在受控网络入口后。
- heartbeat 只接受 Remote Agent machine HMAC authentication。
- RemoteTarget endpoint、TLS fingerprint、agent identity 和 credential 都来自
  Platform API 服务端 profile；普通请求只能提交 `profile_key`。
- API 不返回 credential ref、machine secret、完整 endpoint、profile 文件路径或
  原始错误输入。
- 列表统一使用 `limit=1..100` 和十进制 offset `cursor`；响应结构为
  `{"items": [...], "page": {"limit": 50, "next_cursor": null}}`。

## 3. Environment API

### 3.1 创建 Environment

```http
POST /api/projects/{project_id}/environments
Content-Type: application/json
```

请求：

```json
{
  "name": "staging",
  "environment_type": "staging",
  "base_url": "https://staging.example.test"
}
```

约束：

- `name` 最长 63 字符，只允许小写字母、数字和短横线。
- `environment_type` 只允许 `staging`、`demo`。
- `base_url` 必须为 HTTPS，不能包含 userinfo、query 或 fragment。
- 不接受 `env_profile_ref` 或其他额外字段。
- M7-1 只保存和展示 `base_url`，不据此发起网络访问；后续健康检查必须通过
  服务端 profile/allowlist 派生目标。

成功响应 `201`：

```json
{
  "id": "00000000-0000-0000-0000-000000000101",
  "project_id": "00000000-0000-0000-0000-000000000001",
  "name": "staging",
  "environment_type": "staging",
  "status": "active",
  "base_url": "https://staging.example.test/",
  "created_at": "2026-07-16T00:00:00Z",
  "updated_at": "2026-07-16T00:00:00Z"
}
```

副作用：同一事务写 `EnvironmentCreated`。

### 3.2 列表与详情

```http
GET /api/projects/{project_id}/environments?limit=50&cursor=0
GET /api/environments/{environment_id}
```

列表按 `created_at DESC, id DESC` 排序。项目或 Environment 不存在时返回稳定
404；非法 cursor 返回统一 422。

### 3.3 M9 environment-scope 响应边界

接入用户/RBAC 后，environment-scope 的 Operator、Approver、Auditor 或 Viewer
不因此获得独立 `project.read`、`task.read`、`artifact.read` 或 `ci.read`。
Environment、Deployment 和 Approval 详情可以按当前资源直接关联关系嵌入最小
脱敏上下文：

```json
{
  "parent_project": {
    "id": "uuid",
    "name": "sample-service"
  },
  "related_task": {
    "id": "uuid",
    "title": "发布 sample-service",
    "status": "WaitingDeployApproval"
  },
  "decision_evidence": {
    "commit_sha": "40-hex",
    "image_digest": "sha256:...",
    "ci_conclusion": "succeeded",
    "security_conclusion": "passed",
    "risk_level": "L2"
  }
}
```

- `parent_project` 只包含 id/display name；`related_task` 只包含 id/title/status，且
  没有直接关联 Task 时为 null。
- `decision_evidence` 只来自当前 Deployment/ReleasePlan/Approval 已绑定的不可变
  snapshot，不返回其他 Artifact/CI 正文。
- 以上摘要不能用于调用 Project/Task/Artifact/CIRun 列表或详情 API；服务端仍按
  对应 project scope permission 独立拒绝。
- project/environment-scope 的 Auditor、Viewer 也只在资源匹配 binding scope 时
  获得相应响应，不能跨 binding 枚举。

## 4. RemoteTarget API

### 4.1 注册受控目标

```http
POST /api/environments/{environment_id}/remote-targets
Content-Type: application/json
```

请求：

```json
{
  "profile_key": "demo-linux-agent",
  "display_name": "Demo Linux Agent"
}
```

成功响应 `201`：

```json
{
  "id": "00000000-0000-0000-0000-000000000201",
  "environment_id": "00000000-0000-0000-0000-000000000101",
  "display_name": "Demo Linux Agent",
  "target_type": "linux_remote_agent",
  "agent_id": "remote-agent-demo",
  "endpoint_display": "https://<redacted>:9443",
  "tls_fingerprint": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "credential_fingerprints": [
    "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  ],
  "status": "offline",
  "agent_version": null,
  "capabilities": [],
  "last_heartbeat_at": null,
  "last_error_code": null,
  "last_event_at": null,
  "last_status_changed_at": "2026-07-16T00:00:00Z",
  "created_at": "2026-07-16T00:00:00Z",
  "updated_at": "2026-07-16T00:00:00Z"
}
```

服务端在同一事务创建 target 与 credential 元数据并写
`RemoteTargetRegistered`。profile 至少要有一个当前有效的 `heartbeat` scope
credential；同一 Environment/agent id 由 PostgreSQL 唯一约束串行裁决。

### 4.2 目标列表

```http
GET /api/environments/{environment_id}/remote-targets?limit=50&cursor=0
```

M7-1 尚未接入周期 worker。该读取会把超过
`CLOUDHELM_REMOTE_AGENT_OFFLINE_TIMEOUT_SECONDS` 的 online/degraded target
收敛为 offline 并写 `RemoteAgentOffline`；下一次合法 heartbeat 会写
`RemoteAgentRecovered`。这是临时 reconciliation 边界，不等于实时自主检测。

## 5. Machine-auth heartbeat

### 5.1 请求头

六个请求头全部必填：

```text
X-CloudHelm-Target-Id
X-CloudHelm-Agent-Id
X-CloudHelm-Key-Id
X-CloudHelm-Timestamp
X-CloudHelm-Nonce
X-CloudHelm-Signature
```

- target id 为 UUID。
- timestamp 为 Unix 秒。
- nonce 为 16 至 128 字符的一次性随机值。
- signature 为 lowercase hex HMAC-SHA256。

canonical string 无末尾换行：

```text
METHOD\nPATH\nTIMESTAMP\nNONCE\nBODY_SHA256
```

`BODY_SHA256` 基于实际发送的原始 UTF-8 bytes。Remote Agent 必须先生成固定
bytes、签名，再使用同一 bytes 作为 HTTP content，不能签名后重新序列化。

### 5.2 请求与响应

```http
POST /api/remote-agents/heartbeat
Content-Type: application/json
```

请求：

```json
{
  "target_id": "00000000-0000-0000-0000-000000000201",
  "agent_id": "remote-agent-demo",
  "agent_version": "0.5.1",
  "capabilities": ["capabilities", "health", "heartbeat", "version"],
  "reported_at": "2026-07-16T00:00:00Z"
}
```

响应 `200`：

```json
{
  "target_id": "00000000-0000-0000-0000-000000000201",
  "agent_id": "remote-agent-demo",
  "status": "online",
  "accepted_at": "2026-07-16T00:00:01Z",
  "next_heartbeat_after_seconds": 20
}
```

处理规则：

1. ASGI middleware 在 JSON 解析前限制原始 body，默认 16384 bytes。
2. 同步数据库认证在线程池中使用独立短 Session，校验后立即提交 nonce。
3. credential 必须绑定 target/agent/key/scope/lifecycle。
4. 错误签名对未知、撤销、scope、禁用和配置异常不泄露可枚举差异。
5. secret SHA-256 必须与数据库 fingerprint 一致；轮换新增
   `key_id + credential_ref`，不原地替换同一 ref。
6. nonce 保留时间覆盖 timestamp 的完整容差窗口；顺序和并发 replay 均返回
   `machine_auth_replay`。
7. heartbeat 状态更新使用独立事务和 Target 行锁。

语法错误 JSON 在 FastAPI 解析阶段直接返回 422，不消费 nonce；语法有效且通过
HMAC 后，后续 DTO、reported_at 或 body/header identity 校验失败仍会消费 nonce，
防止同一已认证请求重放。

## 6. M7-2 RepositoryBinding / ReleaseCandidate 契约

### 6.1 RepositoryBinding PUT / GET

```http
PUT /api/projects/{project_id}/repository-binding
Content-Type: application/json
```

请求只允许：

```json
{
  "profile_key": "demo-gitea-repository"
}
```

成功响应：

```json
{
  "id": "00000000-0000-0000-0000-000000000301",
  "project_id": "00000000-0000-0000-0000-000000000001",
  "provider": "gitea",
  "profile_key": "demo-gitea-repository",
  "repository_external_id": "42",
  "repository_owner": "cloudhelm",
  "repository_name": "sample-api",
  "default_branch": "dev",
  "workflow_id": ".gitea/workflows/ci.yml",
  "release_ref_prefix": "refs/heads/cloudhelm/candidates",
  "status": "active",
  "created_at": "2026-07-16T00:00:00Z",
  "updated_at": "2026-07-16T00:00:00Z"
}
```

- profile 由 `CLOUDHELM_REPOSITORY_PROFILES` 或权限受控 UTF-8 文件提供。
- clone URL、credential ref、credential map 和 profile 文件路径不进入响应。
- `release_ref_prefix` 必须是无尾斜杠的完整 `refs/heads/...`，并通过等价
  `git check-ref-format` 校验。
- PUT 重算 old/new internal snapshot hash；完全相同的 profile key、物化字段和
  active 状态返回原 binding，不改 `updated_at`、不写事件、不失效 Candidate。
- 只有 internal snapshot hash 变化或 binding 变为 disabled 时，旧
  `pending_approval|approved` Candidate 与 pending Approval 才同事务
  stale/expired。
- PUT 先锁 Binding，再按 UUID 顺序锁 Candidate/Approval；Candidate POST 按
  `Task -> Binding -> PullRequestRecord -> existing Candidate` 加锁并在插入提交前
  持有 Binding `FOR UPDATE`，从数据库层串行化 PUT/POST。

GET 使用同一 public response：

```http
GET /api/projects/{project_id}/repository-binding
```

### 6.2 Candidate POST / GET

```http
POST /api/tasks/{task_id}/release-candidate
Content-Type: application/json
```

请求体固定为严格空对象：

```json
{}
```

首次创建返回 201，幂等命中返回 200：

```json
{
  "candidate": {
    "id": "00000000-0000-0000-0000-000000000401",
    "task_id": "00000000-0000-0000-0000-000000000011",
    "project_id": "00000000-0000-0000-0000-000000000001",
    "pull_request_record_id": "00000000-0000-0000-0000-000000000021",
    "repository_binding_id": "00000000-0000-0000-0000-000000000301",
    "binding_snapshot": {
      "schema_version": "m7.repository-binding.snapshot.v1",
      "provider": "gitea",
      "repository_external_id": "42",
      "repository_owner": "cloudhelm",
      "repository_name": "sample-api",
      "default_branch": "dev",
      "workflow_id": ".gitea/workflows/ci.yml",
      "release_ref_prefix": "refs/heads/cloudhelm/candidates"
    },
    "binding_snapshot_sha256": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "commit_sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "target_ref": "refs/heads/cloudhelm/candidates/00000000-0000-0000-0000-000000000011/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "request_hash": "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
    "status": "pending_approval",
    "approval_id": "00000000-0000-0000-0000-000000000501",
    "remote_verified_sha": null,
    "idempotency_key": "release_candidate:v1:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
    "approved_at": null,
    "published_at": null,
    "created_at": "2026-07-16T00:00:00Z",
    "updated_at": "2026-07-16T00:00:00Z"
  },
  "approval": {
    "id": "00000000-0000-0000-0000-000000000501",
    "action": "approve_release_candidate",
    "risk_level": "L2",
    "resource_type": "release_candidate",
    "resource_id": "00000000-0000-0000-0000-000000000401",
    "status": "pending",
    "requested_by_agent_run_id": "00000000-0000-0000-0000-000000000031",
    "request_hash": "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
    "expires_at": "2026-07-17T00:00:00Z",
    "consumed_at": null
  }
}
```

服务端固定：

- 读取最新版 open M6 PullRequestRecord 与 active binding。
- 按 `m7.repository-binding.snapshot.v1` 构造八字段安全 snapshot。
- 内部 snapshot hash 额外覆盖 profile key、clone URL 和 credential ref。
- hash 复用 `stable_json_hash`，使用
  `ensure_ascii=False + sort_keys=True + default=str`，返回
  `sha256:<64 lowercase hex>`。
- target ref 为
  `{release_ref_prefix}/{task_id}/{full_commit_sha}/{snapshot_hash_hex}`。
- Candidate request schema 为 `m7.release-candidate.request.v1`，action 固定为
  `approve_release_candidate`，
  idempotency key 为 `release_candidate:v1:<request_hash hex>`。
- Candidate、Approval 和 `release_candidate_reconcile` job 同事务创建；job id
  不进入 public response，也没有调用方 CRUD API。
- Approval 的 `requested_by_agent_run_id` 固定为
  PullRequestRecord 的 `created_by_agent_run_id`；缺失时 Candidate 创建失败。
- approve/reject 把 plain UUID 或 `agent-run:<UUID>` actor id 规范化后与上述实现
  AgentRun 比较，相同则拒绝自批。
- `approve_release_candidate` 是保留 action；通用 Approval create endpoint 返回
  `422 approval_action_reserved`，只能由 CandidateService 内部事务创建。
- broker 暂时不可用不回滚已提交 Candidate；durable dispatcher 后续补投。
- reconcile job 无外部副作用，且不替代 ApprovalService 的同步 freshness 校验。
- M7-2 Candidate create/approve/reject 不改 Task status/current phase；后续
  Orchestrator 纵切再接入 WaitingMergeApproval/CIValidating。

顺序/并发重复请求按
`(pull_request_record_id, binding_snapshot_sha256)` 返回同一资源。rejected 后仍返回
原记录，不创建新审批；新申请需要新 PR 或新 snapshot。

GET 返回同一 envelope；优先当前 `pending_approval|approved` Candidate，否则返回
`created_at,id` 最新历史记录：

```http
GET /api/tasks/{task_id}/release-candidate
```

## 7. 事件与查询边界

M7-1 会写：

- `EnvironmentCreated`
- `RemoteTargetRegistered`
- `RemoteAgentOnline`
- `RemoteAgentHeartbeat`
- `RemoteAgentOffline`
- `RemoteAgentRecovered`

高频 heartbeat 只更新 `last_heartbeat_at`，在详情变化或超过事件间隔时才写
`RemoteAgentHeartbeat`。这些事件当前 `task_id=null`，project/environment/target
身份位于 payload；现有 Task Timeline/SSE 不查询它们。项目/环境事件 API 和实时
SSE 留在后续 M7，不能描述为 M7-1 已交付。

## 8. 稳定错误码

|HTTP|错误码|含义|
|---:|---|---|
|404|`project_not_found`|Project 不存在。|
|404|`repository_binding_not_found`|Project 尚未配置 repository binding。|
|404|`release_candidate_not_found`|Task 尚无 Candidate。|
|404|`environment_not_found`|Environment 不存在。|
|409|`repository_binding_conflict`|Repository identity 已绑定到其他 Project。|
|409|`repository_binding_inactive`|Binding 已禁用。|
|409|`m6_pull_request_required`|缺少符合门禁的最新 open PullRequestRecord。|
|409|`m6_pull_request_creator_required`|PR record 缺少可审计的实现 AgentRun。|
|409|`release_candidate_conflict`|同一 Task 存在不同业务身份的审批/发布前 Candidate。|
|409|`release_candidate_stale`|Candidate 的 PR、binding snapshot 或 request hash 已漂移。|
|409|`approval_expired`|资源审批已超过有效期。|
|409|`approval_consumed`|资源审批已被单次消费。|
|409|`approval_request_hash_mismatch`|Approval 与当前资源 hash 不一致。|
|403|`approval_self_decision_forbidden`|实现 AgentRun 尝试自批。|
|422|`approval_action_reserved`|通用 Approval create endpoint 提交 M7 保留 action。|
|409|`environment_name_conflict`|项目内 Environment 名称重复。|
|409|`environment_not_active`|Environment 不允许注册目标。|
|409|`remote_target_conflict`|同一 Environment 已登记该 Agent。|
|422|`remote_target_profile_not_found`|profile key 不存在。|
|422|`repository_profile_not_found`|repository profile key 不存在。|
|503|`repository_profile_configuration_invalid`|repository profile 文件不可读或非法。|
|503|`repository_profile_unusable`|repository credential/ref 配置不可用。|
|503|`remote_target_profile_configuration_invalid`|profile 文件不可读或非法。|
|503|`remote_target_profile_unusable`|没有可用 heartbeat credential。|
|503|`remote_agent_credential_not_configured`|注册阶段 secret 引用缺失。|
|503|`remote_agent_credential_too_short`|secret 小于 32 bytes。|
|503|`remote_agent_credential_fingerprint_mismatch`|secret 与登记 fingerprint 漂移。|
|401|`machine_auth_required`|缺少 machine-auth header。|
|401|`machine_auth_invalid`|身份、格式或签名无效。|
|401|`machine_auth_expired`|timestamp 或 credential 过期。|
|401|`machine_auth_revoked`|已持有正确 secret 的请求使用撤销 key。|
|401|`machine_auth_replay`|nonce 已消费。|
|401|`machine_auth_target_mismatch`|已认证 header 与 body 不一致。|
|403|`machine_auth_scope_denied`|正确签名但 scope 不允许 heartbeat。|
|403|`remote_target_disabled`|正确签名对应的 Target 已禁用。|
|413|`request_body_too_large`|heartbeat 原始 body 超限。|
|422|`heartbeat_reported_at_invalid`|Agent reported_at 超出允许偏差。|

所有错误返回统一 `code/message/detail/trace_id`；validation detail 不包含调用方原始
credential、endpoint 或其他输入值。
