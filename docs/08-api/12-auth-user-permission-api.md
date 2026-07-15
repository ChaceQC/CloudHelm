# Auth、User 与 Permission API

> 状态：规划。当前 `0.5.1` 尚未实现真实用户认证和 RBAC。
> 细化设计：
> [Ops Hub 身份、用户与分层权限细化](../15-detailed-design/11-identity-access-control.md)

## 1. Authentication

```text
POST /api/auth/bootstrap
POST /api/auth/login-challenges
POST /api/auth/login
POST /api/auth/refresh
POST /api/auth/logout
GET  /api/auth/me
GET  /api/auth/sessions
DELETE /api/auth/sessions/{session_id}
GET  /api/auth/devices
POST /api/auth/devices/pairing-challenges
POST /api/auth/devices/pair
POST /api/auth/device-session-challenges
POST /api/auth/device-sessions
POST /api/auth/devices/{device_id}/revoke
```

### Bootstrap

- 只允许 Ops Hub 尚无用户时调用。
- 使用安装器生成的一次性 bootstrap token。
- 创建首个 `system_owner`、Desktop device 和 session。
- 第二次返回 `409 bootstrap_already_completed`。

### Login

Desktop 先获取短期 login challenge：

```http
POST /api/auth/login-challenges
Content-Type: application/json
```

```json
{
  "username": "admin",
  "device_public_id": "desktop-7f0c9c34"
}
```

响应无论账号/device 是否存在都使用相同外形，避免枚举：

```json
{
  "challenge_id": "uuid",
  "nonce": "base64url-random",
  "expires_at": "2026-07-16T12:05:00Z"
}
```

challenge TTL 最长 5 分钟、单次消费并限速。它可以保存在 Redis 的短期原子消费
key 中；Redis 丢失只使登录重试，不能放行请求，审计仍由 PostgreSQL 记录。随后
提交登录请求：

```json
{
  "username": "admin",
  "password": "secret-from-user-input",
  "challenge_id": "uuid",
  "device": {
    "device_public_id": "desktop-7f0c9c34",
    "device_name": "Windows Desktop",
    "device_type": "desktop",
    "credential_public_key": "base64url-ed25519-public-key",
    "credential_fingerprint": "sha256:...",
    "credential_version": 1,
    "proof": "base64url-ed25519-signature"
  }
}
```

- `device_type` 在 password login 中只允许 `desktop`；Local Runtime 必须走配对流。
- Desktop 首次登录前在本机生成 Ed25519 keypair，private key 只进入 OS credential
  store；新 public id 提交 public key/fingerprint/version 和有效 challenge 签名，
  服务端验签后创建 active Desktop device。
- 已登记 active device 必须提交与服务端已存 public key/fingerprint/version 完全
  匹配的元数据和 challenge 签名；不能借登录请求替换 key。
- `credential_fingerprint = "sha256:" +
  lowercase_hex(SHA256(raw_32_byte_ed25519_public_key))`。服务端解码 public key 后
  自行计算并比较 fingerprint，不信任调用方计算结果。
- 新 device 的 `credential_version` 固定为 1。M9 不提供原地 key rotation；private
  key 丢失或需要替换时生成新的 `device_public_id`/keypair 重新登记。后续若新增
  rotation API，version 只能由服务端在原子事务中递增。
- revoked public id 返回 `device_revoked`，不能原地恢复；重新登记必须生成新的
  public id。
- 响应返回短期 access token、refresh token、session/device 摘要和权限版本；新旧
  device 使用同一响应外形，只由 `device.registered_now` 表示是否首次登记。
- 密码、challenge nonce、private key、proof 和 token 不进入 URL、日志、EventLog
  或普通 Artifact。服务端只保存 public key/fingerprint/version。

Desktop proof 固定为 versioned Ed25519 signature：

