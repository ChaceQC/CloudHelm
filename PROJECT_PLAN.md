# PROJECT_PLAN.md

本文件只记录当前下一步要落实的详细执行计划，不保存总项目规划。总流程和打钩
清单见 `docs/14-roadmap/03-implementation-milestone-flow.md`。

## 1. 当前执行指针

当前阶段为：

```text
M7 Ops Hub 常驻控制面、CI 与远端部署
  -> M7-2B ReleaseCandidate、第一道审批与 WorkflowJob 原子创建
```

用户已明确恢复生产代码实施。M7-2A 数据底座已经完成数据库往返、负约束、
OpenAPI/前端类型同步和 Platform API 全量回归；M7-2B1 server-controlled
RepositoryProfile 与 Binding PUT/GET 也已完成。当前继续 M7-2B2 Candidate、
第一道审批与 WorkflowJob 原子创建，随后进入 M7-2C durable Workflow Engine。

### 1.1 已确认基线

- 当前项目实现版本：`0.5.1`。
- M0-M6 已完成；M1-M6 核验报告见
  `docs/13-testing/01-m1-m6-audit-report.md`。
- M7-0 设计基线已完成。
- M7-1 已完成：
  - Environment。
  - profile-only RemoteTarget。
  - Remote Agent HMAC machine authentication。
  - online/offline/recovery heartbeat。
- M7-2A 已完成：
  - `project_repository_bindings`、`release_candidates`、`workflow_jobs`。
  - ApprovalRequest 的资源/hash/有效期/消费字段与 `cancelled` 状态。
  - Candidate snapshot 类型/ref 约束、published 远端 SHA 非空门禁。
  - WorkflowJob 初始 `next_enqueue_at` 使用 PostgreSQL `now()`。
- M7-2B1 已完成：
  - server-controlled RepositoryProfile。
  - Binding PUT/GET、Project mutex、幂等与 repository identity 冲突映射。
  - binding 漂移后的 Candidate stale / pending Approval expired。
  - CORS PUT、共享 OpenAPI、前端类型与真实并发回归。
- 版本影响：B1 新增兼容 API，属于下一 minor `0.6.0` 的组成部分；当前功能分支
  尚未形成 M7 release/tag，因此开发包继续标记 `0.5.1`，完整 M7 E2E 收口时统一
  发布 `0.6.0`。
- 当前分支：`feature/m7-remote-deploy-closure`。
- 当前开发 PostgreSQL Alembic head：`20260716_0008`。
- Ops Hub 开发/测试基线：安装在 `D:\WSL\Ubuntu-24.04` 的 Ubuntu 24.04
  WSL2，使用发行版内原生 Docker Engine/Compose；Docker Desktop 已卸载。

### 1.2 M7-2A 已验证代码面

```text
modules/platform-api/migrations/versions/
  20260716_0008_create_m7_release_jobs.py

modules/platform-api/src/cloudhelm_platform_api/models/
  __init__.py
  approval.py
  project_repository_binding.py
  release_candidate.py
  workflow_job.py

modules/platform-api/src/cloudhelm_platform_api/schemas/
  approval.py
  common.py

modules/platform-api/src/cloudhelm_platform_api/services/
  approval_service.py

modules/platform-api/tests/
  conftest.py
  m7_release_job_fixture.py
  test_agent_tool_approval_api.py
  test_database_migration.py
  test_m7_release_job_constraints.py

apps/control-console/src/shared/types/
  api.ts

packages/shared-contracts/openapi/
  cloudhelm.openapi.yaml
```

当前验证证据：

- Ubuntu WSL 原生 Docker 中 PostgreSQL/Redis 分别通过 `healthy` / `PONG`。
- `downgrade 20260715_0007 -> upgrade 20260716_0008` 往返通过。
- downgrade 后 M7-2 三表和 Approval 五字段消失，M1-M7-1 表保留。
- `alembic check` 为 `No new upgrade operations detected`。
- migration/约束定向回归覆盖所有新增 CHECK 类别、唯一/部分唯一索引、函数式
  唯一索引、NO ACTION/CASCADE 外键行为和关键 PostgreSQL server default。
- Platform API 当前全量回归 `243 passed, 1 skipped`。
- FastAPI OpenAPI 与共享 YAML 已重新生成并精确同步。
- RepositoryBinding service/API 已由 M7-2B1 完成；Candidate service/API 和
  Workflow Engine 仍属于下一切片，不因 M7-2A 数据底座完成而提前标记。

