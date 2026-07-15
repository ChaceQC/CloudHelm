# Ops Hub 身份、用户与分层权限细化

> 目的：定义不同用户在 Desktop 中可见、可操作和可审批的能力，并确保最终授权
> 由 Ops Hub 服务端执行。
> 参考资料：
> [Ops Hub 用户、会话与权限参考](../../informations/m7-desktop-ops-architecture/identity-access-references.md)

## 1. 范围

MVP 在单个 Ops Hub 实例内实现：

```text
User
Device
UserSession
Role
Permission
RoleBinding
```

暂不实现：

- 完整多租户 organization/billing。
- 企业目录同步。
- 强制外部 OIDC/SAML。
- break-glass 自动越权。

后续可在不改变 permission key 的前提下扩展 organization/tenant scope 和外部 IdP。

## 2. 授权模型

单纯“用户拥有某个 role”不足以表达项目、环境和资源状态。授权决策固定为：

```text
authenticated user
+ active session/device
+ role-derived permissions
+ scope type/id
+ resource attributes/version
+ approval/domain separation-of-duty
```

原则：

- 默认拒绝。
- 每个请求、每个资源重新校验。
- 最小权限。
- Desktop UI 门禁不是安全边界。
- 角色只是一组 permission 模板，服务端最终按 permission 判断。
- 权限允许某类审批，不代表可以批准自己的实现或自己发起的同一资源。

## 3. Scope

```text
system
project:<project_id>
environment:<environment_id>
```

- system binding 用于 Ops Hub 管理能力；`system_owner` 还获得全局资源读取，但
  资源写入、审批和执行仍按具体 permission、resource 和职责分离校验。
- project binding 适用于项目、任务、设计、代码、CI 和 release candidate。
- environment binding 适用于部署、远端日志、diagnostics 和监控。
- environment 必须属于 role binding 可见的 project。
- 后续 organization scope 只能通过新 schema/version 增加。

## 4. 预置角色

预置 role 是默认模板，可由 System Owner 查看；MVP 不允许删除或改变其安全语义。

### `system_owner`

- 管理用户、角色绑定、Ops Hub 配置、备份/恢复和全局审计。
- 可查看所有 project/environment。
- 不自动绕过 release/deployment 自批门禁。

### `project_developer`

- 读取被授权项目。
- 创建 Task、提交需求、启动/暂停本地开发、查看 diff/test/ToolCall。
- 请求设计审查和 release candidate。
- 不批准自己的设计、release candidate 或 deployment。
- 不管理用户、环境、credential 或远端部署。

### `project_reviewer`

- 读取项目设计、diff、测试、安全报告和 PR/CI 证据。
- 决定 design approval 与 release candidate approval。
- 不能修改项目代码或批准自己产生/发起的资源。

### `environment_operator`

- 读取被授权 Environment/RemoteTarget/Deployment。
- 创建 deployment request，读取受限日志和 diagnostics。
- 执行被批准的运维动作。
- 不决定自己发起的 deployment approval。

### `deployment_approver`

- 查看 ReleasePlan、digest、target、risk 和审计证据。
- 决定 deployment approval。
- 不直接执行 deployment operation。

### `auditor`

- 只读 Project/Task/Approval/ToolCall/Event/Audit/Deployment。
- 读取日志时仍受脱敏、时间窗和 environment scope 限制。
- 不创建、修改、审批或执行动作。

### `viewer`

- 只读项目摘要、任务状态、公开 Artifact 摘要和健康状态。
- 不读取敏感日志、完整 ToolCall 参数、credential metadata 或全局审计。

一个用户可以同时拥有多个 role binding；权限取并集，但 deny/domain guard 优先。

## 4.1 预置角色精确权限与可绑定 Scope

预置模板不得由 Desktop 临时拼接。MVP 固定映射如下：

