# PROJECT_PLAN.md

本文件只记录当前下一步要落实的详细执行计划，不保存总项目规划。总流程和打钩
清单见 `docs/14-roadmap/03-implementation-milestone-flow.md`。

## 1. 当前执行指针

```text
M7 Ops Hub 常驻控制面、CI 与远端部署
  -> M7-2D CIRun、Deployment、ServiceInstance 数据与 migration
```

M7-2A 数据底座、M7-2B1 RepositoryBinding、M7-2B2 Candidate/第一道审批和
M7-2C Redis + Celery durable Workflow Engine 已完成。当前切片只建立真实
PostgreSQL、ORM、repository 和严格共享数据契约，为后续受控 candidate ref、
唯一 Gitea CI、ReleasePlan、第二道审批和远端部署纵切提供权威数据底座。

当前版本继续保持 `0.5.1`；完整 M7 E2E 收口时再发布 `0.6.0`。

## 2. 已确认基线

### 2.1 已交付能力

- M1-M6 本地需求、设计、实现、测试、安全和等价 PR 闭环。
- M7-1 Environment、RemoteTarget、machine authentication 与 heartbeat。
- M7-2A：
  - `project_repository_bindings`
  - `release_candidates`
  - `workflow_jobs`
  - 资源型 Approval 字段与数据库约束
- M7-2B1：
  - server-controlled RepositoryProfile
  - Binding PUT/GET
  - identity 冲突、幂等和漂移失效
- M7-2B2：
  - 严格 `{}` Candidate POST
  - 第一道人工作为 L2 Approval
  - Candidate、Approval、pending reconcile WorkflowJob 和事件同事务创建
  - PR/Binding/request freshness、expiry、consumed 和实现 AgentRun 自批门禁
- M7-2C：
  - PostgreSQL 权威 dispatcher/worker/reclaimer
  - dispatch/worker lease、heartbeat、retry、补投和 Task 生命周期联动
  - 首个真实 `release_candidate_reconcile` handler
  - WSL 隔离 Redis restart 与真实 prefork hard-crash 回排

### 2.2 当前环境

- 分支：`feature/m7-remote-deploy-closure`
- Alembic head：`20260716_0008`
- WSL：`Ubuntu-24.04`
- Docker：WSL 发行版内原生 Docker Engine/Compose
- PostgreSQL：`127.0.0.1:15432`
- Redis：`127.0.0.1:16379`
- WSL user-local uv：`/home/cloudhelm/.local/bin/uv`
- Platform API WSL venv：
  `/home/cloudhelm/.cache/cloudhelm/platform-api-venv`
- Workflow Engine WSL venv：
  `/home/cloudhelm/.cache/cloudhelm/workflow-engine-venv`
- Docker Desktop 不作为开发、测试或正式 Desktop 安装依赖。

## 3. 本切片目标与裁剪线

### 3.1 必须完成

1. 先同步最高层设计书、数据库总表、逐表文档和详细设计，冻结三表字段、枚举、
   生命周期、唯一约束、外键和索引。
2. 新增 Alembic `20260716_0009`：
   - `ci_runs`
   - `deployments`
   - `service_instances`
   - deployment Approval 的 action/resource/risk 组合约束
3. 新增三表 SQLAlchemy ORM，并保证 metadata 与 migration 完全一致。
4. 新增只负责持久化和查询的 repository，不写 CI、部署或远端副作用状态机。
5. 新增严格 Pydantic record/read DTO 和 Draft 2020-12 共享 JSON Schema。
6. 使用真实 PostgreSQL 验证正向写入、负约束、FK、唯一键、分页、锁和并发竞争。
7. 使用 WSL 完成 migration 往返、Alembic check 和 Platform API 全量回归。
8. 同步 README、数据文档、测试矩阵、Roadmap、`PROJECT_PROGRESS.md` 和下一阶段
   `PROJECT_PLAN.md`。

### 3.2 本切片不做

- candidate ref push、`git ls-remote` 远端 SHA 复核。
- Gitea workflow dispatch、webhook、poll、runner 或 registry。
- CI Tool、Release / Deploy Agent、严格 ReleasePlan Agent 输出。
- 第二道审批 API、remote deployment API。
- WorkflowJob CI/deploy handler 或 external operation resolver。
- Deployment Controller、Remote Agent Compose operation。
- Service/log API、SSE、Control Console CI/部署页面。
- 正式 Ops Hub TLS installation/bootstrap。
- 自动 restart、rollback 或 `rolled_back` 状态。