## 2. 固定架构与范围

### 2.1 Desktop、Local Runtime 与 Ops Hub

```text
CloudHelm Desktop
  Tauri + React
  SQLite 非权威缓存/草稿/sequence
  OS credential store
          │
          ├── Local Runtime sidecar
          │     workspace / Git / test / local tools
          │
          └── HTTPS REST / SSE
                │
CloudHelm Ops Hub（Linux always-on）
  Platform API
  Orchestrator
  Agent Runtime
  Tool Gateway / Policy / Audit
  Workflow Engine
  Deployment Controller
  PostgreSQL
  Redis
  Artifact store
  Identity / User / Session / RBAC
```

固定约束：

- Desktop 最终用户不安装 Docker、PostgreSQL、Redis 或 Python。
- Desktop 不直连 PostgreSQL、Redis、Remote Agent 或 Docker socket。
- Local Runtime 只访问用户 allowlist workspace。
- Ops Hub 是平台权威宿主；Desktop 退出后，已持久化且无需新审批的服务端流程
  继续。
- PostgreSQL 保存业务权威，Redis/Celery 只负责非权威投递。
- 正常 M7/M8 流程由服务端 WorkflowJob/worker 自动推进。
- `run-next` 只保留为开发调试、答辩逐步展示或人工恢复入口。

### 2.2 用户与分层权限

M9 实现：

```text
users
devices
device_pairing_challenges
user_sessions
session_refresh_tokens
user_invitations
roles
permissions
role_permissions
role_bindings
system_security_state
```

授权固定为：

```text
role permissions
  + system/project/environment scope
  + resource attributes/version
  + domain separation-of-duty
```

M7 的 `20260716_0008` 不混入 IAM 或 EventLog sequence migration。M9 再统一完成
Auth API、PermissionService、真实 user provenance、Desktop effective
permissions 和 sequence sync。冻结约束包括：

- 预置权限按 `(role_key, binding_scope_type)` 映射；Environment binding 只授予
  environment-domain permission，父 Project/关联 Task/CI 只嵌入最小脱敏摘要。
- EventLog 增加 `stream_kind`、user/device/session actor 和 `subject_user_id`，
  Desktop cursor 按 `ops_hub_id + user_id + stream_kind + scope_id` 分区。
- TechnicalDesign 审批绑定当前 id/version/content hash，并持久化当前版本的
  user/AgentRun 修改者 provenance；hash 使用 `technical-design-content.v1`
  stable canonical object，修改者 source 受 CHECK 约束。
- Desktop 首次登记和 Local Runtime pairing/session 使用短期 challenge、Ed25519
  proof、credential version 与撤销级联；服务端只存 public key，Local Runtime
  只取得短期 device-bound token且不复用 Desktop refresh token。

### 2.3 业务项目可移植性

四层边界：

1. Project Core：源码、锁文件、README、测试、Dockerfile、standalone Compose、
   `.env.example`、migration。
2. 可删除 Adapter：
   - `cloudhelm.project.yaml`
   - `cloudhelm.env.schema.json`
3. Managed Release Bundle：manifest hash、CI manifest、OCI digest、ReleasePlan、
   rendered Compose。
4. Host Ops Runtime：Ops Hub、Remote Agent、采集器和凭据。

不变量：

- Project Core 不 import CloudHelm SDK。
- Project Core 不连接 CloudHelm 平台 PostgreSQL。
- 删除两个 Adapter 后仍能独立构建、测试、部署和运行。
- Deployment Controller 使用固定 schema + 通用安全 renderer，不长期维护项目
  专用 Jinja 模板。
- Ops Hub、Remote Agent、观测栈和业务项目使用独立 Compose project、network、
  volume、credential、升级和卸载流程。

### 2.4 Agent 协作边界

- 仓库开发参考 Codex CLI 的 root thread / turn / explicit child 模型。
- CloudHelm 当前产品原语使用 `max_depth=1`、
  `max_active_children=6` 的自有计数语义。
- M1-M6 只实现 root/child conversation、父 AgentRun 绑定、生命周期、工具权限
  交集、摘要门禁和 Task cancel 级联。
- 真实 child AgentRun/provider 调度、wait-all、steer/queue、独立 thread API/UI
  和 workspace/worktree scheduler 尚未交付。

## 3. M7 恢复切片

