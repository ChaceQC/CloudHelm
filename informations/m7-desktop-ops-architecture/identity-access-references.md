# Ops Hub 用户、会话与权限参考

> 检索日期：2026-07-16
> 适用阶段：M7 架构修订、M9 Desktop/RBAC 产品化、M10 安全验收

## 1. NIST RBAC

- 官方资料：
  - https://csrc.nist.gov/projects/role-based-access-control
  - https://csrc.nist.gov/glossary/term/role_based_access_control
- 采用结论：
  - 权限授予到 role，user 通过 role binding 获得权限。
  - 同一 user 可以拥有多个 role；角色和权限保持多对多。
  - CloudHelm 不把权限直接散落在用户名判断或 Desktop 组件中。

## 2. OWASP Authorization

- 官方资料：
  - https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html
- 采用结论：
  - 默认拒绝。
  - 每个请求和具体资源都做权限检查。
  - 使用最小权限。
  - 单纯 RBAC 不足以表达 project/environment/resource ownership，因此采用
    `role + scope + resource attributes + domain separation-of-duty`。
  - Desktop 隐藏/禁用按钮只改善 UX，不能替代 Ops Hub API 授权。

## 3. OAuth 2.0 Security Best Current Practice

- 官方资料：
  - https://www.rfc-editor.org/info/rfc9700/
- 采用结论：
  - Desktop 使用短期 access token。
  - refresh token 轮换，检测旧 token 重用后撤销当前 token family。
  - token 绑定 user、device 和 session；logout、禁用用户和权限重大变化可撤销
    session。
  - token 保存在 OS credential store，不写入 SQLite。

## 4. Password Hashing

- 官方资料：
  - https://www.rfc-editor.org/info/rfc9106/
  - https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html
- 采用结论：
  - 本地账号密码使用成熟库的 Argon2id。
  - 参数按目标 Ops Hub 硬件基准测试，不自研算法或手工拼接 hash。
  - password hash 与可选 pepper 分离；真实密码和 pepper 不写日志。
   - 后续可接 OIDC，但不把外部 IdP 作为毕设 MVP 的必需依赖。

## 5. Ed25519

- 官方资料：
  - https://www.rfc-editor.org/info/rfc8032/
- 采用结论：
  - Desktop 与 Local Runtime 在本机生成 Ed25519 keypair。
  - private key 只进入 OS credential store；Ops Hub 只保存 public key、
    fingerprint 和 credential version。
  - fingerprint 对解码后的 32-byte public key 求 SHA-256；首次 credential
    version 固定为 1，M9 不提供原地 key rotation。
  - login、pairing 和 Local Runtime 短期 device session 使用带版本的 challenge
    canonical bytes + Ed25519 signature，服务端使用成熟密码库验签。
  - 不自研曲线、签名算法、密钥序列化或随机数生成器。

## 6. OAuth 2.0 Device Authorization Grant

- 官方资料：
  - https://www.rfc-editor.org/info/rfc8628/
- 采用结论：
  - 借鉴 user code、短 TTL、轮询/消费边界和设备确认思路。
  - CloudHelm 的 Local Runtime pairing 由已认证 Desktop session 发起并确认，
    不是完整 OAuth authorization server/device grant 实现。
  - one-time code 只保存 hash、单次消费、限制失败次数；配对只建立 device
    identity，后续仍通过签名 challenge 换取短期 device-bound token。

## 7. CloudHelm 取舍

MVP 不实现完整多租户组织系统，先实现单 Ops Hub 实例内的：

```text
User
Role
Permission
RoleBinding(system/project/environment scope)
UserSession
Device
DevicePairingChallenge
```

授权决策输入：

```text
authenticated user
+ active session/device
+ effective permissions
+ scope type/id
+ resource attributes
+ approval/domain separation-of-duty
```

预置 role 只是默认模板，服务端最终按 permission 判断。系统管理员也不能绕过
release/deployment 自批门禁；break-glass 属于增强版并需要独立审计。
