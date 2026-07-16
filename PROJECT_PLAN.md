# PROJECT_PLAN.md

本文件只记录当前下一步要落实的详细执行计划，不保存总项目规划。总流程和打钩
清单见 `docs/14-roadmap/03-implementation-milestone-flow.md`。

## 1. 当前执行指针

```text
M7 Ops Hub 常驻控制面、CI 与远端部署
  -> M7-2E 受控 candidate ref 与唯一 Gitea workflow dispatch
```

M7-2D 已完成 CIRun、Deployment、ServiceInstance 数据底座。当前切片把第一道
L2 Approval 后的 continuation 变成真实、可恢复的服务端外部流程：

```text
approved ReleaseCandidate
  -> publish exact commit to controlled candidate ref
  -> git ls-remote --refs verifies exact SHA
  -> create authoritative triggered CIRun
  -> dispatch one fixed Gitea workflow with return_run_details=true
  -> persist external_run_id and exact provider identity
```

当前版本继续保持 `0.5.1`；完整 M7 CI、制品、ReleasePlan、第二道审批和远端部署
E2E 收口时再发布 `0.6.0`。

## 2. 已确认基线

### 2.1 已交付能力

- M1-M6 本地需求、设计、实现、测试、安全和等价 PR 闭环。
- M7-1 Environment、RemoteTarget、machine authentication 与 heartbeat。
- M7-2A：
  - RepositoryBinding、ReleaseCandidate、WorkflowJob 数据底座。
  - 资源型 Approval 字段、唯一键和状态约束。
- M7-2B1：
  - server-controlled RepositoryProfile。
  - Project RepositoryBinding PUT/GET、幂等与漂移失效。
- M7-2B2：
  - 严格 `{}` Candidate POST。
  - 第一道人工作为 L2 Approval。
  - Candidate、Approval、reconcile WorkflowJob 和事件同事务创建。
  - PR/Binding/request freshness、expiry、consumed 和自批门禁。
- M7-2C：
  - PostgreSQL 权威 Redis + Celery durable Workflow Engine。
  - dispatcher/claim/lease/heartbeat/retry/reclaim 和 Task 生命周期联动。
  - `release_candidate_reconcile -> release_candidate -> none` 真实 handler。
- M7-2D：
  - `ci_runs`、`deployments`、`service_instances`。
  - `20260716_0009` migration、ORM、repository、严格 Record/JSON Schema。
  - 第二道 deployment Approval 数据库组合。
  - SQL 三值逻辑、健康数据安全、部分唯一、真实行锁和 migration 往返。

### 2.2 当前环境

- 分支：`feature/m7-remote-deploy-closure`
- Alembic head：`20260716_0009`
- WSL：`Ubuntu-24.04`
- Docker：WSL 发行版内原生 Docker Engine/Compose
- PostgreSQL：`127.0.0.1:15432`
- Redis：`127.0.0.1:16379`
- Platform API WSL venv：
  `/home/cloudhelm/.cache/cloudhelm/platform-api-venv`
- Workflow Engine WSL venv：
  `/home/cloudhelm/.cache/cloudhelm/workflow-engine-venv`
- Docker Desktop 不作为开发、测试或正式 Desktop 安装依赖。

## 3. 本切片目标与裁剪线

### 3.1 必须完成

1. 冻结 Approval 后 continuation、两个 external WorkflowJob、payload/result、
   side-effect class、锁序、事件和恢复契约。
2. 新增 `20260716_0010`，只扩展 M7 handler CHECK；不修改历史 `0008/0009`。
3. Approval 成功后原子创建唯一 `release_candidate_publish` WorkflowJob。
4. 实现受控本地 commit 解析、无 force 的精确 ref push 和
   `git ls-remote --refs` SHA 回读。
5. publish handler 成功后在同一 PostgreSQL 事务：
   - 标记 Candidate `published`。
   - 写 `remote_verified_sha/published_at`。
   - 消费第一道 Approval。
   - 创建唯一 triggered CIRun。
   - 创建唯一 `ci_workflow_dispatch` WorkflowJob。
6. 实现固定 Gitea workflow dispatch：
   - 固定 owner/repository/workflow/ref。
   - 固定 `return_run_details=true`。
   - 响应必须具有 `workflow_run_id`。
   - 回读 run，精确验证 repository、event、workflow path、head ref 和 head SHA。