### 3.1 M7-2A：建立并验证 0008 数据底座（已完成）

结果：当前 migration/ORM 已形成可审查、可往返、可独立提交的数据库小步；
后续不得再向 `0008` 混入 M7-2B/C 或 M9 能力。由于 0008 在数据库层保留
`approve_release_candidate` action，M7-2A 同时包含通用 Approval POST 的兼容
guard：该入口必须返回稳定 `422 approval_action_reserved`，不能退化为数据库
CHECK 触发的 500；真正的 Candidate 原子创建和审批决策仍属于 M7-2B。

预检：

```powershell
$env:PYTHONIOENCODING='utf-8'
$OutputEncoding=[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new()

git branch --show-current
git status --short
git diff --stat

cd modules/platform-api
uv lock --check
uv run alembic current
uv run alembic heads
uv run alembic check
```

实现要求：

- 复查 `20260716_0008` 的 upgrade/downgrade。
- 本 revision 只包含：
  - `project_repository_bindings`
  - `release_candidates`
  - `workflow_jobs`
  - ApprovalRequest 的 M7 resource/hash/expiry/consumed 字段
- 不包含：
  - User/RBAC。
  - EventLog sequence。
  - CIRun/Deployment/ServiceInstance。
  - 占位 publish/CI/deploy handler。
- ORM 的字段、nullability、CHECK、索引和 M7 状态默认与 migration 对齐；关键
  PostgreSQL server default 另用省略字段的真实 INSERT 验证。当前 Alembic
  `env.py` 未启用 `compare_server_default`，不得只用 `alembic check` 证明默认值
  一致。
- 外键删除规则、CHECK、部分唯一索引、函数式索引和状态枚举有真实数据库负测。
- 执行：

```powershell
uv run alembic downgrade 20260715_0007
uv run alembic upgrade 20260716_0008
uv run alembic check
uv run pytest -q `
  tests/test_database_migration.py `
  tests/test_m7_release_job_constraints.py `
  tests/test_agent_tool_approval_api.py
```

完成判定：

- downgrade 后 M7-2 表/字段消失且 M7-1/M1-M6 数据结构保留。
- upgrade 后全部恢复。
- migration test、全部新增约束类别的真实违反写入、ORM import、数据库默认值和
  `alembic check` 通过。
- 作为独立小步检查 diff、更新进度、提交并 push。

### 3.2 M7-2B：RepositoryBinding、Candidate 与第一道审批

当前状态：

- M7-2B1 RepositoryProfile 与 Binding PUT/GET 已完成并通过全量回归。
- M7-2B2 Candidate、第一道审批与 reconcile WorkflowJob 正在实施。

计划文件：

```text
modules/platform-api/src/cloudhelm_platform_api/core/
  repository_config.py

modules/platform-api/src/cloudhelm_platform_api/providers/
  repository_profile_provider.py

modules/platform-api/src/cloudhelm_platform_api/repositories/
  project_repository_binding_repository.py
  release_candidate_repository.py
  workflow_job_repository.py

modules/platform-api/src/cloudhelm_platform_api/services/
  project_repository_binding_service.py
  release_candidate_service.py
  release_candidate_policy.py
  approval_domain_decision_service.py

modules/platform-api/src/cloudhelm_platform_api/api/
  repository_bindings.py
  release_candidates.py

modules/platform-api/tests/
  test_m7_project_repository_binding_api.py
  test_m7_release_candidate_api.py
  test_m7_approval_decisions.py
