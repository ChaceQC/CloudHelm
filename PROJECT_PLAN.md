# PROJECT_PLAN.md

本文件只记录当前下一步要落实的详细执行计划，不保存总项目规划。总流程和打钩
清单见 `docs/14-roadmap/03-implementation-milestone-flow.md`。

## 1. 当前执行指针

```text
M7 Ops Hub 常驻控制面、CI 与远端部署
  -> M7-2C Redis + Celery durable Workflow Engine
```

M7-2A 数据底座、M7-2B1 RepositoryBinding 和 M7-2B2 Candidate/第一道审批
已经完成。当前任务是让 PostgreSQL 中的 pending WorkflowJob 在 Desktop
`run-next` 之外由服务端 dispatcher/worker 持续推进，并完成首个真实
`release_candidate_reconcile` handler。

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
  - 严格 `{}` Candidate POST；首次 `201`、幂等 `200`
  - active-first Candidate GET
  - 第一道人工作为 L2 Approval
  - Candidate、Approval、pending reconcile WorkflowJob 和事件同事务创建
  - PR/Binding/request freshness、expiry、consumed 和实现 AgentRun 自批门禁
  - PostgreSQL `clock_timestamp()` 锁等待时间修复

### 2.2 当前环境

- 分支：`feature/m7-remote-deploy-closure`
- Alembic head：`20260716_0008`
- WSL：`Ubuntu-24.04`，发行版数据位于 `D:\WSL\Ubuntu-24.04`
- Docker：WSL 发行版内原生 Docker Engine/Compose
- PostgreSQL：Windows `127.0.0.1:15432`
- Redis：Windows `127.0.0.1:16379`
- Docker Desktop 已卸载，不作为开发或测试依赖

### 2.3 B2 收口证据

- Platform API：`308 passed, 1 skipped`
- B2 定向：`46 passed`
- 确定性 Binding PUT/Candidate POST 竞争连续 10 轮通过
- Orchestrator：`7 passed`
- Agent Runtime：`61 passed, 1 skipped`
- Tool Gateway：`45 passed, 1 skipped`
- Remote Agent：`31 passed, 2 skipped`
- Control Console：`17 passed`，production build 通过
- sample repo：`2 passed`，Bandit/pip-audit 通过

## 3. 本切片目标与裁剪线

### 3.1 必须完成

1. 建立独立 `modules/workflow-engine` Python 包和可复现依赖环境。
2. PostgreSQL `workflow_jobs` 保持业务权威；Celery message 只携带
   `workflow_job_id`。
3. 实现 durable dispatcher：
   - due scan
   - dispatch lease
   - publish success/failure finalize
   - enqueue backoff
   - Redis 丢消息后的周期补投
4. 实现 worker 生命周期：
   - claim
   - mark-running
   - heartbeat/lease
   - succeeded/failed/cancelled
   - retry
   - stale reclaim
5. 实现首个真实 `release_candidate_reconcile` handler。
6. Task pause/resume/cancel 与 WorkflowJob 状态联动。
7. 增加精确 workflow schema、事件 payload、测试和文档。
8. 使用 WSL 原生 PostgreSQL/Redis 完成真实集成验证。

### 3.2 本切片不做

- candidate ref push 或远端 SHA 复核。
- Gitea workflow dispatch、runner 或 registry。
- CIRun、Deployment、ServiceInstance。
- Release / Deploy Agent 和第二道部署审批。
- Deployment Controller、Remote Agent Compose operation。
- 外部副作用 handler 的真实 replay/resolver。
- 正式 Ops Hub TLS installation/bootstrap。

外部副作用分类只保留严格 policy/registry 结构，不写固定成功 handler。

## 4. 写代码前必须查阅

- `AGENTS.md`
- `docs/03-modules/modules/workflow-engine.md`
- `docs/07-data/tables/workflow_jobs.md`
- `docs/15-detailed-design/04-data-detail.md`
- `docs/15-detailed-design/05-workflow-state-events.md`
- `docs/15-detailed-design/09-m7-ci-remote-deployment-flow.md`
- `informations/m7-ci-remote-deploy/official-references.md`
- `informations/m7-ci-remote-deploy/reference-projects.md`
- Celery、redis-py、SQLAlchemy 和 PostgreSQL 官方文档

