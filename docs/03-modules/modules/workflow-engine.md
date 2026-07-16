# modules/workflow-engine

> 来源：[设计书 7.1-7.2](../../../云舵 CloudHelm 毕设设计书.md)  
> 层级：`modules/workflow-engine`

## 当前实现状态

M7-2C 已创建独立 `modules/workflow-engine` 包并固定 Celery `5.6.3`、
Kombu `5.6.2`、redis-py `6.4.0`。当前已实现：

- PostgreSQL due scan、dispatch lease、publish success/failure finalize、
  enqueue backoff 与周期 redispatch。
- Celery JSON message、late ack、prefetch=1、worker claim、mark-running、
  heartbeat、terminal、safe retry 与 stale reclaim。
- Task pause/resume/cancel 联动。
- 首个真实且无外部副作用的 `release_candidate_reconcile` handler。
- WSL Ubuntu 24.04 原生 Docker PostgreSQL/Redis、真实 prefork Celery worker
  与 Redis stop/start 补投、进程组 hard-crash lease 回排集成测试。

candidate ref、Gitea CI、registry、Deployment 和 Remote Agent operation 仍属于
后续 M7 纵切，不在当前 handler registry 中注册。

## 职责

异步任务队列、worker、重试、定时任务。

## 技术栈

Redis + Celery。M7 已排除 RQ 和自研队列。

## 上游依赖

Platform API、Orchestrator、Tool Gateway。

## 主要输出

job、retry state、scheduled task、worker heartbeat。

## MVP 实现要点

1. PostgreSQL `workflow_jobs` 是业务权威，Redis 只负责投递；Celery business
   message 只携带 `workflow_job_id`。
2. durable dispatcher 使用 dispatch lease、next enqueue、attempt/error 周期补投，
   关闭数据库 commit 与 broker publish 的永久空窗。
3. claim、mark-running、heartbeat、finish 和 stale reclaim 分别使用短 Session；
   外部 I/O 或长业务计算期间不持有 Task/job 行锁。纯数据库 reconcile 在最终
   收敛短事务中按规定锁序持锁。
4. job 保存 `side_effect_class`。无外部副作用 job 可安全重排；可能已经产生外部
   副作用且状态未知时进入 `recovery_required`。
5. worker 使用 JSON serializer、late ack、prefetch=1 和显式 soft/hard timeout；
   不使用通用 Celery autoretry 盲目重放 push、CI 或 deploy。
6. M7-2 只实现真实的 `release_candidate_reconcile` 数据库 handler；publish、CI
   与 deploy handler 随后续纵切实现。

## WorkflowJob 状态协议

```text
claimable         = pending
lease-active      = claimed | running | cancel_requested
resource-blocking = pending | claimed | running | cancel_requested | recovery_required
terminal          = succeeded | failed | cancelled
manual-blocking   = recovery_required
```

- `attempt` 在 claim 成功时增加；`started_at` 在首次进入 running 时写入；
  succeeded/failed/cancelled 写 `finished_at`。
- claim 后若 mark-running 发现 Task 已暂停，handler 尚未开始，因此释放 worker
  lease、回 pending，并把本次 claim 增加的 `attempt` 同事务减回 1。用户暂停
  不消耗业务执行次数，也不会在 `attempt=max_attempts` 时违反 pending 约束。
- safe retry/stale reclaim 仅在 `attempt < max_attempts` 时回 pending；耗尽时进入
  failed，写 `workflow_job_attempts_exhausted`、数据库完成时间并清 lease/retry/
  enqueue。已请求取消且确认无副作用时优先 cancelled。
- pending 取消直接 cancelled；claimed 且 handler 尚未开始时直接 cancelled；
  running 取消进入 cancel_requested 并保留 lease。
- `recovery_required` 清空两类 lease、retry/enqueue 时间，
  `finished_at=null`，并通过部分唯一索引阻止同资源新 job。
- terminal 不再迁移；M7-2 不提供 recovery_required 自动退出路径。
- `release_candidate_reconcile` 只允许 Task `running|waiting_approval`。dispatcher
  排除 paused/cancelled/failed/done；mark-running 遇到 paused 时回 pending 并清
  lease，Task resume 把 pending job 的 next enqueue 推进到
  `max(clock_timestamp(), next_retry_at)`，不得绕过业务重试退避。
- mark-running 因 Task pause 撤销 attempt 时写
  `WorkflowJobExecutionDeferred(error_code=workflow_job_task_paused)`；
  `WorkflowJobDispatchDeferred` 只表示 broker publish 失败。

## Side-effect stale 规则

`side_effect_class` 只由 handler registry 派生：

|分类|stale running/cancel_requested 处理|
|---|---|
|`none`|未取消时安全回 pending；已请求取消时 cancelled。|
|`external_idempotent`|先查询同一远端 operation；明确终态时收敛，明确未执行或可附着同一幂等 operation 时重排，unknown 进入 recovery_required。|
|`external_uncertain`|只接受明确 succeeded/failed；其余进入 recovery_required。|