```

接口：

```text
PUT  /api/projects/{project_id}/repository-binding
GET  /api/projects/{project_id}/repository-binding
POST /api/tasks/{task_id}/release-candidate
GET  /api/tasks/{task_id}/release-candidate
```

固定门禁：

- Binding 请求只接受服务端 `profile_key`。
- 拒绝任意 URL、token、credential ref、workflow path、remote、refspec。
- Candidate POST 请求体严格为 `{}`。
- 服务端绑定最新版 M6 PullRequestRecord、完整 commit、受控 target ref、
  binding snapshot/hash、request hash 和第一道 L2 Approval。
- 审批前没有 push、CI 或其他外部副作用。
- 同一 PR + binding snapshot 幂等返回同一 Candidate/Approval/WorkflowJob。
- Binding 漂移后旧 pending/approved Candidate 转 stale，pending Approval 过期。
- `approve_release_candidate` 是内部保留 action，通用 Approval POST 拒绝创建。
- 当前 M7-2 自批门禁只能基于 AgentRun provenance，必须继续标注为领域门禁；
  M9 接入真实认证 user provenance 后再形成不可伪造身份边界。
- 事务采用 Task-first 串行化，各路径按用例锁定 Binding/Candidate/Approval；
  不宣称一条不符合实现的全局总锁序。

黑盒/白盒：

- 201 首次创建、200 幂等命中。
- extra field、缺 PR creator、stale binding、非法 profile、重复/并发请求。
- approval 过期、已消费、hash 漂移、自批、错误 resource/action。
- 审批前 Git/Gitea/CI 调用次数为 0。

### 3.3 M7-2C：Workflow Engine durable continuation

计划目录：

```text
modules/workflow-engine/
  pyproject.toml
  README.md
  src/cloudhelm_workflow_engine/
    config.py
    celery_app.py
    dispatcher.py
    worker_service.py
    handlers.py
    lease_heartbeat.py
    stale_reclaimer.py
  tests/
```

固定语义：

- PostgreSQL `workflow_jobs` 是业务权威。
- Celery message 只携带 `workflow_job_id`。
- API 事务创建业务状态、EventLog 和 WorkflowJob 后提交。
- durable dispatcher 使用 dispatch lease、`next_enqueue_at`、attempt/error 补投。
- worker 使用短事务 claim、lease、heartbeat、terminal update。
- 无外部副作用 job 可安全重排。
- 外部幂等 job 先查询 provider/operation，再决定收敛或重排。
- 外部状态未知进入 `recovery_required`，不盲目重放。
- Redis 重启后由 PostgreSQL pending job 补投。
- Task pause/cancel 在 dispatch 前阻断；dispatch 后记录 cancel requested 并等待
  外部 operation 终态。
- 正常 continuation 不要求 Desktop 点击 `run-next`。

首个生产 handler 只实现无外部副作用的
`release_candidate_reconcile`。Publish、CI、Deploy handler 在对应后续切片实现，
不写固定成功或空 handler。

验证：

```powershell
wsl -d Ubuntu-24.04 -u cloudhelm -- bash -lc @"
cd '/mnt/d/graduation project'
docker compose -f infra/docker-compose.dev.yml \
  --profile optional up -d redis
docker exec cloudhelm-redis-dev redis-cli ping
"@

cd modules/workflow-engine
uv lock --check
uv run pytest -q
```

必须覆盖：

- 重复 message。
- 并发 claim。
- lease heartbeat。
- worker kill / stale reclaim。
- enqueue 前后 crash window。
- Redis 重启补投。
- attempt exhausted。
- Task pause/cancel。
- `recovery_required` 不重放。

### 3.4 M7-3：通用项目契约与 renderer

计划文件：

```text
packages/shared-contracts/schemas/projects/
  cloudhelm-project.schema.json
  cloudhelm-environment.schema.json
  project-delivery-manifest.schema.json

examples/sample-repo-python/
  cloudhelm.project.yaml
  cloudhelm.env.schema.json
  compose.yaml
  README.md

modules/deployment-controller/
  src/.../project_contract.py
  src/.../compose_renderer.py
  src/.../compose_policy.py
  tests/
```

要求：

- JSON Schema 使用明确 `schema_version` 和 `additionalProperties=false`。
- 所有文件引用是规范化仓库相对路径；拒绝绝对路径、`..`、symlink 越界。
- 项目 manifest 不接受 host、endpoint、credential、secret、任意 command、
  privileged、host network、Docker socket 或 host path mount。
- Controller 只使用固定通用 renderer。
- CI manifest/ReleasePlan 绑定 project manifest hash、environment schema hash、
  standalone Compose hash 和 deployment adapter。
- 删除两个 Adapter 后，sample repo 仍按 README standalone 通过测试、Compose
  config/up/health/down。
- 同一 commit 的 standalone/managed 核心行为一致。

### 3.5 M7-4：Ops Hub installation 与 Remote Target bootstrap

计划目录：

```text
infra/ops-hub/
  compose.yaml
  .env.example
  install.sh
  upgrade.sh
  backup.sh
  restore.sh
  uninstall.sh
  cloudhelm-ops-hub.service

infra/remote-agent/
  install.sh
  upgrade.sh
  uninstall.sh
  cloudhelm-remote-agent.service
