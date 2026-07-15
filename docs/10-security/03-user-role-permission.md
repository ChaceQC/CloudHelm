# Ops Hub 用户、角色与权限

> 细化契约：
> [Ops Hub 身份、用户与分层权限细化](../15-detailed-design/11-identity-access-control.md)

## 核心结论

- 用户、session、role binding 和权限由常在线 Ops Hub 统一管理。
- Desktop 根据服务端 effective permissions 展示功能，但 UI 门禁不是安全边界。
- API 每次按 user、device、scope、resource 和 domain guard 重新授权。
- 默认拒绝、最小权限、职责分离。
- 用户凭据与 Remote Agent machine credential 完全隔离。

## MVP 作用域

```text
system
project:<project_id>
environment:<environment_id>
```

## 预置角色

|角色|主要能力|
|---|---|
|system_owner|用户、角色绑定、配置、备份和全局审计|
|project_developer|任务、需求、本地开发、diff/test、请求 release|
|project_reviewer|设计和 release candidate 审查/审批|
|environment_operator|环境、部署请求、受限日志和 diagnostics|
|deployment_approver|独立决定 deployment approval|
|auditor|审计、审批、部署和日志只读|
|viewer|项目/任务/健康摘要只读|

角色可组合，permission 取并集；当前没有用户自定义 negative grant，文中的 deny
表示服务端 scope/resource policy 与自批门禁优先。

精确映射按 `(role_key, binding_scope_type)` 定义。Environment binding 不授予独立
Project/Task/Artifact/CI 读取；Environment、Deployment 或 Approval 响应只嵌入
当前资源直接关联的父 Project、Task、commit/digest 和 CI/安全结论最小摘要。
project/environment-scope 的 `auditor`、`viewer` 也只能读取与 binding scope
匹配的资源，不能因角色名获得全局读取。

## Desktop 功能门禁

Desktop 必须支持：

- 登录、退出、session/device 管理。
- 用户列表、邀请、启用/禁用。
- role binding 的 system/project/environment scope 管理。
- 根据权限隐藏/禁用页面、按钮、快捷键和批量动作。
- 403 后刷新权限；role binding 事件后清理无权缓存。
- SQLite cache 按 Ops Hub + user 分区。

## 不可绕过规则

- 有 `release_candidate.decide` 也不能批准自己的实现。
- 有 `deployment.decide` 也不能批准自己发起的 ReleasePlan。
- `system_owner` 不自动绕过职责分离。
- 请求体中的 `actor_id` 不作为用户身份；服务端从认证上下文写入 user/device。
- 高风险离线 intent 不自动重放。

## 当前状态

当前 Platform API 与 Desktop 尚未实现真实用户认证或 RBAC。本文件是后续
PostgreSQL migration、Auth API、PermissionService、Desktop UI 和测试的规划依据。
预置角色精确 permission 集、允许 Scope 和 Desktop route/action 映射见
[Ops Hub 身份、用户与分层权限细化](../15-detailed-design/11-identity-access-control.md)。