本切片不得新增未来 HTTP path，不生产 CIRun/Deployment/ServiceInstance 事件，
也不得修改 `20260716_0008` 的
`ck_workflow_jobs_m7_2_handler`。后续 external handler 必须使用新 migration。

## 4. 写代码前必须冻结的设计

当前 `docs/07-data/01-database-schema.md`、旧逐表文档、详细设计和总设计书之间
存在字段与状态漂移。编码前先同步：

- `云舵 CloudHelm 毕设设计书.md`
- `docs/07-data/01-database-schema.md`
- 新增 `docs/07-data/tables/ci_runs.md`
- 重写 `docs/07-data/tables/deployments.md`
- 重写 `docs/07-data/tables/service_instances.md`
- `docs/15-detailed-design/04-data-detail.md`
- `docs/15-detailed-design/09-m7-ci-remote-deployment-flow.md`

冻结结论如下。

### 4.1 CIRun

字段：

```text
id
task_id
project_id
pull_request_record_id
release_candidate_id
provider
repository_external_id
external_run_id
external_job_id
workflow_id
workflow_revision
source_ref
commit_sha
status
idempotency_key
last_event_action
last_event_status
last_delivery_id
provider_head_sha
provider_updated_at
artifact_manifest_id
image_index_digest
platform_manifest_digest
started_at
finished_at
created_at
updated_at
```

状态：

```text
triggered
running
passed
failed
cancelled
```

关键约束：

- provider 固定 `gitea`。
- `source_ref` 必须为完整 `refs/heads/...`。
- commit/head SHA 只允许 40/64 位小写 hex；head 非空时必须等于 commit。
- OCI digest 固定 `sha256:<64 lowercase hex>`。
- `external_run_id` 在 dispatch 已接受但 provider run 尚未关联时允许为空。
- `release_candidate_id` 唯一。
- `(task_id, idempotency_key)` 唯一。
- `(provider, repository_external_id, external_run_id)` 非空时唯一。
- passed 必须具有 Artifact manifest、两类 digest、started/finished；其他状态不得
  伪造 passed 证据。
- provider event/delivery 字段只保存最后一次安全幂等线索；完整 delivery 审计由
  后续 webhook EventLog 纵切实现。

### 4.2 Deployment

字段：

```text
id
task_id
project_id
environment_id
remote_target_id
ci_run_id
release_plan_artifact_id
commit_sha
image_ref
image_digest
platform_manifest_digest
release_version
request_hash
approval_id
remote_operation_id
status
health_summary_json
failure_code
failure_summary
requested_by_actor
approved_by_actor
dispatched_by_agent_run_id
idempotency_key
started_at
finished_at
rollback_candidate_id
rollback_request_artifact_id
created_at
updated_at
```

状态：

```text
planned
pending_approval
queued
deploying
verifying
healthy
unhealthy
failed
rollback_requested
cancelled
```

关键约束：

- commit 为完整 40/64 位小写 hex；request/image/platform digest 为 SHA-256 格式。
- `health_summary_json` 为空或 JSON object；失败摘要必须脱敏且有长度上限。
- `(task_id, idempotency_key)`、`(environment_id, release_version)` 唯一。
- `approval_id` 非空时唯一。
- `(remote_target_id, remote_operation_id)` 非空时唯一。
- pending approval 起绑定 Approval；queued 起具有 approved actor。
- deploying/verifying 必须有 operation 和 started time。
- healthy/unhealthy 必须有 operation、started/finished 和 health summary。
- failed 必须有 finished time 和稳定 failure code。
- rollback_requested 必须同时绑定历史 candidate 与 rollback request Artifact；
  candidate 不能自引用。
- ReleasePlan hash 使用不可变 `artifacts.sha256`，并进入后续 Approval canonical
  request/request hash；本表不复制第二份可漂移 hash。

### 4.3 ServiceInstance

字段：

```text
id
deployment_id
environment_id
remote_target_id
service_name
compose_project
runtime_type
runtime_ref
image_digest
status
health_url
health_result_json
last_health_check_at
last_error_code
created_at
updated_at
```

状态：

```text
starting
running
healthy
unhealthy
stopped
failed
```

关键约束：