|角色|Binding Scope|精确 permission 集|
|---|---|---|
|`system_owner`|`system`|`system.read`、`system.settings.manage`、`system.users.manage`、`system.roles.read`、`system.role_bindings.manage`、`system.audit.read`、`system.backup.manage`、`audit.read`、`project.read`、`task.read`、`artifact.read`、`environment.read`、`remote_target.read`、`ci.read`、`remote_status.read`、`monitoring.read`|
|`project_developer`|`project`|`project.read`、`task.read`、`task.create`、`task.run`、`task.pause`、`task.cancel`、`requirement.write`、`design.write`、`workspace.execute`、`artifact.read`、`artifact.sensitive_read`、`release_candidate.request`、`ci.read`|
|`project_reviewer`|`project`|`project.read`、`task.read`、`artifact.read`、`artifact.sensitive_read`、`design.review`、`release_candidate.decide`、`ci.read`|
|`environment_operator`|`environment`|`environment.read`、`remote_target.read`、`deployment.request`、`deployment.execute`、`remote_status.read`、`remote_logs.read`、`remote_diagnostics.request`、`monitoring.read`|
|`deployment_approver`|`environment`|`environment.read`、`remote_target.read`、`deployment.decide`、`remote_status.read`|
|`auditor`|`system`|`system.read`、`system.audit.read`、`audit.read`、`project.read`、`task.read`、`artifact.read`、`environment.read`、`remote_target.read`、`ci.read`、`remote_status.read`、`remote_logs.read`、`monitoring.read`|
|`auditor`|`project`|`audit.read`、`project.read`、`task.read`、`artifact.read`、`ci.read`|
|`auditor`|`environment`|`audit.read`、`environment.read`、`remote_target.read`、`remote_status.read`、`remote_logs.read`、`monitoring.read`|
|`viewer`|`project`|`project.read`、`task.read`、`artifact.read`|
|`viewer`|`environment`|`environment.read`、`remote_status.read`|

Scope 继承规则：

- 预置映射按 `(role_key, binding_scope_type)` 固定；同一个 role 在不同 binding
  scope 下使用不同 permission 集，不能把多种 Scope 的 permission 合并后再由
  客户端猜测。
- system-scope `system_owner` 和 system-scope `auditor` 的读取权限覆盖全部 project/
  environment；写入、审批、执行权限不因全局读取自动获得。
- project scope 覆盖该 Project 及其 Task/Spec/Design/Artifact/CI，并允许读取其
  Environment 摘要；不自动获得 environment operation 权限。
- environment scope 只覆盖该 Environment、RemoteTarget、Deployment、Service、
  log/metric/incident，不自动获得其他环境或项目开发权限。
- Environment/Deployment/Approval 响应可以嵌入父 Project、关联 Task、Artifact、
  CIRun 和 ReleasePlan 的最小脱敏摘要，供运维和部署审批理解上下文；这不形成独立
  `project.read`、`task.read`、`artifact.read` 或 `ci.read` 授权，也不能据此调用
  Project/Task/Artifact/CI 列表或详情 API。
- `deployment.decide` 的资源响应必须包含做出决定所需的不可变 commit、digest、
  测试/安全结论和风险摘要，但不得返回无关 Artifact 正文或其他 Task 数据。
- project/environment-scope 的 `auditor`、`viewer` permission 只在请求资源匹配
  binding scope 时生效；`auditor` 的 `audit.read` 也必须按同一 scope 过滤。
- 同名 permission 在无匹配 scope 时视为未授予。
- 当前 MVP 不提供用户可配置 negative grant；本文中的 deny 指服务端 policy、
  scope 失败或 domain guard 优先于 allow。

## 5. Permission key

### System

```text
system.read
system.settings.manage
system.users.manage
system.roles.read
system.role_bindings.manage
system.audit.read
system.backup.manage
audit.read
```

### Project / development

```text
project.read
project.manage
task.read
task.create
task.run
task.pause
task.cancel
requirement.write
design.write
design.review
workspace.execute
artifact.read
artifact.sensitive_read
release_candidate.request
release_candidate.decide
ci.read
```

### Environment / deployment / ops

```text
environment.read
environment.manage
remote_target.read
remote_target.manage
deployment.request
deployment.decide
deployment.execute
remote_status.read
remote_logs.read
remote_diagnostics.request
remote_diagnostics.decide
monitoring.read
incident.manage
```

permission key 必须进入共享契约、OpenAPI 扩展和测试，不允许在 UI 中临时拼写。

## 6. 数据模型目标

### `users`

```text
id
username
email
display_name
status: invited | active | disabled
password_hash
auth_version
last_login_at
created_at
updated_at
```

- username/email 规范化后唯一。
- password hash 使用成熟 Argon2id 库。
- disabled 用户不能刷新 token；`auth_version` 变化使旧 access token 失效。