新增 Celery/Redis Python 依赖前必须确认官方支持版本，固定在独立
`pyproject.toml` 和 `uv.lock`，并把采用结论补充到 `informations/`。

## 5. 预检

### 5.1 Git 与工作区

```powershell
git branch --show-current
git status --short
git diff --check
```

只有 B2 已提交并 push 后才开始 Workflow Engine 代码提交。

### 5.2 WSL/PostgreSQL/Redis

```powershell
wsl -d Ubuntu-24.04 -- bash -lc @"
docker ps
docker exec cloudhelm-postgres-dev pg_isready -U cloudhelm -d cloudhelm
docker exec cloudhelm-redis-dev redis-cli ping
"@
```

预期：

```text
PostgreSQL accepting connections
Redis PONG
```

### 5.3 数据库

```powershell
cd modules/platform-api
$env:CLOUDHELM_DATABASE_URL='postgresql+psycopg://cloudhelm:cloudhelm_dev@127.0.0.1:15432/cloudhelm'
uv lock --check
uv run alembic current
uv run alembic check
```

## 6. 计划目录与文件

```text
modules/workflow-engine/
  pyproject.toml
  uv.lock
  README.md
  src/cloudhelm_workflow_engine/
    __init__.py
    config.py
    celery_app.py
    dispatcher.py
    worker_service.py
    handlers.py
    lease_heartbeat.py
    stale_reclaimer.py
    schemas.py
    errors.py
  tests/
    conftest.py
    test_config.py
    test_dispatcher.py
    test_claim_and_duplicate.py
    test_heartbeat.py
    test_worker_terminal.py
    test_reclaimer.py
    test_release_candidate_reconcile.py
    test_redis_restart_requeue.py
    test_task_pause_cancel.py

modules/platform-api/src/cloudhelm_platform_api/
  repositories/workflow_job_repository.py
  schemas/workflow_job.py
  services/release_candidate_reconcile_service.py

packages/shared-contracts/schemas/workflow/
  workflow-job.schema.json
```

需要同步：

```text
packages/shared-contracts/schemas/events/task-event.schema.json
modules/platform-api/README.md
modules/workflow-engine/README.md
docs/03-modules/modules/workflow-engine.md
docs/07-data/tables/workflow_jobs.md
docs/15-detailed-design/04-data-detail.md
docs/15-detailed-design/09-m7-ci-remote-deployment-flow.md
docs/14-roadmap/03-implementation-milestone-flow.md
PROJECT_PROGRESS.md
```

## 7. 实现任务

### 7.1 独立包和配置

- Workflow Engine 可以单向依赖 Platform API 的数据库模型/repository。
- Platform API 不得反向依赖 Workflow Engine，避免包循环。
- 配置使用 Pydantic Settings，至少包含：
  - database URL
  - broker URL
  - queue names
  - dispatch interval/batch/lease
  - worker lease/heartbeat
  - retry/enqueue backoff
  - soft/hard timeout
  - visibility timeout
- 校验：
  - `2 * heartbeat < worker lease`
  - `2 * publish timeout < dispatch lease`
  - `soft timeout < hard timeout < visibility timeout`
  - `visibility timeout >= hard timeout + worker lease`
- Celery 仅接受 JSON，`prefetch=1`、late ack、worker lost reject、ignore result。
- 禁止通用 autoretry 盲目重放业务 handler。

### 7.2 WorkflowJob repository

所有方法使用短 Session，按 `workflow_job.id` 稳定排序。

必须实现：

```text
reserve_due_jobs
finalize_dispatch_success
finalize_dispatch_failure
claim_job
mark_running
heartbeat
finish_succeeded
finish_failed
schedule_retry
request_cancel
reclaim_stale_jobs
```

due reserve：

```sql
tasks.status IN ('running', 'waiting_approval')
AND workflow_jobs.status = 'pending'
AND workflow_jobs.attempt < workflow_jobs.max_attempts
AND (next_retry_at IS NULL OR next_retry_at <= clock_timestamp())
AND next_enqueue_at <= clock_timestamp()
AND (
  dispatch_lease_expires_at IS NULL
  OR dispatch_lease_expires_at <= clock_timestamp()
)
ORDER BY next_enqueue_at, workflow_jobs.id
FOR UPDATE SKIP LOCKED
```

