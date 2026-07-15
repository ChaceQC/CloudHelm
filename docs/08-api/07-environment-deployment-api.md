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

以下端点仍是后续 M7 契约，不属于 M7-1：

```text
POST /api/remote-targets/{target_id}/test-connection
GET  /api/tasks/{task_id}/release-candidate
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

## 6. 事件与查询边界

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

## 7. 稳定错误码

|HTTP|错误码|含义|
|---:|---|---|
|404|`project_not_found`|Project 不存在。|
|404|`environment_not_found`|Environment 不存在。|
|409|`environment_name_conflict`|项目内 Environment 名称重复。|
|409|`environment_not_active`|Environment 不允许注册目标。|
|409|`remote_target_conflict`|同一 Environment 已登记该 Agent。|
|422|`remote_target_profile_not_found`|profile key 不存在。|
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