### `devices`

```text
id
user_id
device_name
device_public_id
device_type: desktop | local_runtime
credential_public_key
credential_fingerprint
credential_version
status: pending | active | revoked
last_seen_at
created_at
paired_at
paired_by_user_id
paired_by_device_id
revoked_at
```

Desktop 与 Local Runtime 使用不同 device identity。两者都在本机生成 Ed25519
keypair，private key 只进入 OS credential store；服务端只保存 public key、
fingerprint 和 version。Desktop 首次 password login 使用 challenge signature
登记 public id；Local Runtime 通过短期 pairing challenge、用户确认和独立 key
完成绑定。

fingerprint 固定为对解码后的 32-byte Ed25519 public key 求 SHA-256，并编码为
`sha256:<lowercase hex>`；服务端自行计算，不信任请求值。首次登记 version 固定为
1。M9 不支持原地 key rotation；key 丢失/替换使用新的 device public id，后续
rotation API 如引入只能由服务端原子递增 version。

### `device_pairing_challenges`

```text
id
user_id
created_by_device_id
requested_device_public_id
requested_device_type: local_runtime
requested_device_name
credential_public_key
credential_fingerprint
requested_credential_version
one_time_code_hash
status: pending | consumed | expired | rejected
failed_attempt_count
expires_at
consumed_at
created_at
```

- 只有 active Desktop session 可以为同一用户创建 Local Runtime challenge；创建
  challenge 即表示用户在 Desktop 中确认本次配对。
- one-time code 只保存 hash，TTL 最长 5 分钟，单次消费并限制失败次数。
- Local Runtime 必须提交与 challenge 绑定的 public id、credential version 和
  Ed25519 proof；服务端使用 challenge 中冻结的 public key 验签，不匹配、过期、
  重放或已撤销设备均拒绝。
- 配对只建立 device identity。每次本地工具请求仍按“用户 effective permissions
  ∩ Local Runtime allowlist ∩ 当前 project/task/workspace 归属”重新授权。
- Local Runtime 不复用 Desktop refresh token；用户禁用、binding 撤销、Desktop
  发起设备撤销或 Local Runtime 自身撤销都会使其 credential/session 失效。

### `user_sessions`

```text
id
user_id
device_id
session_type: desktop | local_runtime
token_family_id
issued_at
expires_at
last_used_at
revoked_at
revoked_reason
```

- Desktop session 保存 token family、device 和 lifecycle；Local Runtime session
  为短期、device-bound access token，`token_family_id` 为空且不签发 refresh token。

### `session_refresh_tokens`

```text
id
session_id
token_hash
issued_at
used_at
replaced_by_token_id
revoked_at
reuse_detected_at
```

- 只保存 refresh token hash。
- refresh token 每次使用后标记 `used_at` 并创建 replacement。
- 已使用 token 再次出现时记录 `reuse_detected_at`，撤销整个 family。

### `user_invitations`

```text
id
email
username_hint
token_hash
invited_by_user_id
expires_at
accepted_at
revoked_at
created_at
```

邀请 token 只保存 hash、单次消费，不进入 EventLog 或普通日志。

### `roles`

```text
id
key
display_name
description
built_in
created_at
```

### `permissions`

```text
id
key
description
risk_class
```

### `role_permissions`

```text
role_id
permission_id
```

### `role_bindings`

```text
id
user_id
role_id
scope_type: system | project | environment
project_id
environment_id
status: active | revoked | expired
granted_by_user_id
expires_at
created_at
revoked_at
revoked_by_user_id
revoked_reason
```

约束：

- API 继续使用统一 `scope_id`，service 按 `scope_type` 物化为真实 FK：
  - system：`project_id/environment_id` 均为空。
  - project：`project_id` 必填，`environment_id` 为空。
  - environment：`project_id/environment_id` 均必填。
- `environments(id, project_id)` 建唯一键，role binding 以复合 FK 保证 Environment
  确实属于同一 Project，不使用无法建立外键的 polymorphic `scope_id`。
- status 使用 `active | revoked | expired`。
- system/project/environment 分别建立 active partial unique index，保证同一
  user/role/scope 只允许一个 active 且未过期 binding。