7. 将真实 `external_run_id`、provider head/time 写入 CIRun；不等待 CI 完成。
8. 对 publish/dispatch 的网络中断和 hard crash 实现 fail-closed resolver：
   - 已存在同 SHA ref 视为幂等 publish 成功。
   - ref 指向其他 SHA 时禁止 force push。
   - dispatch response 丢失时只查询并绑定唯一精确 run。
   - 0 条或多条无法唯一证明时进入 `recovery_required`，不得重复 dispatch。
9. 使用 WSL 隔离 Gitea Compose fixture 完成真实 push、ls-remote、dispatch、
   run 查询和崩溃恢复测试。
10. 同步 Tool schema、Workflow schema、事件 schema、模块文档、测试矩阵、
    Roadmap、`PROJECT_PROGRESS.md` 和下一阶段 `PROJECT_PLAN.md`。

### 3.2 本切片不做

- 不等待 runner 完成 workflow。
- 不解析 job、log、JUnit、security、SBOM、provenance 或 OCI digest。
- 不实现 CI webhook。
- 不生成 ReleasePlan。
- 不新增第二道 Approval HTTP API。
- 不实现 Release / Deploy Agent。
- 不调用 Deployment Controller、Remote Agent 或 Docker Compose。
- 不实现 registry push、artifact download 或远端部署。
- 不新增 Control Console CI/部署页面。
- 不建立正式 Ops Hub installation/bootstrap。

本切片完成边界只允许声明：

```text
controlled candidate ref
+ exact remote SHA verification
+ one fixed workflow_dispatch
+ authoritative CIRun run identity
```

## 4. 必须先冻结的设计

### 4.1 两段 external WorkflowJob

外部副作用拆成两个独立 job，避免一次 handler 同时混合 Git 可幂等写入与 CI
不确定写入：

```text
release_candidate_publish
  resource_type = release_candidate
  side_effect_class = external_idempotent

ci_workflow_dispatch
  resource_type = ci_run
  side_effect_class = external_uncertain
```

禁止把两步合并为一个 job；否则 push 已成功、dispatch 未开始或 dispatch response
丢失时无法使用现有 recovery policy 精确收敛。

### 4.2 Approval 后 continuation

第一道 Approval 决策成功时，在原有 Task/Candidate/Approval 锁内：

1. 重新执行 PR、Binding、request hash、expiry、自批和状态 freshness。
2. 将 Candidate 从 `pending_approval` 更新为 `approved`。
3. 将 Approval 更新为 `approved`，但此时不写 `consumed_at`。
4. 创建唯一 pending `release_candidate_publish` job。
5. 写 `WorkflowJobQueued` 与
   `ReleaseCandidatePublishQueued` 低敏事件。
6. 同一事务提交，不在 HTTP 请求中执行 Git 或 HTTP。

重复 approve 必须返回现有终态和现有 publish job，不创建第二个 job。

### 4.3 publish payload/result

payload：

```json
{
  "schema_version": "m7.release-candidate-publish.payload.v1",
  "candidate_id": "UUID",
  "approval_id": "UUID",
  "repository_binding_id": "UUID",
  "expected_candidate_request_hash": "sha256:<64 lowercase hex>",
  "expected_binding_snapshot_sha256": "sha256:<64 lowercase hex>",
  "expected_pull_request_record_id": "UUID",
  "expected_commit_sha": "<40 or 64 lowercase hex>",
  "expected_target_ref": "refs/heads/cloudhelm/release-candidates/..."
}
```

result：

```json
{
  "schema_version": "m7.release-candidate-publish.result.v1",
  "outcome": "published | already_published",
  "candidate_id": "UUID",
  "target_ref": "refs/heads/...",
  "remote_verified_sha": "<full SHA>",
  "published_at": "RFC3339 UTC date-time",
  "ci_run_id": "UUID",
  "dispatch_job_id": "UUID"
}
```

payload/result 全字段 required、`additionalProperties=false`，不得包含 workspace
绝对路径、clone URL、credential ref、username、token、命令行或原始 stderr。

### 4.4 dispatch payload/result

payload：

