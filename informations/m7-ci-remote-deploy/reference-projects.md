# M7 CI/CD 与远端部署参考项目实践

检索日期：2026-07-14；复核日期：2026-07-15

适用阶段：M7 Release / Deploy Agent、远端动作审批、持久化执行记录、失败恢复、
Remote Agent 心跳、受限远端诊断与审计

版本与许可证边界：本文件只借鉴公开架构和工程实践，不复制实现代码。进入具体
代码借鉴前，必须再次固定参考项目 release/commit 并核验当时许可证；本轮仅使用
Rundeck、Windmill、Kestra、MeshCentral 和 Teleport 官方文档/仓库描述作为设计
输入。

## 1. Rundeck

### 官方链接

- [Rundeck Jobs](https://docs.rundeck.com/docs/manual/jobs/)
- [Job Workflows](https://docs.rundeck.com/docs/manual/jobs/job-workflows.html)
- [Rundeck API](https://docs.rundeck.com/docs/api/)
- [rundeck/rundeck](https://github.com/rundeck/rundeck)

### 适用子任务

- `7.7` 高风险远端动作审批与恢复。
- `7.8` Release / Deploy Agent 的计划执行。
- `7.10` Deployment、operation 和审计记录。

### 摘要

- Rundeck 将 Job 定义与每次 Execution 分离；Job 描述参数、节点、workflow 和
  错误处理，Execution 保存独立 id、状态、时间和执行输出。
- ACL、Job 输入约束和执行日志共同形成“谁以什么参数执行哪个受控动作”的审计
  形态；失败处理与重试策略属于 workflow 的显式部分。

### 采用结论

- CloudHelm 分离 ReleasePlan、ApprovalRequest、ToolCall、Deployment 和
  RemoteOperation；每次执行保存不可混用的稳定 id、输入 hash、状态、时间和
  证据引用。
- 高风险动作先审批精确计划，再恢复原 waiting ToolCall；日志和结果与该次
  execution 绑定，而不是只附着在可复用任务定义上。
- 重复请求使用稳定 idempotency key 返回已有 execution/operation，不自动重复
  远端副作用。

### 排除结论

- 不复制 Rundeck 的通用 Job 编辑器、节点发现、插件生态或任意脚本执行面。
- Rundeck 的 retry/重新执行不被视为天然幂等；CloudHelm 仍需 request hash、
  operation store 和数据库唯一约束。
- M7 审批由 CloudHelm 自身持久化，不依赖外部商业审批能力。

## 2. Windmill

### 官方链接

- [Python Scripts Quickstart](https://www.windmill.dev/docs/getting_started/scripts_quickstart/python)
- [Run Scripts](https://www.windmill.dev/docs/getting_started/scripts_quickstart)
- [Audit Logs](https://www.windmill.dev/docs/core_concepts/audit_logs)
- [windmill-labs/windmill](https://github.com/windmill-labs/windmill)

### 适用子任务

- `7.7` Tool action 参数 schema、日志和审计。
- `7.8` Release / Deploy Agent 工具调用。
- `7.12` 控制台部署、日志和诊断证据展示。

### 摘要

- Windmill 把脚本入口参数转换为可描述、可校验的参数界面，并将运行记录与脚本
  版本、输入和结果关联。
- Audit Logs 为操作提供 action、actor、资源、时间和相关元数据，敏感值需要与
  普通参数和日志分离。

### 采用结论

- CloudHelm 每个 CI、Deploy、Remote 工具提供固定 Pydantic/JSON Schema，
  Agent 只提交结构化参数，Tool Gateway 统一校验、审批和审计。
- 审计记录保存 actor、tool、target、request hash、状态、时间、trace id 和脱敏
  结果摘要；env profile、Token、SSH key 只保存引用。
- 控制台基于结构化 execution evidence 展示状态和日志，不把自由脚本文本作为
  用户操作入口。

### 排除结论

- 不实现任意 Python/Shell/TypeScript 脚本编辑器、脚本市场或通用工作流 SaaS。
- 不允许工具参数携带 secret、任意 host、任意 URL、任意路径或自由命令。
- 不直接复制 Windmill 源码、数据库模型或部署拓扑。

## 3. Kestra

### 官方链接

- [Executions](https://kestra.io/docs/workflow-components/execution)
- [Retries](https://kestra.io/docs/workflow-components/retries)
- [Errors](https://kestra.io/docs/workflow-components/errors)
- [kestra-io/kestra](https://github.com/kestra-io/kestra)

### 适用子任务

- `7.8` Release / Deploy Agent 失败处理。
- `7.9` M7 CI 到 Monitoring 状态机。
- `7.10` 事件驱动推进、重试和失败恢复。

### 摘要

- Kestra Execution 保存一次 workflow 运行的状态、任务运行、输入、输出和时间；
  retry 与 error behavior 是显式 workflow 语义。
- 失败恢复区分重试当前动作、从失败位置恢复和启动新 execution，避免把所有失败
  归结为无条件整条流程重跑。

### 采用结论

- CloudHelm 为 CI、release candidate、deployment 和 remote operation 分别保存
  状态与 attempt；事件只驱动满足前置条件的下一步。
- 对纯查询可有界重试；对 build、push、deploy 等副作用先查询同一远端
  operation，再决定恢复，禁止无条件重放。
- 失败保存最后成功阶段、结构化错误、证据和 `next_action`；M7 成功终点进入
  `Monitoring`，不提前写 `Done`。

### 排除结论

- 不引入通用事件总线、分布式调度器、backfill、cron 平台或动态 DAG 编辑器。
- 不采用无界自动重试，不把“再次执行整个 workflow”作为部署超时的默认恢复。
- 不复制 Kestra 的插件运行时或内部队列实现。

## 4. MeshCentral

### 官方链接

- [Ylianst/MeshCentral](https://github.com/Ylianst/MeshCentral)
- [MeshCentral documentation directory](https://github.com/Ylianst/MeshCentral/tree/master/docs)
- [MeshCentral agent source](https://github.com/Ylianst/MeshAgent)

### 适用子任务

- `7.5` Remote Agent capability、heartbeat 和 operation 查询。
- `7.10` RemoteTarget 在线状态与心跳接收。
- `7.12` 控制台远端状态、服务、日志和 diagnostics 展示。

### 摘要

- MeshCentral 使用中心服务维护设备清单与 Agent 连接状态，再通过受管 Agent
  执行远端管理能力；设备身份、连接状态和操作入口相互关联。
- Agent 与中心的持续连接/状态信息使界面能够区分在线、离线和不可达设备，而不
  以一次 API 成功永久推断在线。

### 采用结论

- CloudHelm RemoteTarget 保存稳定 target id、Agent 版本、capabilities、
  last heartbeat 和状态；offline/degraded 由服务端时间阈值计算。
- 部署与诊断请求先校验 target capability；每个远端动作保存 operation id，
  网络中断后查询 operation store。
- 控制台明确展示 heartbeat age、capability、service health 和 operation 状态，
  不把“主机存在”与“Agent 可执行部署”混为一谈。

### 排除结论

- 不实现通用 RMM、远程桌面、KVM、文件传输、用户聊天、设备发现或交互终端。
- 不复制 MeshCentral 协议、Agent 源码、证书体系或设备分组模型。
- M7 只管理 demo/staging 中预注册的 RemoteTarget，不支持公网任意设备注册。

## 5. Teleport

### 官方链接

- [Authentication architecture](https://goteleport.com/docs/reference/architecture/authentication/)
- [Session recording](https://goteleport.com/docs/reference/architecture/session-recording/)
- [Enroll an OpenSSH server without installing a Teleport agent](https://goteleport.com/docs/enroll-resources/server-access/openssh/openssh-agentless/)
- [gravitational/teleport](https://github.com/gravitational/teleport)

### 适用子任务

- `7.7` `remote.ssh_exec_readonly` 身份与审计边界。
- `7.10` 远端操作审计事件。
- `7.11` known-hosts、私钥权限和诊断运维说明。

### 摘要

- Teleport 将用户/主机身份、短期凭据、访问策略与会话审计关联；主机身份不是
  单纯由调用方提交的 host 字符串决定。
- Session recording 和结构化审计事件强调“谁访问了哪个资源、执行了什么、何时
  开始结束”；Agentless OpenSSH 仍需要受信主机配置和受控连接入口。

### 采用结论

- CloudHelm 将 RemoteTarget 服务端记录、pinned host key/fingerprint、专用
  identity 引用和 diagnostic profile 共同作为 SSH 调用身份。
- 只读诊断记录 actor、target、profile、审批策略、开始/结束时间、exit code、
  输出摘要和 trace id；日志执行脱敏和大小限制。
- 正常发布只走 Remote Agent；SSH 是按 target policy 显式启用的补充诊断路径。

### 排除结论

- M7 不引入 Teleport Proxy/Auth Service、CA、短期证书签发、RBAC 平台或完整
  session recording 基础设施。
- 不提供自由 shell、交互会话、端口转发、文件传输或生产主机访问。
- 不以 Teleport 的能力描述替代 OpenSSH host key 校验、CloudHelm 审批或审计
  落库。