reserve 写 dispatch owner/expiry，并在 publish 前增加 `enqueue_attempt`。事务提交后
才调用 broker。

finalize 必须带：

```text
job id + status=pending + dispatch owner
```

worker 已 claim 时，旧 dispatcher finalize 必须 no-op。

### 7.3 Worker claim、lease 与 heartbeat

- claim 成功时：
  - `attempt += 1`
  - status -> `claimed`
  - 写 lease owner/expiry/heartbeat
  - 清 dispatch lease、next enqueue、next retry
- mark-running 使用独立事务：
  - Task paused：job 回 pending
  - Task terminal：job cancelled
  - 合法 Task：status -> running，首次写 `started_at`
- handler 期间不持有 Task/job 行锁。
- heartbeat 只允许当前 owner 更新 active lease。
- finish 只接受当前 owner；旧 owner 晚到结果 no-op。

锁等待后产生的 transition、lease、heartbeat、retry 和 finish 时间统一使用锁后
读取的一次 PostgreSQL `clock_timestamp()`。既有 migration 的 server default
继续保持 `0008` 定义，不修改历史 migration。

### 7.4 Retry 与 stale reclaim

- safe retry 只在 `attempt < max_attempts` 时回 pending。
- attempt 耗尽：
  - status -> failed
  - error code -> `workflow_job_attempts_exhausted`
  - 写 `finished_at`
  - 清两类 lease、retry/enqueue
- `side_effect_class=none`：
  - 未取消 stale active job -> pending
  - cancel_requested -> cancelled
- external 类型：
  - 本切片不执行真实 handler
  - unknown 必须进入 recovery_required
  - recovery_required 不自动重放

### 7.5 release_candidate_reconcile

输入固定：

```json
{
  "schema_version": "m7.release-candidate-reconcile.payload.v1",
  "candidate_id": "UUID",
  "approval_id": "UUID",
  "expected_candidate_request_hash": "sha256:<64 hex>",
  "expected_binding_snapshot_sha256": "sha256:<64 hex>",
  "expected_pull_request_record_id": "UUID"
}
```

锁序：

```text
Task
  -> WorkflowJob
  -> ProjectRepositoryBinding
  -> ReleaseCandidate
  -> Approval
```

分支：

- pending/approved 且 freshness 一致：`succeeded + valid`
- PR、Binding、hash、expiry 或 consumed 漂移：
  - Candidate -> stale
  - 只有 pending Approval -> expired
  - job -> `succeeded + stale`
- rejected/published/stale/cancelled：`succeeded + terminal_noop`
- Approval 缺失或状态组合异常：
  `failed + release_candidate_approval_state_invalid`
- transient DB error：按 retry policy 回排

handler 不调用 Git、HTTP、Docker、Gitea、CI 或 Remote Agent。

### 7.6 Task pause/resume/cancel

- pause：dispatcher 不再 reserve 新 job；已 running job 保留可审计状态。
- resume：pending job 的 `next_enqueue_at` 推进到数据库当前时间。
- cancel：
  - pending -> cancelled
  - claimed 且 handler 未开始 -> cancelled
  - running -> cancel_requested
- Task 与 job 写操作先锁 Task，再按 job UUID 升序锁定。

### 7.7 契约和事件

新增严格 `workflow-job.schema.json`，payload/result：

- 所有必填字段明确。
- `additionalProperties=false`。
- hash、UUID、时间、状态枚举使用固定格式。
- broker payload 只允许 `workflow_job_id`，不得包含 credential、clone URL、
  profile、环境变量或业务正文。

事件至少包含：

```text
WorkflowJobStarted
WorkflowJobSucceeded
WorkflowJobRetryScheduled
WorkflowJobCancelled
WorkflowJobRecoveryRequired
WorkflowJobDispatchDeferred
```

每种事件使用精确 payload allowlist。

## 8. 黑盒与白盒测试

### 8.1 配置

- 默认值和环境变量覆盖。
- 时间不变量非法时启动失败。
- broker message 不包含业务 payload/secret。