```json
{
  "schema_version": "m7.ci-workflow-dispatch.payload.v1",
  "ci_run_id": "UUID",
  "release_candidate_id": "UUID",
  "repository_binding_id": "UUID",
  "provider": "gitea",
  "repository_external_id": "<stable id>",
  "workflow_id": ".gitea/workflows/cloudhelm-release.yml",
  "workflow_revision": "sha256:<workflow file bytes>",
  "source_ref": "refs/heads/...",
  "commit_sha": "<40 or 64 lowercase hex>"
}
```

result：

```json
{
  "schema_version": "m7.ci-workflow-dispatch.result.v1",
  "outcome": "dispatched | recovered_existing",
  "ci_run_id": "UUID",
  "external_run_id": "<decimal provider run id>",
  "workflow_id": ".gitea/workflows/cloudhelm-release.yml",
  "source_ref": "refs/heads/...",
  "commit_sha": "<full SHA>",
  "provider_status": "<bounded Gitea run status>",
  "provider_updated_at": "RFC3339 UTC date-time"
}
```

### 4.5 workflow revision

`workflow_revision` 的权威来源固定为：

```text
sha256:<lowercase SHA-256 of exact workflow file bytes at commit_sha>
```

handler 使用：

```text
git show <commit_sha>:<workflow_id>
```

读取文件，并在 dispatch 前验证：

- 文件存在且 UTF-8/YAML 可解析。
- `on.workflow_dispatch` 存在。
- 不监听 `push`。
- M7-2E fixture workflow 不含 SSH、Compose、Remote Agent 或部署命令。

本切片不自研完整 workflow 静态分析器；只冻结上述高风险裁剪门禁。

### 4.6 Git publish 契约

workspace 由服务端使用 Task ID 和既有 `LocalWorkspaceResolver` 派生，payload 不
携带路径。publish adapter 固定执行：

```text
git cat-file -e <commit_sha>^{commit}
git rev-parse <commit_sha>^{commit}
git ls-remote --refs <controlled-remote> <target_ref>
git push <controlled-remote> <commit_sha>:<target_ref>
git ls-remote --refs <controlled-remote> <target_ref>
```

规则：

- remote、clone URL、target ref 均来自锁后重验的 Binding/Profile/Candidate。
- 禁止 `--force`、`--force-with-lease`、`--all`、`--mirror`、tag 和隐式 refspec。
- remote ref 缺失才允许 push。
- remote ref 已存在且 SHA 相同返回 `already_published`。
- remote ref 已存在且 SHA 不同返回稳定失败
  `release_candidate_ref_conflict`，不修改远端。
- push 返回成功后仍必须以 `ls-remote --refs` 的完整 SHA 为准。

### 4.7 Gitea dispatch 契约

固定调用：

```text
POST /api/v1/repos/{owner}/{repo}/actions/workflows/{workflow_id}/dispatches
  ?return_run_details=true
```

body：

```json
{
  "ref": "refs/heads/...",
  "inputs": {
    "cloudhelm_ci_run_id": "UUID",
    "cloudhelm_release_candidate_id": "UUID"
  }
}
```

只接受 `200` 与严格 RunDetails：

```json
{
  "workflow_run_id": 123,
  "run_url": "...",
  "html_url": "..."
}
```

`204`、缺少 run ID、非整数 run ID、redirect、非同源 URL 或额外不受控响应均视为
provider contract failure。run URL 只用于同源校验，不写 CIRun/EventLog。

随后调用：

```text
GET /api/v1/repos/{owner}/{repo}/actions/runs/{workflow_run_id}
```

并验证：

- repository id 等于 Binding `repository_external_id`。
- `event=workflow_dispatch`。
- `path=workflow_id`。
- `head_branch` 对应受控 candidate ref。
- `head_sha=commit_sha`。
- run id 与 dispatch response 完全一致。

### 4.8 dispatch 崩溃与 resolver

正常路径使用 `return_run_details=true` 直接取得 run id。若请求可能已发送但
response/DB commit 丢失：

1. resolver 查询 repository runs：

```text
GET /api/v1/repos/{owner}/{repo}/actions/runs
  ?event=workflow_dispatch
  &branch=<candidate branch>
  &head_sha=<commit sha>
```

2. 再本地过滤：
   - workflow path。
   - repository id。
   - head branch/head SHA。
   - `started_at >= ci_runs.created_at - bounded_clock_skew`。