```text
canonical =
  "cloudhelm-device-login-v1\n"
  + challenge_id + "\n"
  + nonce + "\n"
  + device_public_id + "\n"
  + device_type + "\n"
  + credential_fingerprint + "\n"
  + credential_version

proof = base64url(Ed25519-Sign(device_private_key, UTF8(canonical)))
```

canonical 无末尾换行，字符串字段使用 API 已校验的原始值。
服务端使用成熟 Ed25519 库验签；新 device 使用请求 public key，已有 device 使用
数据库中已登记 public key。任何字段、key、fingerprint 或版本不匹配均返回统一
`device_proof_invalid`，不泄露账号/device 是否存在。

### Local Runtime pairing

已登录 Desktop 用户为同一用户的 Local Runtime 发起 challenge：

```http
POST /api/auth/devices/pairing-challenges
Authorization: Bearer <access-token>
Content-Type: application/json
```

```json
{
  "device_public_id": "local-runtime-3c91f08d",
  "device_name": "Workstation Local Runtime",
  "device_type": "local_runtime",
  "credential_public_key": "base64url-ed25519-public-key",
  "credential_fingerprint": "sha256:...",
  "credential_version": 1
}
```

成功响应：

```json
{
  "challenge_id": "uuid",
  "one_time_code": "Q7M4-P2KD",
  "expires_at": "2026-07-16T12:05:00Z"
}
```

创建 challenge 即表示当前 Desktop session 对本次 public id 明确确认。服务端保存
one-time code hash、user、发起 Desktop device、请求 public id/public key/
fingerprint/version、TTL 和失败次数，不保存明文 code。
fingerprint 仍由服务端对 raw public key 计算，首次 version 必须为 1。

Local Runtime 完成配对：

```http
POST /api/auth/devices/pair
Content-Type: application/json
```

```json
{
  "challenge_id": "uuid",
  "one_time_code": "Q7M4-P2KD",
  "device_public_id": "local-runtime-3c91f08d",
  "credential_version": 1,
  "proof": "base64url-ed25519-signature"
}
```

Local Runtime 在本机生成 Ed25519 keypair，私钥只进入 OS credential store。
`proof` 是对以下 canonical UTF-8 bytes 的 Ed25519 签名：

```text
cloudhelm-local-runtime-pair-v1
<challenge_id>
<one_time_code>
<device_public_id>
<credential_version>
```

canonical 各行使用 `\n`，无末尾换行。
服务端使用 challenge 中固定的 public key/version 验签，不能接受 pair 请求临时
替换 public key/fingerprint/version。

成功响应：

```json
{
  "device": {
    "id": "uuid",
    "device_type": "local_runtime",
    "status": "active",
    "credential_version": 1
  },
  "granted_scope": "device_identity_only"
}
```

- challenge TTL 最长 5 分钟、单次消费、限制失败次数；过期、重放、public id/
  fingerprint/proof 不匹配均拒绝并写审计。
- 创建、过期、拒绝、成功分别写 `DevicePairingRequested`、
  `DevicePairingExpired`、`DevicePairingRejected`、`DevicePaired`；EventLog
  不包含明文 code、proof 或 private key。
- Local Runtime private key 只进入 OS credential store，不复用 Desktop refresh
  token，也不继承固定全局权限。
- 每次本地工具请求使用“用户 effective permissions ∩ Local Runtime allowlist ∩
  当前 project/task/workspace 归属”授权。
- 用户禁用、binding 变化、Desktop 主动撤销或 Local Runtime device revoke 会使
  相关 session/credential 失效。

### Local Runtime device session

配对只建立 device identity。Local Runtime 每次建立短期 API session 时先请求
challenge：

```text
POST /api/auth/device-session-challenges
POST /api/auth/device-sessions
```

challenge 响应使用与 login challenge 相同的 generic 外形和 Redis 单次消费/TTL
边界，不泄露 device 是否存在：

```json
{
  "device_public_id": "local-runtime-3c91f08d"
}
```

```json
{
  "challenge_id": "uuid",
  "nonce": "base64url-random",
  "expires_at": "2026-07-16T12:05:00Z"
}
```