cancel_requested 覆盖 external 规则：不得再次调用原副作用；remote cancelled/
not_started -> cancelled，succeeded -> succeeded，failed -> failed，running/
unknown -> recovery_required。

M7-2 registry 固定为：

```text
release_candidate_reconcile -> release_candidate -> none
```

## Durable dispatcher

Candidate POST 在 PostgreSQL 事务内创建 pending job。M7-2B2 事务层只依赖
PostgreSQL WorkflowJob repository，不直接依赖 Workflow Engine 运行包；M7-2C
独立 dispatcher 使用同一 reserve 入口扫描和投递。每轮先读取一次
`due_cutoff=clock_timestamp()`，其 due 条件为：

```sql
tasks.status IN ('running', 'waiting_approval')
AND workflow_jobs.status = 'pending'
AND workflow_jobs.attempt < workflow_jobs.max_attempts
AND (
  workflow_jobs.next_retry_at IS NULL
  OR workflow_jobs.next_retry_at <= due_cutoff
)
AND workflow_jobs.next_enqueue_at <= due_cutoff
AND (
  workflow_jobs.dispatch_lease_expires_at IS NULL
  OR workflow_jobs.dispatch_lease_expires_at <= due_cutoff
)
```

reserve 事务先无锁扫描候选，再按 Task -> WorkflowJob 使用
`FOR UPDATE SKIP LOCKED` 重验并写 owner/expiry、增加 `enqueue_attempt`；取得
Job 锁后另读一次 `reserved_at=clock_timestamp()`。提交后才 publish。
success/failure finalize 必须按
`id + status=pending + dispatch_lease_owner=reservation_owner +
expected_enqueue_attempt` 条件更新。dispatch owner 必须是每次 reservation
唯一 token。success 还必须清
`last_enqueue_error_code`；若 worker 已先 claim，finalize no-op。

- reserve 后、publish 前崩溃：dispatch lease 到期后补投。
- publish 后、success finalize 前崩溃：重复投递由 PostgreSQL claim 去重。
- publish 成功但消息丢失：`next_enqueue_at` 到期后 redispatch。
- claim 时清空 dispatch lease、next enqueue 和 next retry。

broker enqueue 与 safe business retry 分别使用无 jitter 的指数退避：

```text
min(max_enqueue_backoff, enqueue_backoff * 2 ** (enqueue_attempt - 1))
min(max_retry_backoff, retry_backoff * 2 ** max(attempt - 1, 0))
```

## Worker 与锁顺序

Celery business message 只含 `workflow_job_id`。同时访问 Task/job/resource 时：

```text
无锁读取 job.task_id/resource_id 与 Candidate binding/approval identity hint
  -> Task FOR UPDATE
  -> WorkflowJob FOR UPDATE
  -> ProjectRepositoryBinding FOR UPDATE
  -> ReleaseCandidate FOR UPDATE
  -> Approval
```

worker lease owner 必须包含每次 delivery 唯一 token，不能只使用 hostname/PID，
否则旧 attempt 的 late result 可能覆盖同一进程中的新 claim。

dispatcher reserve 按 `Task -> WorkflowJob` 加锁；Task pause 在已持 Task 锁时
按 Job UUID 顺序撤销 pending job 的 dispatch token，使旧 finalize no-op。
Binding PUT 只按
`Binding -> Candidate(UUID 顺序) -> Approval(UUID 顺序)` 加锁，不反向获取
Task。Redis、HTTP、Git 或其他外部 I/O 期间不持有数据库行锁。
reconcile 获取全部资源锁后重新读取一次 `clock_timestamp()` 并重验
worker owner、lease 和 Approval expiry，禁止锁等待后沿用旧时间。

stale reclaimer 先无锁扫描过期 job ID，再为每个 ID 建立独立短 Session：
无锁读取 `task_id` hint，随后按 `Task -> WorkflowJob` 加锁并重新验证 lease。
不得先锁 WorkflowJob 再反向获取 Task，也不得在一批 job 上长期持锁。

Celery 固定使用 JSON serializer、`accept_content=["json"]`、
`acks_late=true`、`task_reject_on_worker_lost=true`、
`worker_prefetch_multiplier=1`、`task_ignore_result=true`、UTC，且不配置通用
autoretry。

## M7-2 配置

