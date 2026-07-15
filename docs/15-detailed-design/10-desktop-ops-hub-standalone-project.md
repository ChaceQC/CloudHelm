# Desktop、Ops Hub 与可独立项目细化契约

> 目的：把“跨平台桌面安装、App 可离线、远端 Agents 运维系统常在线、业务项目
> 可受管也可独立运行”细化为可实现和可验收的契约。
> 当前状态：文档冻结阶段，尚未实现生产代码。

## 1. 四层产物边界

```text
A. Project Core
   源码、锁文件、测试、README、Dockerfile、standalone Compose、
   .env.example、migration、数据卷说明
          │
          ├── 可完全单独运行、部署和交付
          │
B. CloudHelm Adapter
   cloudhelm.project.yaml
   cloudhelm.env.schema.json
          │
          ├── 可删除；只服务受管部署
          │
C. Managed Release Bundle
   CI manifest、project manifest hash、OCI digest、ReleasePlan、
   rendered Compose、release metadata、health result
          │
          └── 由 CI / Controller 生成

D. Host Ops Runtime
   Ops Hub、Remote Agent、采集器、凭据、operation store
   与业务项目源码和生命周期独立
```

不变量：

- 删除 B 后，A 仍能按 README 独立运行。
- A 不 import CloudHelm SDK，不调用 Platform API，不连接 CloudHelm 数据库。
- C 不作为源码运行依赖。
- D 不注入业务源码，也不因业务项目卸载而删除。

## 2. Project Core 独立运行基线

每个 Agent 新建项目和被 CloudHelm 纳管的既有项目必须满足：

|类别|必选契约|
|---|---|
|源码|完整源码、依赖清单、锁文件；无 CloudHelm workspace 绝对路径|
|README|开发、测试、构建、启动、停止、升级、备份/数据保留命令|
|配置|`.env.example` 只包含变量名、类型和占位说明|
|密钥|不提交真实值；支持环境变量，推荐同时支持 `_FILE`|
|测试|正常、异常、配置缺失、健康和持久化测试|
|容器|至少一个可独立构建 Dockerfile；非 root；响应 SIGTERM|
|编排|`compose.yaml` 或显式声明的 standalone Compose|
|健康|网络服务提供免认证、无敏感数据的健康检查，默认 `/health`|
|日志|stdout/stderr 是必选主通道，文件日志只作补充|
|指标|`/metrics` 可选；声明后必须是可解析的 Prometheus 格式|
|数据|项目自己的 migration、volume 或外部数据库契约自包含|
|CI|可在独立仓库构建和测试，不要求 CloudHelm 在线|
|剥离性|缺少全部 `CLOUDHELM_*` 环境变量时仍按独立模式启动|

业务项目数据库不得复用 Ops Hub PostgreSQL database/schema/user。

## 3. CloudHelm Adapter

使用根目录文件：

```text
cloudhelm.project.yaml
cloudhelm.env.schema.json
```

不使用 `.cloudhelm/` 保存提交版契约，因为该目录已用于本地临时 Artifact/数据且在
示例项目中被 `.gitignore` 排除。

### 3.1 `cloudhelm.project.yaml`

建议最小结构：

```yaml
schema_version: cloudhelm.project.v1

project:
  key: sample-repo-python
  display_name: Sample Service

standalone:
  compose_file: compose.yaml

artifacts:
  images:
    - key: api
      ci_artifact: sample-service

services:
  - key: api
    image_key: api
    container_port: 8000
    health:
      kind: http
      path: /health
      expected_status: [200]
      timeout_seconds: 3
    logs:
      source: stdout
      format: text
    metrics:
      kind: prometheus
      path: /metrics
      required: false
    environment_schema: cloudhelm.env.schema.json
    volumes:
      - key: application-data
        mount_path: /var/lib/sample-service
        retention: retain

compatibility:
  deployment_adapter: docker_compose_v1
```

约束：

- 对应 JSON Schema 使用 `additionalProperties=false`。
- 文件引用必须是规范化仓库相对路径，拒绝绝对路径、`..` 和 symlink 越界。
- manifest 不保存 host、Remote Agent endpoint、远端根目录、credential ref、
  secret value 或任意 command。
- 不允许自定义 `privileged`、host network、Docker socket、host path mount 或
  entrypoint override。
- 平台 identity 通过外部 metadata/label 注入，不是业务应用启动前提。

### 3.2 `cloudhelm.env.schema.json`

只描述逻辑配置：

```json
{
  "schema_version": "cloudhelm.environment.v1",
  "variables": [
    {
      "name": "DATABASE_URL",
      "required": true,
      "secret": true,
      "supports_file": true
    }
  ]
}
```

映射链：

```text
项目逻辑变量
  -> environment schema
  -> Ops Hub env profile
  -> Remote Agent credential/_FILE 注入
```

项目只认识变量名，不认识 CloudHelm credential ID。