服务端 challenge 冻结 `device_id + device_public_id + credential_version`；session
请求不能覆盖这些值。

随后 Local Runtime 提交：

```json
{
  "challenge_id": "uuid",
  "device_public_id": "local-runtime-3c91f08d",
  "credential_version": 1,
  "proof": "base64url-ed25519-signature"
}
```

proof canonical：

```text
cloudhelm-local-runtime-session-v1
<challenge_id>
<nonce>
<device_public_id>
<credential_version>
```

canonical 各行使用 `\n`，无末尾换行。服务端使用已登记 public key 验签，创建
`session_type=local_runtime` 的短期 session，并返回最多 10 分钟的 device-bound
access token；不签发用户 refresh token。过期后重新执行 challenge/signature，
每个受保护请求仍重新校验 user/device/session、binding 和 workspace 归属。

```json
{
  "session_id": "uuid",
  "device_id": "uuid",
  "access_token": "short-lived-device-token",
  "token_type": "Bearer",
  "expires_in": 600,
  "expires_at": "2026-07-16T12:10:00Z",
  "session_type": "local_runtime"
}
```

成功和拒绝分别写 `DeviceSessionCreated`、`DeviceSessionRejected`；nonce、proof
和 access token 不写入 EventLog。
challenge 不存在、已消费、重放或过期统一返回
`device_session_challenge_invalid`，避免泄露 device 状态；public key、proof 或
credential version 不匹配统一返回 `device_session_proof_invalid`。

### Refresh

- refresh token 轮换。
- 检测旧 token 重用后返回 `refresh_token_reuse_detected` 并撤销 token family。
- disabled user、revoked device、expired/revoked session 均拒绝。

## 2. User Management

```text
GET   /api/users
POST  /api/users/invitations
POST  /api/auth/invitations/accept
GET   /api/users/{user_id}
PATCH /api/users/{user_id}
POST  /api/users/{user_id}/disable
POST  /api/users/{user_id}/enable
POST  /api/users/{user_id}/sessions/revoke
```

权限：

```text
system.users.manage
```

系统必须始终至少保留一个 active、未过期、用户未禁用的 system-scope
`system_owner` binding；任何用户禁用、binding 撤销/过期或角色变更都不能破坏
该不变量。禁用用户必须撤销全部 session 并写审计事件。

邀请接受请求把 token 放在 JSON body，不进入 URL、access log、EventLog 或普通
trace attribute。

## 3. Role 与 Binding

```text
GET    /api/roles
GET    /api/permissions
GET    /api/role-bindings
POST   /api/role-bindings
POST   /api/role-bindings/{binding_id}/revoke
```

创建 binding：

```json
{
  "user_id": "uuid",
  "role_key": "project_developer",
  "scope_type": "project",
  "scope_id": "uuid",
  "expires_at": null
}
```

约束：

- system scope 的 `scope_id` 必须为空。
- project/environment scope 的资源必须存在。
- API `scope_id` 由 service 物化为数据库 `project_id/environment_id` 与真实
  外键，不保存 polymorphic foreign key。
- environment 必须属于调用者可管理的 project。
- 同一 user/role/scope active binding 幂等返回原记录。
- revoke 为软撤销，保存 `revoked_by_user_id/revoked_at/reason`；过期 worker
  原子把 binding 转为 `expired` 并写事件。
- system-scope `system_owner` 除管理能力外拥有全局资源读取；写入、审批和执行仍
  按具体 permission、resource version 与职责分离判断。

## 4. Effective Permission

```text
GET /api/me/effective-permissions
GET /api/me/effective-permissions?project_id=<uuid>
GET /api/me/effective-permissions?environment_id=<uuid>
```

响应：

```json
{
  "user_id": "uuid",
  "auth_version": 4,
  "permission_version": 19,
  "scope": {
    "type": "project",
    "id": "uuid"
  },
  "permissions": [
    "project.read",
    "task.create",
    "task.run"
  ]
}
```