|环境变量|默认值|
|---|---:|
|`CLOUDHELM_WORKFLOW_QUEUE_NAME`|`cloudhelm.workflow`|
|`CLOUDHELM_WORKFLOW_MAINTENANCE_QUEUE_NAME`|`cloudhelm.workflow.maintenance`|
|`CLOUDHELM_WORKFLOW_JOB_LEASE_SECONDS`|90|
|`CLOUDHELM_WORKFLOW_JOB_HEARTBEAT_SECONDS`|20|
|`CLOUDHELM_WORKFLOW_DISPATCH_INTERVAL_SECONDS`|5|
|`CLOUDHELM_WORKFLOW_DISPATCH_LEASE_SECONDS`|15|
|`CLOUDHELM_WORKFLOW_BROKER_PUBLISH_TIMEOUT_SECONDS`|5|
|`CLOUDHELM_WORKFLOW_REDISPATCH_AFTER_SECONDS`|60|
|`CLOUDHELM_WORKFLOW_ENQUEUE_BACKOFF_SECONDS`|1|
|`CLOUDHELM_WORKFLOW_MAX_ENQUEUE_BACKOFF_SECONDS`|60|
|`CLOUDHELM_WORKFLOW_RETRY_BACKOFF_SECONDS`|5|
|`CLOUDHELM_WORKFLOW_MAX_RETRY_BACKOFF_SECONDS`|300|
|`CLOUDHELM_WORKFLOW_RECLAIM_INTERVAL_SECONDS`|30|
|`CLOUDHELM_WORKFLOW_BATCH_SIZE`|50|
|`CLOUDHELM_WORKFLOW_SOFT_TIME_LIMIT_SECONDS`|840|
|`CLOUDHELM_WORKFLOW_HARD_TIME_LIMIT_SECONDS`|900|
|`CLOUDHELM_WORKFLOW_VISIBILITY_TIMEOUT_SECONDS`|1800|

Settings 必须验证两倍 heartbeat 小于 job lease、reclaim interval 小于 job lease、
两倍 publish timeout 小于 dispatch lease、dispatch interval 小于 dispatch lease、
redispatch 时间大于 dispatch lease，以及
`soft < hard < visibility`、`visibility >= hard + job lease`。

## `release_candidate_reconcile`

该 job 与 Candidate、Approval 同事务创建，`max_attempts=3`。payload 精确为：

```json
{
  "schema_version": "m7.release-candidate-reconcile.payload.v1",
  "candidate_id": "UUID",
  "approval_id": "UUID",
  "expected_candidate_request_hash": "sha256:<64 lowercase hex>",
  "expected_binding_snapshot_sha256": "sha256:<64 lowercase hex>",
  "expected_pull_request_record_id": "UUID"
}
```

result 精确为：

```json
{
  "schema_version": "m7.release-candidate-reconcile.result.v1",
  "outcome": "valid | stale | terminal_noop",
  "candidate_status": "pending_approval | approved | rejected | published | stale | cancelled",
  "approval_status": "pending | approved | rejected | expired | cancelled",
  "pull_request_record_id": "UUID",
  "binding_snapshot_sha256": "sha256:<64 lowercase hex>",
  "checked_at": "RFC3339 UTC date-time"
}
```

两者所有字段 required 且 `additionalProperties=false`。handler 重新核验当前 PR、
binding snapshot、Candidate request hash 与 Approval：

- 全部一致：`succeeded + outcome=valid`。
- PR/binding/hash 漂移：Candidate/Approval 原子 stale/expired，
  `succeeded + outcome=stale`。
- 对 pending/approved Candidate，Approval 过期、已消费、expired/cancelled 或
  action/resource/hash 不匹配：Candidate stale；仅 pending Approval 转 expired，
  已 approved/expired/cancelled 保留历史，job succeeded + stale。
- Candidate 已 rejected/stale/cancelled/published：
  `succeeded + outcome=terminal_noop`。
- Approval 缺失，或 Candidate/Approval 出现 pending/approved/rejected 决策状态
  不一致：failed + `release_candidate_approval_state_invalid`。
- transient DB error：`attempt < max_attempts` 时按 safe business retry 回
  pending，否则 failed + `workflow_job_attempts_exhausted`。

该 job 不执行外部副作用，也不替代 ApprovalService 在 approve/reject 时的同步
freshness 校验。

当前数据库 CHECK 会直接拒绝 `approve_release_candidate` 的 action、
resource type 或 L2 risk 结构漂移；handler 仍保留防御性契约校验，并对可持久化
的 resource id、request hash、Candidate snapshot/hash/PR 漂移执行 stale 收敛。

## 测试关注点

- 参数校验和错误处理。
- 与相邻模块的集成路径。
- 顺序/并发重复 delivery、lease owner、heartbeat、dispatch 补偿和旧 owner late
  result。
- worker hard-crash、stale claimed/running、side-effect-aware reclaim。
- Redis 重启后 pending job 能由 dispatcher 恢复投递。
- Task pause/cancel 与 claim 并发。
- Task cancel 同事务把 active Candidate 标记为 `cancelled`，只把 pending
  Candidate Approval 标记为 expired，避免终态 Task 遗留可推进资源。
- PostgreSQL/migration/worker 集成只创建真实 `none` job；
  `external_idempotent/external_uncertain` 仅测试纯 stale policy/registry。后续真实
  handler 用新 migration 扩展 CHECK 后再补数据库集成。
- 关键输出是否能被控制台展示和被审计追踪。