### 8.2 Dispatcher

- due/未到期/暂停/终态 Task 过滤。
- 批量、顺序和 `SKIP LOCKED`。
- reserve 后 publish 前崩溃。
- publish 后 finalize 前崩溃。
- publish 成功但消息丢失。
- dispatch failure backoff 和错误码。

### 8.3 Worker

- 重复 message 与并发 claim 只有一个成功。
- claim、mark-running、heartbeat 和 terminal。
- owner 不匹配和 lease 过期。
- 旧 owner late result no-op。
- worker kill 后 stale reclaim。
- attempt exhausted。

### 8.4 Reconcile

- valid。
- PR drift。
- Binding snapshot/hash drift。
- request hash drift。
- Approval expired/consumed。
- rejected/published/stale/cancelled terminal_noop。
- Approval 缺失/非法状态组合。
- transient DB error retry。

### 8.5 Task 生命周期

- pause/dispatch 竞争。
- resume 推进 pending job。
- cancel/claim 竞争。
- running cancel_requested。

### 8.6 WSL 真实集成

1. 启动 PostgreSQL/Redis。
2. 通过 Candidate API 创建 pending reconcile job。
3. 启动 dispatcher/worker。
4. 验证 job 自动 succeeded。
5. 停止 Redis，创建新 pending job。
6. 恢复 Redis。
7. 验证 PostgreSQL dispatcher 补投，且没有重复副作用。

## 9. 验证命令

```powershell
wsl -d Ubuntu-24.04 -- bash -lc @"
docker exec cloudhelm-redis-dev redis-cli ping
docker exec cloudhelm-postgres-dev pg_isready -U cloudhelm -d cloudhelm
"@

cd modules/workflow-engine
uv lock --check
uv run pytest -q

cd ../platform-api
$env:CLOUDHELM_DATABASE_URL='postgresql+psycopg://cloudhelm:cloudhelm_dev@127.0.0.1:15432/cloudhelm'
uv lock --check
uv run alembic current
uv run alembic check
uv run pytest -q

cd ../../apps/control-console
npm.cmd test
npm.cmd run build

cd ../..
git diff --check
git status --short
```

还必须执行：

- 全部 JSON Schema meta-validation。
- FastAPI OpenAPI 与共享 YAML 精确一致。
- UTF-8/BOM、Markdown 相对链接、敏感信息和文件体量检查。
- dispatcher/claim/reclaim 并发文件连续多轮。

## 10. 完成判定

- API 创建的 pending reconcile job 无需 Desktop `run-next` 即可由 dispatcher
  投递、worker claim 并收敛到正确终态。
- Celery 重复消息和并发 worker 只有一个有效 claim。
- Redis 重启后 PostgreSQL pending job 自动补投。
- worker hard crash 后 `none` job 按 lease/stale 规则安全回排。
- Task pause/resume/cancel 与 WorkflowJob 状态一致。
- `release_candidate_reconcile` 所有分支有真实 PostgreSQL 测试。
- Workflow Engine、Platform API、共享契约、前端和 WSL 集成全部通过。
- README、详细设计、Roadmap、`PROJECT_PROGRESS.md` 和 Git commit/push 同步。

## 11. 风险与处理

|风险|处理|
|---|---|
|Platform API 与 Workflow Engine 循环依赖|只允许 Workflow Engine 单向依赖 Platform API persistence；API 只落 PostgreSQL job|
|把 Redis 当业务权威|所有状态、lease、attempt、结果与错误只写 PostgreSQL|
|事务 `now()` 在锁等待后倒挂|transition/lease/heartbeat/finish 使用锁后单次 `clock_timestamp()`|
|重复消息产生重复执行|数据库 claim + owner/lease 条件更新|
|publish crash window 丢 job|dispatch lease + `next_enqueue_at` 周期补投|
|worker 崩溃后盲目重放|按 side-effect class reclaim；unknown external -> recovery_required|
|把空 handler 写成完成|本切片只实现真实 reconcile handler，其余 handler 不注册|
|WSL 开发基线被写成正式 Ops Hub|只记录 IT-031A；正式 installation/IT-031B 继续未完成|