- environment scope 必须引用真实 Environment。
- binding 过期由 worker 原子转为 `expired`，不继续占用 active 唯一约束。
- binding 过期/撤销后立即从 effective permissions 排除。

### `system_security_state`

```text
singleton_key
permission_version
bootstrap_completed_at
updated_at
```

- role、permission、binding、user status 或安全语义变化时在同一事务增加
  `permission_version`。
- bootstrap token 单次消费后记录完成状态；后续调用稳定返回冲突。
- 任何事务都不得让系统失去最后一个 active、未过期且用户 active 的
  system-scope `system_owner`。

### 现有表身份修订

后续 migration 应把关键 actor 从自由字符串升级为用户引用：

```text
approval_requests.requested_by_user_id
approval_requests.decided_by_user_id
tasks.created_by_user_id
agent_runs.initiated_by_user_id
technical_designs.last_modified_by_user_id
technical_designs.last_modified_by_agent_run_id
technical_designs.last_modified_source
technical_designs.content_sha256
event_logs.actor_user_id
tool_calls.requested_by_user_id
release_candidates.requested_by_user_id
ci_runs.requested_by_user_id
deployments.requested_by_user_id
```

保留 `actor_type/actor_id` 安全投影用于兼容历史和 machine/system actor，但用户
操作的真实身份必须来自认证上下文。ReleaseCandidate、ReleasePlan/Deployment
和 AgentRun 必须保存人类发起者 provenance；职责分离比较认证 user 与这些服务端
引用，不用 legacy actor string 或 AgentRun UUID 代替用户授权身份。

`technical_designs.version` 已是当前版本字段。M9 增加上述修改者与内容 hash 后，
每次人类修改从认证上下文写 `last_modified_by_user_id`；Agent 生成或重写时写
`last_modified_by_agent_run_id`，并通过 `agent_runs.initiated_by_user_id` 解析该
版本的人类发起者。Design approval 必须绑定当前 `technical_design_id + version +
content_sha256`，reviewer 与当前版本最后修改者/AgentRun 发起者相同则拒绝。

`last_modified_source` 固定为 `user | agent_run | legacy_system`：

- `user` 要求 user 非空、AgentRun 为空。
- `agent_run` 要求 AgentRun 非空、user 为空。
- `legacy_system` 只允许 migration 回填的历史记录，两者均为空；M9 API 不得创建。

内容 hash 使用项目统一 `stable_json_hash`：

```text
content_sha256 = stable_json_hash({
  "schema": "technical-design-content.v1",
  "design_type": design_type,
  "content_markdown": content_markdown,
  "openapi_json": openapi_json,
  "db_schema_json": db_schema_json,
  "mermaid_diagram": mermaid_diagram,
  "risk_level": risk_level,
  "version": version
})
```

所有 null 和原始 Markdown 字符串都进入 canonical JSON；写入后不得在 hash 之外
再次做换行或空白归一化。

## 7. 认证流程

### 首次 bootstrap

1. Ops Hub 安装器生成一次性 bootstrap token。
2. 首个 Desktop 通过 HTTPS 使用 token 创建 `system_owner`。
3. token 单次消费并立即失效。
4. 创建 user、device 和 session，写完整审计。

### Login

```text
POST /api/auth/login-challenges
  -> generic short-lived nonce without account/device enumeration
POST /api/auth/login
  -> user/password/device_public_id/device_type/public key/device proof
  -> short-lived access token
  -> rotated refresh token
  -> session/device/effective system permissions summary
```

新 Desktop public id 首次登记时，服务端使用请求 public key 验证 challenge
signature；已有 active device 必须使用服务端已登记 public key 和匹配 credential
version 验签。private key 从不上传或由服务端返回。revoked public id 不允许原地
恢复，重新登记必须生成新的 public id/keypair。

### Local Runtime pairing

```text
Authenticated Desktop
  -> POST /api/auth/devices/pairing-challenges
  -> challenge id + one-time code + expiry
Local Runtime
  -> POST /api/auth/devices/pair
  -> public id + code + credential proof
  -> active device identity
```

创建 challenge 即为当前 Desktop session 的用户确认；服务端绑定 user、发起
Desktop device、请求 public id/public key/fingerprint/version 和 TTL。配对后只
获得 device identity，实际工具任务继续按用户 permission、Local Runtime
allowlist 和当前 project/task/workspace 归属求交集。