- M7 runtime type 固定 `docker_compose`。
- service/Compose project 使用受控 slug。
- image digest 固定 SHA-256。
- `health_result_json` 为空或 JSON object。
- healthy/unhealthy 必须同时具有 health result 和 last health check。
- `(deployment_id, service_name)` 唯一。
- Environment、Target、digest 与父 Deployment 的一致性由后续 service 层在
  Task/Deployment 锁内重验；本切片只提供精确查询和锁入口。

### 4.4 Deployment Approval

`approval_requests` 增加并冻结：

```text
action=approve_deployment
resource_type=deployment
risk_level=L3
requested_by_agent_run_id IS NOT NULL
```

其他 action 不能冒充 deployment resource；现有 release candidate 组合继续保持
L2 和原有约束。M7-2D 只建立数据库约束，不新增审批创建/决策 API。

## 5. 实现前必须查阅

- `AGENTS.md`
- `docs/15-detailed-design/00-mvp-scope-and-cutline.md`
- `docs/15-detailed-design/01-module-contracts.md`
- `docs/15-detailed-design/04-data-detail.md`
- `docs/15-detailed-design/07-testing-acceptance-matrix.md`
- `docs/15-detailed-design/09-m7-ci-remote-deployment-flow.md`
- `docs/07-data/00-entity-model.md`
- `docs/07-data/01-database-schema.md`
- `docs/07-data/tables/{approval_requests,artifacts,release_candidates}.md`
- `informations/m7-ci-remote-deploy/official-references.md`
- PostgreSQL 16、SQLAlchemy 2.x、Alembic、Pydantic v2、JSON Schema 2020-12
  官方文档。

如果官方资料与现有设计冲突，先更新本计划和对应 `docs/`，再写 migration。

## 6. 预检

### 6.1 Git 与工作区

```powershell
git branch --show-current
git status --short
git diff --stat
git diff --check
```

必须位于 `feature/m7-remote-deploy-closure` 或从 `dev` 拉出的 M7 功能分支；禁止
在 `main` 修改。

### 6.2 WSL Ops Hub 依赖

```powershell
wsl -d Ubuntu-24.04 -- docker ps
wsl -d Ubuntu-24.04 -- `
  docker exec cloudhelm-postgres-dev `
  pg_isready -U cloudhelm -d cloudhelm
wsl -d Ubuntu-24.04 -- `
  docker exec cloudhelm-redis-dev redis-cli ping
wsl -d Ubuntu-24.04 -u cloudhelm -- `
  /home/cloudhelm/.local/bin/uv --version
```

预期：PostgreSQL accepting connections、Redis PONG、uv 可用。Ops Hub/Platform
API migration 和 pytest 均从 WSL 执行。

### 6.3 数据库基线

```powershell
wsl -d Ubuntu-24.04 -u cloudhelm `
  --cd "/mnt/d/graduation project/modules/platform-api" -- `
  env `
  PATH=/home/cloudhelm/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin `
  UV_PROJECT_ENVIRONMENT=/home/cloudhelm/.cache/cloudhelm/platform-api-venv `
  CLOUDHELM_DATABASE_URL=postgresql+psycopg://cloudhelm:cloudhelm_dev@127.0.0.1:15432/cloudhelm `
  /home/cloudhelm/.local/bin/uv run alembic current
```

预期当前为 `20260716_0008 (head)`。

## 7. 计划文件

```text
modules/platform-api/
  migrations/versions/
    20260716_0009_create_m7_ci_deployment_data.py
  src/cloudhelm_platform_api/
    models/
      ci_run.py
      deployment.py
      service_instance.py
    repositories/
      ci_run_repository.py
      deployment_repository.py
      service_instance_repository.py
    schemas/
      ci_run.py
      deployment.py
      service_instance.py
  tests/
    m7_ci_deployment_fixture.py
    test_m7_ci_deployment_constraints.py
    test_m7_ci_deployment_repositories.py
    test_m7_ci_deployment_contracts.py

packages/shared-contracts/schemas/
  ci/ci-run.schema.json
  deployment/deployment.schema.json
  deployment/service-instance.schema.json