3. 恰好一条匹配：写 `external_run_id`，结果为 `recovered_existing`。
4. 0 条或多条：job 进入 `recovery_required`，不重复 dispatch。

通用 worker 不对 `external_uncertain` 自动盲重试；只有上述 resolver 能把精确唯一
外部事实收敛为成功。

### 4.9 凭据与私有配置

- Binding 继续保存服务端 `profile_key/clone_url/credential_ref/workflow_id`。
- 普通 API、payload/result/EventLog/ToolCall 摘要不返回私有配置。
- `RepositoryProfileProvider` 锁后重新加载 profile，并要求与 Binding 完全一致。
- Gitea API base 从受控 HTTPS clone URL 的同源 origin 派生：
  `https://host[:port]/api/v1`。
- repository credential 使用严格内部结构解析：

```json
{
  "username": "<service account>",
  "token": "<secret>"
}
```

- API 使用 `Authorization: token <secret>` header。
- Git HTTPS 使用临时环境/askpass 或等价不会把凭据写入 argv、remote、日志和
  文件的机制；子进程结束后清除。
- HTTP client 固定 `trust_env=false`、TLS 校验、禁止 redirect、明确
  connect/read/write/pool timeout 和响应字节上限。

### 4.10 锁序与事务

publish handler 锁序：

```text
Task
-> WorkflowJob
-> RepositoryBinding
-> ReleaseCandidate
-> Approval
-> PullRequestRecord
```

外部 Git 操作前的短事务只完成 claim、锁后重验和安全快照；不得持有数据库行锁
等待 Git 网络。外部操作完成后，finalize 事务按相同资源顺序重验 snapshot/hash/
status，再写 Candidate/Approval/CIRun/dispatch job/event。

dispatch handler 锁序：

```text
Task
-> WorkflowJob
-> CIRun
-> ReleaseCandidate
-> RepositoryBinding
```

HTTP 外部调用同样不持有数据库行锁。finalize 必须验证 claim token、lease、
request hash、run identity 和当前 Task 状态。

## 5. 实现前必须查阅

- `AGENTS.md`
- `PROJECT_PROGRESS.md`
- `docs/15-detailed-design/00-mvp-scope-and-cutline.md`
- `docs/15-detailed-design/01-module-contracts.md`
- `docs/15-detailed-design/04-data-detail.md`
- `docs/15-detailed-design/05-workflow-state-events.md`
- `docs/15-detailed-design/07-testing-acceptance-matrix.md`
- `docs/15-detailed-design/09-m7-ci-remote-deployment-flow.md`
- `docs/05-tool-layer/tools/git-tool.md`
- `docs/05-tool-layer/tools/ci-tool.md`
- `docs/06-workflows/01-pr-to-remote-deploy.md`
- `docs/07-data/tables/{release_candidates,ci_runs,workflow_jobs}.md`
- `informations/m7-ci-remote-deploy/official-references.md`
- Gitea 1.26.4 API/source、Git、HTTPX、Celery、PostgreSQL 和 Pydantic 官方资料。

外部资料采用结论必须先写入
`informations/m7-ci-remote-deploy/official-references.md`；如当前 Gitea fixture
不支持 `return_run_details=true`，先调整版本门禁和计划，不写兼容猜测。

## 6. 预检

### 6.1 Git 与工作区

```powershell
git branch --show-current
git status --short
git diff --stat
git diff --check
git log --oneline --decorate -5
```

必须位于 `feature/m7-remote-deploy-closure`；禁止在 `main` 修改。

### 6.2 WSL Ops Hub 基线

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

预期：PostgreSQL accepting connections、Redis PONG、uv 可用。

### 6.3 数据库与 M7-2D 回归

```powershell
wsl -d Ubuntu-24.04 -u cloudhelm `
  --cd "/mnt/d/graduation project/modules/platform-api" -- `
  env `
  PATH=/home/cloudhelm/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin `
  UV_PROJECT_ENVIRONMENT=/home/cloudhelm/.cache/cloudhelm/platform-api-venv `
  CLOUDHELM_DATABASE_URL=postgresql+psycopg://cloudhelm:cloudhelm_dev@127.0.0.1:15432/cloudhelm `
  /home/cloudhelm/.local/bin/uv run alembic current