```

#### 3.5.1 Ops Hub installation/bootstrap

每套 CloudHelm 中心设施只执行一次。最小组件：

```text
TLS ingress
platform-api
orchestrator / agent-runtime workers
tool-gateway / policy / audit
workflow-engine scheduler/workers
deployment-controller
postgresql
redis
artifact storage
gitea / act_runner / OCI registry（内置或受控外接）
```

中心设施门禁：

- 对外只暴露 TLS ingress。
- PostgreSQL、Redis、worker、Docker socket 和内部管理端口不暴露公网。
- 创建专用服务用户、服务凭据、持久卷和备份/恢复目录。
- 验证 Platform `/health`、`/ready`、worker/scheduler heartbeat、持久化和备份。
- 不以 Project、Environment 或业务项目发布为单位重复安装 Ops Hub。
- M7 沿用当前受控网络/认证边界，不创建真实 user/device/session；一次性 identity
  bootstrap token、首个 owner 和 Desktop device/session 固定留到 M9。

#### 3.5.2 Remote Target / Environment bootstrap

每台受管 Linux 目标只安装：

```text
Docker Engine / Compose
cloudhelm-remote-agent.service
telemetry collectors
TLS trust
machine credential
target registration
```

目标门禁：

- 注册到既有 Ops Hub，不安装 Platform API、PostgreSQL、Redis、Gitea/registry、
  用户 pairing 或中心备份体系。
- Ops Hub、Remote Agent、观测栈和业务项目使用独立 Compose project/network/
  volume/credential 或 systemd/data 目录。
- 验证 Remote Agent heartbeat、版本和 capabilities。
- `demo-all-in-one` 允许两条安装链同机运行，但 manifest、credential、升级和
  卸载入口仍分离。
- 普通业务项目发布不重复执行任一 bootstrap。
- 业务项目卸载不删除 Ops Hub 或审计数据。

### 3.6 M7-5：真实 CI、部署与 E2E

完成：

- 固定版本 Gitea、act_runner、OCI registry。
- 不监听 push 的固定 workflow。
- 精确 ref 的唯一 `workflow_dispatch`。
- JUnit/security/SBOM/scan/OCI digest manifest。
- Release / Deploy Agent 严格 ReleasePlan。
- 第二道 deployment approval。
- Tool Gateway → Deploy Tool → Controller → Remote Agent。
- Remote Agent Compose config/pull/digest verify/up/ps/health。
- ServiceInstance、DeploymentResult、MonitoringRegistered。
- Desktop 退出后流程继续。
- Redis 重启补投。
- Linux staging cleanup。

完成后版本目标为 `0.6.0`；在完整 M7 E2E 前保持 `0.5.1`。

## 4. 必须阅读的本地文档

```text
AGENTS.md
云舵 CloudHelm 毕设设计书.md
PROJECT_PROGRESS.md
docs/14-roadmap/03-implementation-milestone-flow.md
docs/01-architecture/04-desktop-ops-hub-project-boundary.md
docs/07-data/01-database-schema.md
docs/07-data/02-storage-boundary.md
docs/08-api/07-environment-deployment-api.md
docs/08-api/12-auth-user-permission-api.md
docs/10-security/03-user-role-permission.md
docs/15-detailed-design/00-mvp-scope-and-cutline.md
docs/15-detailed-design/01-module-contracts.md
docs/15-detailed-design/02-agent-tool-contract.md
docs/15-detailed-design/03-api-detail.md
docs/15-detailed-design/04-data-detail.md
docs/15-detailed-design/05-workflow-state-events.md
docs/15-detailed-design/06-deployment-observability-detail.md
docs/15-detailed-design/07-testing-acceptance-matrix.md
docs/15-detailed-design/09-m7-ci-remote-deployment-flow.md
docs/15-detailed-design/10-desktop-ops-hub-standalone-project.md
docs/15-detailed-design/11-identity-access-control.md
```

外部资料归档：

```text
informations/m7-ci-remote-deploy/official-references.md
informations/m7-ci-remote-deploy/reference-projects.md
informations/m7-desktop-ops-architecture/official-references.md
informations/m7-desktop-ops-architecture/identity-access-references.md
informations/m4-agent-context/codex-responses-context.md
```

## 5. 恢复实施前统一预检

```powershell
$env:PYTHONIOENCODING='utf-8'
$OutputEncoding=[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new()

git branch --show-current
git status --short
git log --oneline --decorate --max-count=10
git diff --stat

wsl -d Ubuntu-24.04 -u cloudhelm -- bash -lc @"
cd '/mnt/d/graduation project'
docker compose -f infra/docker-compose.dev.yml ps
docker compose -f infra/docker-compose.dev.yml --profile optional ps
"@

cd modules/platform-api
uv lock --check
uv run alembic current
uv run alembic heads
uv run alembic check
```

要求：

- 当前分支不是 `main`。
- 工作区修改集合与当前 M7-2B/C 执行指针及 `PROJECT_PROGRESS.md` 一致。
- 开发数据库 head 与代码 revision 一致。
- PostgreSQL/Redis 可用后再运行 migration/worker 测试。
- 数据、API、worker 和文档按可验证子系统分步提交，不混入未来 M9 能力。

## 6. 验证矩阵

### 后端

```powershell
cd modules/platform-api
uv run pytest -q

cd ..\orchestrator
uv run pytest -q

cd ..\agent-runtime
uv run pytest -q

cd ..\tool-gateway
uv run pytest -q
```

### 前端

```powershell
cd apps/control-console
npm.cmd test
npm.cmd run build
```

### 数据库

```powershell
cd modules/platform-api
uv run alembic downgrade 20260715_0007
uv run alembic upgrade head
uv run alembic check
```

### 契约

- FastAPI OpenAPI 与 `packages/shared-contracts/openapi/cloudhelm.openapi.yaml`
  反序列化后精确一致。
- 全部 JSON Schema 通过 Draft 2020-12 元校验。
- project/env schema 与 Python/TypeScript 类型、文档示例同步。

### 黑盒

- 正常路径。
- 缺失/额外字段。
- 非法枚举和非法状态。
- 401/403/404/409/422。
- 重复与并发提交。
- 审批前无副作用。
- Desktop 退出后 continuation。
- Adapter 删除后的 standalone。

### 白盒

- repository/service/policy 分层。
- migration、CHECK、索引、事务回滚。
- Task-first 串行化和具体资源锁。
- WorkflowJob claim/lease/heartbeat/reclaim。
- refresh/permission/EventLog 留到 M9，不混入 M7 测试完成声明。

## 7. 文档与 Git 收口

每个可验证小步：

1. 更新相关 API/Data/Workflow/Testing 文档。
2. 更新 `PROJECT_PROGRESS.md`。
3. 只勾已有真实证据的 Roadmap 项。
4. 执行：

   ```powershell
   git status --short
   git diff --stat
   git diff --check
   ```

5. 复查关键 diff，移除缓存、日志、构建产物、临时备份和凭据。
6. 使用中文 commit message。
7. push 当前功能分支。
8. push 后再次检查 status/log/remote branch。

## 8. 风险与处理

|风险|处理|
|---|---|
|开发 DB 与 0008 约束漂移|每次修改 migration 后重新执行真实 downgrade/upgrade、约束负测和 `alembic check`|
|WSL 环境记录与生产代码混入同一提交|WSL 开发基线已独立提交；M7-2A 再按数据/契约小步提交|
|把 IAM 混入 M7 migration|IAM/EventLog sequence 固定留给 M9 新 revision|
|继续依赖 Desktop `run-next`|M7 worker 以 durable job 自动 continuation；入口仅调试/恢复|
|项目专用模板扩散|以 project/env schema + 通用 renderer 替换|
|Redis 消息丢失|PostgreSQL job 权威 + durable dispatcher 补投|
|外部副作用未知|查询 provider/operation；未知进入 `recovery_required`|
|业务项目绑定平台|Adapter 可删除、standalone/managed 双路径强制验收|
|用户权限只做前端|M9 API 每次鉴权，Desktop 只消费 effective permission/capability|
|subagent 能力过度声明|只描述内部原语；真实 child 调度仍保持未实现|

## 9. 当前完成判定

生产代码实施已经恢复。M7-2A 已提交并 push；M7-2B1 RepositoryProfile 与
Binding PUT/GET 已满足真实代码、幂等/漂移/并发黑盒白盒测试、OpenAPI、前端
类型、文档和 WSL PostgreSQL 证据。当前执行指针进入 M7-2B2 Candidate、第一道
审批与 WorkflowJob 原子创建。

后续每个切片仍必须有真实代码、黑盒/白盒测试、数据库/契约验证、文档、
`PROJECT_PROGRESS.md`、Roadmap 和 Git 证据，才能标记完成。