## 4. Managed Release Bundle

CI manifest 必须增加：

```text
project_contract_version
project_manifest_sha256
environment_schema_sha256
standalone_compose_sha256
```

ReleasePlan 必须增加：

```text
project_contract_version
project_manifest_sha256
deployment_adapter
```

Controller 使用“固定 schema + 通用安全 renderer”生成受管 Compose，不再为每个
项目在 CloudHelm 仓库维护一份项目专用 Jinja 模板。

独立 Compose 与受管 rendered Compose 不要求字节一致，但必须语义一致：

- service/image identity。
- container port。
- health endpoint。
- required variables。
- persistent volume retention。
- graceful stop。

## 5. Ops Hub 与业务项目隔离

同一 Linux 主机也必须使用：

```text
cloudhelm-ops
cloudhelm-project-<project-key>
cloudhelm-observability
```

隔离项：

- Compose project。
- network。
- named volume。
- service user。
- credential。
- backup。
- upgrade/uninstall。

业务项目可以继续运行，即使：

- Desktop 关闭。
- Desktop 与 Ops Hub 断网。
- Local Runtime 停止。
- Ops Hub 短暂重启。

Ops Hub 恢复后通过 Remote Agent/service status/manifest identity 重新收敛状态。

## 6. Desktop 运行时契约

Desktop 安装包包含：

```text
Tauri shell
React assets
local-runtime sidecar
SQLite migrations
icons/version/update metadata
```

不包含 PostgreSQL、Redis、Docker、Remote Agent 或 Ops Hub secret。

Desktop SQLite 只保存：

```text
server_profiles
ui_preferences
offline_drafts
event_cursors
cached_read_models
local_runtime_registry
```

credential 使用 OS credential store。React 不直接执行任意 SQL，固定通过 Rust
repository/command 调用。

## 7. 用户/device 与 machine 身份

身份分离：

|身份|用途|存储|
|---|---|---|
|user access/refresh token|Desktop 查询、提交、审批|OS credential store|
|Local Runtime Ed25519 private key|配对证明与短期 device session|OS credential store|
|Remote Agent machine credential|heartbeat、operation|远端 credential file/store|
|Controller credential|调用 Remote Agent|Ops Hub secret store|

要求：

- Ops Hub 只通过 TLS 暴露。
- 首次 bootstrap 创建第一个 `system_owner` 和 Desktop device/session；M9 必须
  交付多用户、scoped RBAC 与职责分离，不能停留在调用方自报管理员身份。
- 新 Desktop public id 通过短期 login challenge 登记；Local Runtime 由 active
  Desktop session 创建短期、单次消费 pairing challenge，并使用独立 credential。
- Desktop 与 Local Runtime 都使用 Ed25519 challenge proof，服务端只保存 public
  key/fingerprint/version；Local Runtime 另用签名 challenge 换取短期
  device-bound access token，不签发 refresh token。
- Local Runtime 的每次工具任务按用户 effective permissions、sidecar allowlist
  和当前 project/task/workspace 归属求交集，不复用 Desktop refresh token。
- `actor_id`、角色和审批人由认证上下文派生，不能相信请求体自报身份。
- 用户/device token 与 Remote Agent machine credential 不复用。

## 8. 离线与重连契约

### 8.1 EventLog 扩展目标

```text
sequence BIGINT
stream_kind TEXT
project_id UUID
aggregate_type TEXT
aggregate_id UUID
aggregate_version BIGINT
schema_version TEXT
actor_user_id UUID
actor_device_id UUID
actor_session_id UUID
subject_user_id UUID
```

`sequence` 是同一 Ops Hub 内单调递增的客户端同步位置；UUID `id` 继续用于事件
唯一身份。

### 8.2 Snapshot + event tail

```text
GET /api/me/security-snapshot
GET /api/me/events?after_sequence=<n>
GET /api/me/events/stream

GET /api/projects/{project_id}/sync-snapshot
GET /api/projects/{project_id}/events?after_sequence=<n>
GET /api/projects/{project_id}/events/stream
```

`/api/me/*` 返回当前认证用户的 User/Device/Session/RoleBinding/permission-version
控制流，并按 `subject_user_id` 过滤；它不依赖用户当前是否打开某个 Project。

snapshot 返回：

```json
{
  "project_id": "uuid",
  "high_watermark_sequence": 1234,
  "resource_versions": {},
  "projects": [],
  "tasks": [],
  "approvals": [],
  "environments": [],
  "deployments": []
}
```

重连算法：

1. Desktop 按 `ops_hub_id + user_id + stream_kind + scope_id` 读取本地 last
   sequence；user_control 流只接受 subject 为当前认证用户的事件。
2. 获取缺失事件；若 cursor 过期则拉取完整 snapshot。
3. 按 event id 去重。
4. 按 aggregate version 拒绝旧覆盖。
5. 从 snapshot high-watermark 打开 SSE，补齐建连窗口。
6. 成功应用后更新 SQLite cursor。