```

预期：`20260716_0009 (head)`。

### 6.4 Gitea fixture 预检

- 确认 WSL Docker 可拉取固定 Gitea 1.26.4 image。
- 使用独立 Compose project、network、volume 和端口。
- 不能复用正式或开发中的真实 Gitea 数据。
- fixture 的用户名、密码和 token 都是测试专用固定/随机值，不进入 Git。
- 测试结束必须删除容器、network 和 volume。

## 7. 计划文件

```text
modules/platform-api/
  migrations/versions/
    20260716_0010_create_m7_candidate_publish_ci_dispatch.py
  src/cloudhelm_platform_api/
    models/workflow_job.py
    schemas/workflow_job.py
    schemas/event_log.py
    services/
      release_candidate_approval_service.py
      release_candidate_publish_prepare.py
      release_candidate_publish_finalize.py
      ci_dispatch_prepare.py
      ci_dispatch_finalize.py
    repositories/
      release_candidate_repository.py
      ci_run_repository.py
      workflow_job_repository.py
    core/repository_config.py
    providers/repository_profile_provider.py
  tests/
    test_m7_candidate_publish_contracts.py
    test_m7_candidate_publish_service.py
    test_m7_ci_dispatch_contracts.py
    test_m7_ci_dispatch_service.py
    test_m7_external_job_constraints.py
    test_m7_external_job_concurrency.py

modules/workflow-engine/
  src/cloudhelm_workflow_engine/
    adapters/
      controlled_git.py
      gitea_actions.py
    handlers/
      release_candidate_publish.py
      ci_workflow_dispatch.py
    resolvers/
      ci_workflow_dispatch.py
    registry.py
    worker_factory.py
    config.py
    schemas.py
  tests/
    test_controlled_git_adapter.py
    test_gitea_actions_adapter.py
    test_release_candidate_publish_handler.py
    test_ci_workflow_dispatch_handler.py
    test_ci_workflow_dispatch_resolver.py

modules/tool-gateway/
  src/cloudhelm_tool_gateway/
    schemas/git.py
    schemas/ci.py
    tools/git_tool.py
    tools/ci_tool.py
    tools/__init__.py
  tests/
    test_git_tool.py
    test_ci_tool.py

packages/shared-contracts/schemas/
  workflow/workflow-job.schema.json
  events/task-event.schema.json
  tools/git-tool.schema.json
  tools/ci-tool.schema.json

infra/testing/gitea-actions/
  docker-compose.yml
  README.md
  fixtures/
    cloudhelm-release.yml
  scripts/
    prepare_fixture.py
    cleanup_fixture.py