响应还应包含服务端权限快照版本和资源能力：

```json
{
  "auth_version": 4,
  "permission_version": 19,
  "capabilities": {
    "can_create_task": true,
    "can_decide_current_approval": false,
    "cannot_decide_reason": "self_approval_forbidden"
  }
}
```

Desktop 可以据此渲染 UI，但服务端资源 API 仍独立鉴权。Approval、
ReleaseCandidate、ReleasePlan/Deployment 等详情响应应返回服务端计算的
`allowed_actions` 或 `capabilities`，避免 UI 只靠静态 permission key 猜测
资源级自批门禁。

## 5. Resource API 统一变化

所有写 API 后续统一：

- 从 access token 派生 `user_id/device_id/session_id`。
- 不接受调用方自报 actor 作为授权身份。
- 支持 `Idempotency-Key`。
- 状态敏感操作支持 `If-Match` 或 `expected_resource_version`。
- 403 使用 `permission_denied` 或 `scope_access_denied`，不泄露无权资源细节。

审批请求体后续只提交 reason/decision；`decided_by_user_id` 由认证上下文写入。

## 6. Desktop 缓存与权限变化

Desktop 登录后始终维护独立于 project subscription 的用户控制流：

```text
GET /api/me/security-snapshot
GET /api/me/events?after_sequence=<n>
GET /api/me/events/stream
```

控制流只返回当前用户的最小 User/Device/Session/RoleBinding/permission-version
事件。用户禁用、device/session revoke、system-scope binding 变化或当前没有打开
任何 Project 时，仍可通过该通道刷新安全状态。

`GET /api/me/security-snapshot` 至少返回：

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

Desktop 从 `as_of_sequence` 继续读取 `stream_kind=user_control` 且
`subject_user_id` 为当前用户的事件，再打开 SSE，关闭 snapshot 与 live stream
之间的竞态窗口。

role binding 变化后：

1. Ops Hub 在权威 security state 行中原子增加 `permission_version`。
2. 写 `RoleBindingGranted/Revoked/Expired` EventLog。
3. Desktop 收到事件后重新调用 effective-permissions。
4. 清除已失去 scope 的 cached read models。
5. 正在显示的页面切换为无权状态，不保留敏感正文。

## 7. 错误码

```text
authentication_required
invalid_credentials
session_expired
session_revoked
device_revoked
device_proof_invalid
device_pairing_not_found
device_pairing_expired
device_pairing_replayed
device_pairing_proof_invalid
device_session_challenge_invalid
device_session_proof_invalid
permission_denied
scope_access_denied
self_approval_forbidden
bootstrap_already_completed
role_binding_not_found
role_binding_conflict
refresh_token_reuse_detected
event_cursor_reset_required
```

## 8. 验收

- 无 token 访问受保护 API 返回 401。
- Viewer 不能创建 Task。
- Developer 只能操作绑定 project。
- Operator 只能查看绑定 environment 日志。
- Environment 角色只能通过 Environment/Deployment 响应读取父 Project、关联
  Task/Artifact/CI 的最小脱敏摘要，不能调用对应独立详情 API。
- Reviewer 有 permission 但仍不能自批。
- 禁用用户后旧 access/refresh token 均失效。
- Desktop 修改 UI 请求不能绕过 API 403。
- 邀请 token 只保存 hash、单次消费且过期后拒绝。
- refresh token 轮换历史能够检测已替换旧 token 重用并撤销 token family。
- 撤销/过期最后一个 active system owner 的请求被拒绝。
- 新/已有 Desktop 都使用 Ed25519 challenge proof；服务端只保存 public key，
  revoked public id、key 替换和 credential version 漂移均有稳定结果。
- Local Runtime pairing 覆盖 TTL、单次消费、错误 proof、重放、失败次数限制和
  user/device/binding revoke 级联。
- Local Runtime 短期 device session 不签发 refresh token，token 过期、device
  revoke 或 binding/workspace 变化后必须重新签名并重新授权。