### 8.3 写命令

写请求统一使用：

```text
Idempotency-Key
If-Match / expected_resource_version
```

App 离线时：

- 需求、评论和表单允许保存为 draft。
- 审批、部署、取消、回滚和远端命令只保存为需要重新确认的 intent。
- 重连后重新认证、读取最新 resource version，再由用户确认提交。
- 不自动 replay 高风险 intent。

服务端已确认持久化的命令不依赖 Desktop 在线；事务提交后创建 EventLog 和
WorkflowJob，由 worker 继续执行。

## 9. Orchestrator 推进契约

正常工作流：

```text
用户提交命令/审批
  -> API 事务写业务状态 + EventLog + WorkflowJob
  -> commit
  -> server worker 推进
```

`run-next`：

- 保留为本地开发调试、答辩逐步展示和人工恢复入口。
- 不作为常在线远端 CI、部署、监控和 SRE 流程的正常触发器。

Desktop 离线时：

- 不需要新审批的步骤继续。
- 到达 risk/approval gate 后持久等待。
- 通知可通过邮件/Webhook 等 P1 通道发送。

## 10. 计划共享契约

后续代码阶段创建：

```text
packages/shared-contracts/schemas/projects/
  cloudhelm-project.schema.json
  cloudhelm-environment.schema.json
  project-delivery-manifest.schema.json

packages/shared-contracts/schemas/sync/
  project-sync-snapshot.schema.json
  project-event-envelope.schema.json
```

所有 schema 必须：

- 有明确 `schema_version`。
- `additionalProperties=false`。
- 记录兼容性和变更历史。
- 同步 Python Pydantic、TypeScript 类型和文档示例。

## 11. 双路径验收矩阵

|编号|测试|通过证据|
|---|---|---|
|PORT-01|移除两个 CloudHelm adapter 文件|项目按 README 启动，health 通过|
|PORT-02|独立 Compose|config/up/wait/ps/down 全部通过|
|PORT-03|未启动 Platform API/Redis/Remote Agent|业务服务仍健康|
|PORT-04|重启/升级数据保持|命名卷保留，migration 可重复执行|
|PORT-05|缺失/非法配置|稳定失败且无 secret 回显|
|CH-01|project/env schema|有效通过，extra/path/secret 违规拒绝|
|CH-02|通用 Controller renderer|固定 digest，无 privileged/host network/socket/越界挂载|
|CH-03|证据链|commit、manifest hash、CI manifest、digest、ReleasePlan 一致|
|CH-04|标准观测|stdout 可读；metrics 可选且声明时可解析|
|CH-05|密钥边界|源码、manifest、Artifact、ReleasePlan、Compose、日志无 secret|
|DUAL-01|同 commit 独立/受管部署|API、health、持久化行为一致|
|DUAL-02|Desktop 断线|项目和已持久化远端工作流继续|
|DUAL-03|导出交付|源码、锁、README、Dockerfile、Compose、env、migration、校验摘要齐全|
|SYNC-01|Desktop 长时间离线后重连|事件无丢失/重复/倒序覆盖|
|OPS-01|退出 Desktop 后完成部署|远端到达 healthy/Monitoring|

## 12. 版本与迁移影响

- 本轮只修改文档，当前实现版本继续为 `0.5.1`。
- M7 服务端 Ops Hub 与远端部署闭环完成目标仍为 `0.6.0`。
- Desktop productization 与 installer 作为后续兼容新增能力进入 M9。
- 现有服务端 Alembic migration 继续使用 PostgreSQL。
- Desktop SQLite 使用独立 migration chain。
- EventLog sequence/project/aggregate 字段需要后续新 PostgreSQL migration。
- ReleasePlan、CI manifest、project manifest 和 sync API 会形成新版本化契约。

### 12.1 里程碑责任

|里程碑|责任|
|---|---|
|M7|常在线 Ops Hub、durable continuation、project/env adapter schema、通用 renderer、真实 CI 与远端部署|
|M8|集中监控、告警、Incident 与 SRE 分析，Desktop 退出后仍持续运行|
|M9|Tauri Desktop、Local Runtime、SQLite/credential store、用户/session/device、scoped RBAC、sequence sync|
|M10|Windows/Linux 安装包、Ops Hub 安装/升级/备份恢复、独立/受管双路径与最终 E2E|

## 13. 当前未实现边界

截至 2026-07-16，以下均为规划：

- Tauri `src-tauri`、Windows/Linux installer。
- Desktop SQLite、OS credential store、server profile 和用户认证。
- Local Runtime sidecar。
- Ops Hub 安装 profile、backup/restore。
- project/env manifest schema 和通用 Controller renderer。
- sequence-based project sync。
- 同 commit 独立/受管双路径 E2E。

当前 M6 sample fixture 的独立启动事实不能代替上述通用契约完成证据。