```

同步：

```text
云舵 CloudHelm 毕设设计书.md
docs/07-data/README.md
docs/07-data/01-database-schema.md
docs/07-data/tables/{ci_runs,deployments,service_instances}.md
docs/15-detailed-design/{04-data-detail,07-testing-acceptance-matrix,
09-m7-ci-remote-deployment-flow}.md
docs/03-modules/modules/platform-api.md
modules/platform-api/README.md
packages/shared-contracts/README.md
docs/14-roadmap/03-implementation-milestone-flow.md
PROJECT_PROGRESS.md
```

## 8. 实现任务

### 8.1 文档契约冻结

- 清除旧 `image_tag/deployed_by/rollback_from` 模型。
- 增加 `ci_runs.md` 并同步两级文档索引。
- 明确三表状态、字段、CHECK、FK、删除规则、唯一键和索引。
- 明确 M7-2D 只是数据底座，不把 CI、API、事件或远端执行写成已交付。

### 8.2 Migration

- revision：`20260716_0009`
- down revision：`20260716_0008`
- 建表顺序：
  1. `ci_runs`
  2. `deployments`
  3. `service_instances`
- downgrade 反向删除，并恢复原 Approval CHECK。
- constraint/index 必须显式命名，测试按名称断言。
- 不修改历史 migration。

### 8.3 ORM

- 使用 SQLAlchemy 2.x `Mapped`。
- 公共时间与 UUID mixin 复用现有基类。
- JSON 使用 PostgreSQL JSONB。
- ORM `nullable/default/server_default/index/constraint` 与 migration 精确一致。
- 更新 `models/__init__.py`，确保 Alembic metadata 可发现。

### 8.4 Repository

`CIRunRepository`：

```text
create
get(for_update)
get_by_candidate
get_by_task_idempotency
get_by_external_run
list_by_task
list_by_project
```

`DeploymentRepository`：

```text
create
get(for_update)
get_by_task_idempotency
get_by_environment_release_version
get_by_remote_operation
latest_by_task
list_by_project
list_by_environment
```

`ServiceInstanceRepository`：

```text
create
create_many
get
get_by_deployment_service
list_by_deployment
list_by_environment
```

repository 只负责 SQLAlchemy 查询、锁和稳定分页，不写状态机、事件、审批或外部
调用。列表排序固定为 `created_at DESC,id DESC`；同一 Deployment 的服务列表按
`service_name,id`。

### 8.5 Pydantic 与 JSON Schema

- Pydantic v2 使用 `ConfigDict(extra="forbid", from_attributes=True)`。
- 本切片只新增内部 Record/Read DTO，不暴露调用方 Create DTO。
- 共享 Schema 使用 Draft 2020-12：
  - 全字段 `required`
  - 可空字段使用 `null`
  - `additionalProperties=false`
  - UUID/date-time/hash/ref/digest pattern 明确
- Pydantic 生成 schema 与共享 JSON 做结构精确一致测试。
- DTO/JSON 不得包含 token、credential、clone URL、raw logs 或未脱敏失败内容。
- OpenAPI 仍与共享 YAML 精确一致，不新增未来 endpoint。

## 9. 测试矩阵

### 9.1 黑盒/数据库约束

- 每个合法状态至少一条可写形态。
- 非法 status、SHA、digest、ref、slug、JSON 类型、生命周期和时间顺序命中精确
  constraint name。
- Candidate 只能关联一个 CIRun。
- provider/repository/run、Task/idempotency、Environment/release version、
  Approval、Remote operation、Deployment/service 唯一。
- FK、删除规则和 rollback self-reference 正确。
- passed/healthy/unhealthy/failed/rollback_requested 证据组合完整。

### 9.2 白盒/repository

- create/get/not found。
- `for_update` 行锁行为。
- scope 过滤与稳定分页。
- repository 不隐式推进状态。
- ORM metadata 与数据库反射一致。

### 9.3 并发

使用两个独立 PostgreSQL Session 确定性验证：

- 同 Candidate 创建 CIRun：仅一条成功。
- 同 Task/idempotency 创建 Deployment：仅一条成功。
- 同 Environment/release version 创建 Deployment：仅一条成功。
- 同 Deployment/service 创建 ServiceInstance：仅一条成功。
- 失败方命中预期唯一约束，不产生半写入。

### 9.4 Migration

- `upgrade head`
- `downgrade 20260716_0008`
- 验证三表和新增 Approval constraint 消失，旧表保留。
- 再次 `upgrade head`
- `alembic check` 无漂移。

### 9.5 契约与回归

- 三个共享 JSON Schema meta-validation。
- Pydantic/JSON Schema 精确一致。
- FastAPI OpenAPI 与共享 YAML 精确一致，且没有未实现路径。
- Platform API 全量 pytest。
- Workflow Engine 非集成与 WSL integration 回归。
- 其余 M1-M7 模块、Control Console、sample repo 按改动影响执行回归。

## 10. WSL 验证命令

```powershell
wsl -d Ubuntu-24.04 -u cloudhelm `
  --cd "/mnt/d/graduation project/modules/platform-api" -- `
  env `
  PATH=/home/cloudhelm/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin `
  UV_PROJECT_ENVIRONMENT=/home/cloudhelm/.cache/cloudhelm/platform-api-venv `
  CLOUDHELM_DATABASE_URL=postgresql+psycopg://cloudhelm:cloudhelm_dev@127.0.0.1:15432/cloudhelm `
  /home/cloudhelm/.local/bin/uv lock --check