配对成功后，Local Runtime 通过
`POST /api/auth/device-session-challenges` 与
`POST /api/auth/device-sessions` 对短期 nonce 签名，获得最多 10 分钟的
device-bound access token；不签发 refresh token。每次换取和每个受保护请求都重验
user/device/session、binding 与 workspace 归属。

### Invitation accept

```text
POST /api/auth/invitations/accept
  -> verify token hash / expiry / unused
  -> set username/password
  -> activate user
  -> consume invitation once
```

### Refresh

- 验证 refresh token hash、family、device、expiry、user status 和 auth_version。
- 原 token 标记已用并产生新 token。
- 检测重用时撤销整个 family。

### Logout / revoke

- 当前 session logout。
- 用户可撤销自己的设备/session。
- `system.users.manage` 可禁用用户或撤销全部 session。

## 8. Desktop 权限体验

Desktop 登录后读取：

```text
GET /api/auth/me
GET /api/me/effective-permissions?project_id=&environment_id=
GET /api/me/security-snapshot
GET /api/me/events/stream
```

UI 行为：

- 页面路由、按钮、快捷键和批量操作按 effective permissions 隐藏或禁用。
- 禁用状态说明缺少的 permission 和 scope，不把内部策略细节暴露给无权用户。
- 服务器返回 401 时刷新 session；返回 403 时刷新 effective permissions。
- role binding 变化通过 EventLog/SSE 通知，Desktop 清理相关缓存并重新求值。
- SQLite cache 按 `ops_hub_id + user_id` 分区；logout 删除该用户的敏感 read model
  和草稿索引，token 由 credential store 删除。

即使 UI 显示按钮，Ops Hub 仍重新校验；即使 UI 隐藏按钮，用户也不能通过直接
HTTP 请求绕过授权。

### 8.1 Desktop route/action 映射

|页面/动作|permission|Scope|还需服务端 capability|
|---|---|---|---|
|项目/任务只读|`project.read`、`task.read`|system/project|资源可见|
|创建任务|`task.create`|project|Project active|
|启动/暂停/取消任务|`task.run`、`task.pause`、`task.cancel`|project|当前状态允许|
|查看完整 diff/安全证据|`artifact.sensitive_read`|project|Artifact 非受限或已脱敏|
|决定设计审批|`design.review`|project|`can_decide_current_approval`|
|请求 release candidate|`release_candidate.request`|project|当前 PR/commit 可发布|
|决定 release candidate|`release_candidate.decide`|project|非实现/请求 owner|
|查看 Environment 中的父项目/关联任务摘要|`environment.read`|environment|只返回当前 Environment/Deployment 直接关联的最小脱敏摘要，不开放 Project/Task route|
|请求部署|`deployment.request`|environment|ReleasePlan/target fresh|
|决定部署|`deployment.decide`|environment|非 requester|
|执行部署|`deployment.execute`|environment|Approval 已消费且资源版本匹配|
|查看受限日志|`remote_logs.read`|environment|时间窗/服务范围允许|
|管理用户/绑定|`system.users.manage`、`system.role_bindings.manage`|system|不能移除最后 owner|

Approval、ReleaseCandidate、Deployment 等资源响应统一返回服务端计算的
`allowed_actions`/`capabilities`。Desktop 不根据 role 名猜测自批、状态或资源
版本门禁。

## 9. Approval 职责分离

必须同时满足 permission 和领域门禁：

|审批|所需 permission|额外门禁|
|---|---|---|
|Design|`design.review`|审批绑定当前 design version/content hash；不能批准自己直接修改或由自己发起 AgentRun 生成/重写的当前版本|
|Release candidate|`release_candidate.decide`|不能是对应 PR/Coder Agent 实现者或 request owner|
|Deployment|`deployment.decide`|不能是 ReleasePlan requester；与 execute 权限分离|
|Remote diagnostics|`remote_diagnostics.decide`|不能是同一请求发起人|

`system_owner` 也必须满足以上门禁。MVP 不提供单人 break-glass。

## 10. API 响应与错误

统一错误：

```text
authentication_required       401
session_expired               401
session_revoked               401
device_revoked                401
device_proof_invalid          401
device_pairing_expired        409
device_pairing_replayed       409
device_pairing_proof_invalid  401
device_session_challenge_invalid 409
device_session_proof_invalid  401
permission_denied             403
scope_access_denied           403
self_approval_forbidden       403
role_binding_not_found        404
role_binding_conflict         409
bootstrap_already_completed   409
refresh_token_reuse_detected  401
```

