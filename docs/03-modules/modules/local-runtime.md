# modules/local-runtime

> 层级：`modules/local-runtime`
> 状态：目标模块，尚未创建生产代码。

## 职责

`local-runtime` 是随 CloudHelm Desktop 安装包分发的跨平台 sidecar，负责本机
源码开发能力：

- workspace allowlist 与项目选择。
- Git repository、worktree、branch、diff、commit。
- 受控依赖检查、测试、安全扫描和 Artifact 收集。
- 与 Ops Hub 交换已认证、可审计、带幂等键的本地工具任务。
- Desktop 退出或网络断开时安全暂停本地步骤，并在重连后依据服务端状态恢复。

## 不负责

- 不保存 Task、Approval、WorkflowJob 或 Deployment 的权威状态。
- 不直接连接 PostgreSQL、Redis 或 Remote Agent。
- 不执行远端部署、监控采集、自由 shell 或任意宿主路径访问。
- 不把本地 SQLite 当作服务端数据库副本。

## 技术与发行形态

- 后续实现为 Windows/Linux 原生可执行文件。
- 通过 Tauri sidecar 随 Desktop 安装器分发。
- 本机状态只保存 workspace registry、短期任务恢复证据和非敏感缓存。
- Ed25519 device private key 使用 OS credential store；本地日志和 SQLite 不保存
  private key 或 token。
- 文件、Git 和命令执行继续复用 Tool Gateway 的 schema、risk、allowlist 和审计
  规则，并在 sidecar 侧执行第二道参数门禁。

## 通信契约

```text
Ops Hub
  -> signed local tool assignment
  -> local-runtime claim
  -> bounded execution
  -> structured result / artifact digest
  -> Ops Hub PostgreSQL commit
```

- Local Runtime 只建立出站 HTTPS 连接。
- 首次连接由 active Desktop session 创建短期、单次消费的 pairing challenge；
  Local Runtime 使用独立 public id、credential fingerprint/version 和 proof 完成
  配对。private key 只保存到 OS credential store；配对后通过签名 challenge 换取
  最多 10 分钟的 device-bound access token，不签发 refresh token。
- Local Runtime 不复用 Desktop refresh token；每次任务的有效权限是“当前用户
  effective permissions ∩ Local Runtime allowlist ∩ project/task/workspace 归属”。
- 用户禁用、role binding 撤销、Desktop/Local Runtime device revoke 或 credential
  version 变化后，旧 session/assignment 立即失效并重新鉴权。
- M9 不提供原地 device key rotation；private key 丢失时使用新的 public id/keypair
  重新配对，后续 rotation version 只能由服务端递增。
- 每条任务绑定 `task_id + tool_call_id + workspace_id + idempotency_key`。
- Desktop 关闭时已被服务端接受的远端工作流继续运行；本地 workspace 步骤可保持
  paused，不由 Ops Hub 在其他主机盲目重放。

## 与 Remote Agent 的区别

|模块|运行位置|对象|主要能力|
|---|---|---|---|
|Local Runtime|开发者 Windows/Linux 桌面主机|本地源码/workspace|Git、测试、代码工具|
|Remote Agent|受管 Linux 环境|已部署业务项目|部署 operation、状态、受限日志、diagnostics|

## 测试关注点

- Windows/Linux sidecar 打包和签名。
- workspace 越界、symlink、敏感文件和命令门禁。
- Desktop/网络中断后的暂停、重复领取和幂等恢复。
- pairing challenge 过期、重放、错误 proof、失败次数超限和撤销级联。
- project/task/workspace 越权与用户权限变更后的 assignment 拒绝。
- 本机执行结果与 Ops Hub ToolCall/EventLog 的一致性。
- 卸载 Desktop 后不删除用户业务仓库；清理 sidecar cache 不影响服务端审计。