wsl -d Ubuntu-24.04 -u cloudhelm `
  --cd "/mnt/d/graduation project/modules/platform-api" -- `
  env `
  PATH=/home/cloudhelm/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin `
  UV_PROJECT_ENVIRONMENT=/home/cloudhelm/.cache/cloudhelm/platform-api-venv `
  CLOUDHELM_DATABASE_URL=postgresql+psycopg://cloudhelm:cloudhelm_dev@127.0.0.1:15432/cloudhelm `
  /home/cloudhelm/.local/bin/uv run alembic upgrade head

wsl -d Ubuntu-24.04 -u cloudhelm `
  --cd "/mnt/d/graduation project/modules/platform-api" -- `
  env `
  PATH=/home/cloudhelm/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin `
  UV_PROJECT_ENVIRONMENT=/home/cloudhelm/.cache/cloudhelm/platform-api-venv `
  CLOUDHELM_DATABASE_URL=postgresql+psycopg://cloudhelm:cloudhelm_dev@127.0.0.1:15432/cloudhelm `
  /home/cloudhelm/.local/bin/uv run pytest -q

wsl -d Ubuntu-24.04 -u cloudhelm `
  --cd "/mnt/d/graduation project/modules/platform-api" -- `
  env `
  PATH=/home/cloudhelm/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin `
  UV_PROJECT_ENVIRONMENT=/home/cloudhelm/.cache/cloudhelm/platform-api-venv `
  CLOUDHELM_DATABASE_URL=postgresql+psycopg://cloudhelm:cloudhelm_dev@127.0.0.1:15432/cloudhelm `
  /home/cloudhelm/.local/bin/uv run alembic check
```

Migration 往返优先使用专用临时测试数据库，不破坏开发库。

## 11. 完成判定

- `20260716_0009` upgrade/downgrade/check 全通过。
- 三表 ORM、migration、Pydantic、共享 JSON Schema 和权威文档一致。
- 正负数据库约束、repository、并发和分页测试通过。
- WSL Platform API 全量回归通过。
- OpenAPI 没有新增未实现 endpoint。
- 没有生产事件、外部 handler、CI 或远端副作用被写成已交付。
- Roadmap 只勾选 CIRun/Deployment/ServiceInstance 数据与 migration。
- `PROJECT_PROGRESS.md` 记录命令、结果、风险和下一步。
- `PROJECT_PLAN.md` 滚动到 candidate ref 发布与唯一 Gitea CI 纵切。
- 复查 `git diff --stat`、关键 diff、`git diff --check` 后按可验证小步提交并 push
  当前功能分支。

## 12. 风险与处理

|风险|处理|
|---|---|
|旧简表与详细设计冲突|先同步最高层设计书、总表和逐表文档，再写 migration|
|把数据表误报为 CI/部署闭环|完成说明限定为 data foundation，API/worker/controller 保持未完成|
|跨表一致性无法靠 CHECK|本切片提供精确查询/锁；后续 service 在同事务重验|
|nullable external run 窗口导致重复|Candidate 与 Task idempotency 保持业务唯一，provider run 使用部分唯一索引|
|可变 tag 混入部署|只保存不可变 digest；tag 仅可作为 image ref 展示部分且必须带 digest|
|失败摘要泄露|只保存稳定 code 和有界脱敏 summary，契约拒绝 raw logs/token/credential|
|migration 污染开发数据|往返使用专用临时测试数据库，开发库只执行 upgrade/current/check|
|WSL PATH 缺少 user-local uv|所有 WSL 命令显式注入 `/home/cloudhelm/.local/bin`|