```

同步：

```text
informations/m7-ci-remote-deploy/official-references.md
docs/05-tool-layer/tools/{git-tool,ci-tool}.md
docs/06-workflows/01-pr-to-remote-deploy.md
docs/07-data/tables/{release_candidates,ci_runs,workflow_jobs}.md
docs/15-detailed-design/{01-module-contracts,04-data-detail,
05-workflow-state-events,07-testing-acceptance-matrix,
09-m7-ci-remote-deployment-flow}.md
modules/{platform-api,workflow-engine,tool-gateway}/README.md
packages/shared-contracts/README.md
docs/14-roadmap/03-implementation-milestone-flow.md
PROJECT_PROGRESS.md
```

## 8. 实现任务

### 8.1 文档与资料冻结

- 归档 Gitea 1.26.4 `return_run_details`、RunDetails、run query filter 和 run schema。
- 更新 Git Tool 文档，增加内部受控 publish/verify，不开放任意 push API。
- 更新 CI Tool 文档，增加固定 workflow dispatch/get run，不开放任意 owner/repo/
  workflow/ref。
- 冻结两个 job 的 payload/result、side-effect class、事件和 recovery。
- 明确 M7-2E 不等待 CI 成功、不生成 artifact/digest。

### 8.2 Migration 与 ORM

- revision：`20260716_0010`
- down revision：`20260716_0009`
- 只 drop/recreate `ck_workflow_jobs_m7_2_handler`：

```text
release_candidate_reconcile -> release_candidate -> none
release_candidate_publish   -> release_candidate -> external_idempotent
ci_workflow_dispatch        -> ci_run -> external_uncertain
```

- 不修改历史 `0008/0009`。
- downgrade 恢复只有 reconcile 的旧 CHECK。
- ORM metadata 与 migration 精确一致。
- migration 往返测试：
  `0009 -> head -> 0009 -> head/check`。

### 8.3 Approval continuation

- 扩展 release candidate approval service。
- approve 事务原子创建 publish job 和队列事件。
- reject 不创建 external job。
- 重复/并发 approve 只保留一个 publish job。
- Task paused/cancelled、Approval expiry、PR/Binding/hash 漂移继续 fail closed。

### 8.4 Tool/adapter

- Git adapter 使用参数数组、固定环境、超时、进程树清理和有界摘要。
- Git adapter 不返回命令行、remote URL 或 credential。
- Gitea adapter 使用严格 Pydantic request/response。
- HTTP client 禁 redirect、`trust_env=false`、TLS 校验、四类 timeout 和连接池。
- Tool Gateway registry 固定内部工具名、风险和允许调用角色。
- workflow handler 只能调用固定 adapter/tool method，不拼接任意命令或 URL。

### 8.5 publish handler

- prepare 事务锁后读取并返回不可变安全快照。
- 外部阶段解析本地 commit、检查 workflow 文件、查询/推送/回读 remote ref。
- finalize 事务重验 Task/job/candidate/approval/binding/PR。
- 原子：
  - Candidate published。
  - Approval consumed。
  - CIRun triggered。
  - dispatch job pending。
  - publish job succeeded。
  - 写低敏事件。
- finalize 前崩溃时由 ref resolver 收敛，不重复 push。

### 8.6 dispatch handler

- prepare 事务锁后读取 CIRun/Candidate/Binding/Profile 快照。
- 调用固定 dispatch endpoint，必须请求 run details。
- 获取 run 后立即 GET 回读并精确校验。
- finalize 更新 CIRun external run identity/provider evidence，job succeeded。
- response 丢失时调用 resolver；无法唯一证明则 recovery_required。
- 同一 Candidate、CIRun 或 dispatch job 并发 delivery 不得产生第二个 dispatch。

### 8.7 事件与共享契约

新增或冻结：

```text
ReleaseCandidatePublishQueued
ReleaseCandidatePublished
CIRunTriggered
CIRunRunIdentityBound
WorkflowJobRecoveryRequired
```

事件 payload 只包含 UUID、状态、受控 ref、完整 SHA、provider/run identity 和
稳定 error code；不包含 URL、profile、credential、token、命令或原始输出。

### 8.8 WSL Gitea fixture

- 独立 Compose project，例如 `cloudhelm-m7-ci-fixture`。
- 固定 Gitea `1.26.4` image，不使用 `latest`。
- 初始化测试 admin/service account 和测试仓库。
- seed workflow 只包含 `workflow_dispatch`，不监听 push。
- 不启动 runner；本切片只验证 run 创建与 identity。
- 从 WSL 创建本地 Git fixture commit，执行真实 publish/dispatch。
- 测试结束删除 Compose project、network、volume 和临时目录。

## 9. 测试矩阵

### 9.1 黑盒/外部行为

- Approval approve 后自动创建唯一 publish job，HTTP 请求不执行外部操作。
- remote ref 不存在：push 一次，回读 SHA 相同。
- remote ref 已存在且 SHA 相同：幂等成功，无第二次 push。
- remote ref 已存在且 SHA 不同：稳定冲突，无 force。
- dispatch 使用固定 endpoint/workflow/ref/inputs。
- `return_run_details=true` 返回 run id，并能 GET 精确回读。
- Gitea 204、缺 run id、run identity 漂移、redirect、超大响应稳定失败。
- 同 Candidate/CIRun 重复消息只产生一个 remote ref 和一个 workflow run。

### 9.2 白盒/事务与锁

- Approval/Candidate/publish job 同事务。
- publish finalize 的 Candidate/Approval/CIRun/dispatch job/event 同事务。
- dispatch finalize 的 CIRun/job/event 同事务。
- Task cancel/pause 与 external finalize 竞争时 Task 状态优先。
- PR、Binding snapshot/hash、profile、commit、ref、workflow 漂移全部拒绝。
- payload/result Pydantic、共享 JSON Schema、数据库 CHECK 精确一致。

### 9.3 崩溃恢复

- push 成功后、finalize 前崩溃：`ls-remote` 收敛为 already published。
- dispatch 成功后、response/commit 前崩溃：resolver 绑定唯一 run。
- resolver 0 条：recovery_required，不重复 dispatch。
- resolver 多条：recovery_required，不猜测。
- external handler 超时、worker SIGKILL、lease 过期不进入通用盲重放。

### 9.4 Migration

- `upgrade head`
- `downgrade 20260716_0009`
- 旧三表与 M7-2D Approval constraint 保留。
- 新 handler CHECK 恢复为只允许 reconcile。
- 再次 `upgrade head`
- `alembic check` 无漂移。

### 9.5 回归

- Platform API 全量 pytest。
- Workflow Engine 非 integration 全量。
- Workflow Engine Redis restart/prefork hard-crash integration。
- Tool Gateway 全量。
- M7-2D 定向与 migration 往返。
- OpenAPI/JSON Schema meta-validation。
- UTF-8/BOM、Markdown 链接、JSON、敏感信息和 `git diff --check`。

## 10. WSL 验证命令

### 10.1 Platform API

```powershell
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
```

### 10.2 Workflow Engine

```powershell
wsl -d Ubuntu-24.04 -u cloudhelm `
  --cd "/mnt/d/graduation project/modules/workflow-engine" -- `
  env `
  PATH=/home/cloudhelm/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin `
  UV_PROJECT_ENVIRONMENT=/home/cloudhelm/.cache/cloudhelm/workflow-engine-venv `
  CLOUDHELM_DATABASE_URL=postgresql+psycopg://cloudhelm:cloudhelm_dev@127.0.0.1:15432/cloudhelm `
  CLOUDHELM_REDIS_URL=redis://127.0.0.1:16379/0 `
  /home/cloudhelm/.local/bin/uv run pytest -q