403 detail 不返回其他项目、环境、用户或 credential 的存在信息。

## 11. Event 与审计

计划事件：

```text
UserInvited
UserActivated
UserDisabled
DevicePairingRequested
DevicePairingExpired
DevicePairingRejected
DevicePaired
DeviceRevoked
DeviceSessionCreated
DeviceSessionRejected
SessionRevoked
RoleBindingGranted
RoleBindingRevoked
RoleBindingExpired
PermissionDenied
```

EventLog 后续增加单调 `sequence`、`stream_kind`、project/aggregate
identity/version、schema version、user/device/session actor 引用和
`subject_user_id`。`actor_user_id` 表示执行者，`subject_user_id` 表示用户控制流
受众；两者不能混用。SSE `id` 使用 sequence，权限过滤造成的 sequence 空洞正常。
RoleBinding 撤销/过期时，被影响用户必须收到 `stream_kind=user_control` 且
`subject_user_id` 为自己的最小 self/control event，以刷新 effective permissions
并清理 Desktop 缓存；`/api/me/events*` 只按认证 user 匹配 subject，不从 payload
推断受众，也不依赖用户当前是否订阅某个 Project。

审计至少包含：

```text
authenticated_user_id
device_id
session_id
permission
scope_type
scope_id
resource_type
resource_id
decision
reason_code
trace_id
created_at
```

不记录密码、access token、refresh token、device private key、challenge nonce/
proof、完整 Authorization header 或 secret。

## 12. 验收矩阵

|编号|测试|通过标准|
|---|---|---|
|IAM-01|首次 bootstrap|只能创建一次 owner，bootstrap token 失效|
|IAM-02|登录/刷新/退出|短 access token、refresh rotation、logout 撤销有效|
|IAM-03|refresh 重用|token family 全部撤销并写审计|
|IAM-04|禁用用户|旧 session 和新请求均被拒绝|
|IAM-05|默认拒绝|无 binding 用户不能读取项目|
|IAM-06|project scope|用户只能访问绑定项目|
|IAM-07|environment scope|operator 只能操作绑定环境|
|IAM-08|UI 门禁|不同角色 Desktop 页面和按钮正确变化|
|IAM-09|API 强制|直接构造 HTTP 请求仍返回 403|
|IAM-10|职责分离|有 permission 的 requester 仍不能自批|
|IAM-11|binding 变更|SSE 后 Desktop 更新权限并清理无权缓存|
|IAM-12|审计|allow/deny/role/session 事件可追溯且无 token|
|IAM-13|Scope 矩阵|environment binding 不能独立读取父 Project/Task/Artifact/CI，只能读取直接关联的脱敏摘要|
|IAM-14|Desktop 首次登记|新/已有 public id 均用 Ed25519 challenge proof，服务端只存 public key；revoked public id 不原地恢复|
|IAM-15|Local Runtime 配对与 session|challenge 过期、重放、错误 proof 和失败次数超限均拒绝；短期 device session 无 refresh token，撤销后本地调用失效|
|IAM-16|用户控制流|管理员撤权时 actor 与 subject 分离，受影响用户从 snapshot watermark 后完整补齐|

## 13. 版本影响

- 用户、会话、role binding、EventLog actor 和 Approval actor 会新增 PostgreSQL
  migration。
- OpenAPI 增加 auth/user/role-binding/effective-permission API。
- Desktop 增加登录、用户管理、权限管理、无权/只读状态和缓存分区。
- Tool Gateway、Orchestrator、Approval、Deploy、Monitoring API 都要接入认证
  context，不接受调用方自报 actor。
- 完成这些兼容新增能力后再评估 `0.8.0`（M9）版本；本轮文档仍保持 `0.5.1`。

## 14. 当前未实现边界

截至 2026-07-16：

- Platform API 没有真实用户登录或 role binding。
- `actor_id` 仍存在调用方字符串语义。
- Desktop 没有登录、OS credential store 或 effective permission UI。
- API 主要按本地开发来源/CORS 运行。

因此当前任何用户/RBAC 能力都只能标记为规划。