```

### 10.3 Gitea integration

具体命令由 `infra/testing/gitea-actions/README.md` 固化，必须：

```text
compose up
-> fixture prepare
-> real publish/ls-remote/dispatch/run query tests
-> compose down -v
```

无论测试成功或失败都必须执行 cleanup。

## 11. 完成判定

- `20260716_0010` upgrade/downgrade/check 全通过。
- Approval 后唯一 publish job 自动 continuation。
- 真实 WSL Gitea 完成 exact ref push、SHA 回读和唯一 dispatch。
- CIRun 保存真实 external run identity，commit/ref/workflow/repository 精确匹配。
- push/dispatch crash recovery 不重复外部副作用。
- external uncertainty 无法唯一证明时进入 recovery_required。
- payload/result/event/ToolCall 不泄露 URL、credential、token、命令或原始输出。
- Platform API、Workflow Engine、Tool Gateway 与 M7-2D 回归通过。
- Roadmap 只勾选 M7-2E 对应受控 ref/唯一 dispatch/run identity，不把 CI 成功、
  artifact、ReleasePlan 或远端部署写成已完成。
- `PROJECT_PROGRESS.md` 记录真实命令、结果、失败闭环和遗留风险。
- `PROJECT_PLAN.md` 滚动到 CI run/job/artifact/OCI digest 收敛。
- 复查 Git diff 后按可验证小步 commit，并立即 push 当前功能分支。

## 12. 风险与处理

|风险|处理|
|---|---|
|把 push 成功等同于远端 ref 正确|每次都执行 `git ls-remote --refs` 并比较完整 SHA|
|remote ref 已存在但指向其他 SHA|稳定冲突，禁止任何 force push|
|dispatch API 不返回 run id|固定 Gitea 1.26.4+ `return_run_details=true`，否则 provider contract failure|
|dispatch response 丢失后重复触发|resolver 只绑定唯一精确 run；0/多条进入 recovery_required|
|Git/HTTP 操作期间持有数据库锁|prepare/finalize 短事务，中间外部调用不持锁|
|profile 或 credential 漂移|锁后重验 Binding/Profile，私有配置不进入 payload/result|
|凭据出现在 argv/日志|使用临时环境/askpass，审计只保留低敏摘要|
|测试 Gitea 污染开发依赖|独立 Compose project/network/volume/port，finally cleanup|
|无 runner 导致 run 不完成|本切片只验 run 创建/identity，CI completion 属于下一切片|
|把 M7-2E 误报为完整 CI|完成说明限定为 ref + SHA + unique dispatch + run identity|
