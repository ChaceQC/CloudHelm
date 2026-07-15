# modules/workflow-engine

> 来源：[设计书 7.1-7.2](../../../云舵 CloudHelm 毕设设计书.md)  
> 层级：`modules/workflow-engine`

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
   handler 运行期间不持有 Task/job 行锁。
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
  lease，Task resume 把 pending job 的 next enqueue 推进到数据库当前时间。

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

Candidate POST 在 PostgreSQL 事务内创建 pending job，提交后调用 dispatcher 的
同一 reserve 入口 best-effort 投递。周期 dispatcher 的 due 条件为：

```sql
tasks.status IN ('running', 'waiting_approval')
AND workflow_jobs.status = 'pending'
AND workflow_jobs.attempt < workflow_jobs.max_attempts
AND (
  workflow_jobs.next_retry_at IS NULL
  OR workflow_jobs.next_retry_at <= now()
)
AND workflow_jobs.next_enqueue_at <= now()
AND (
  workflow_jobs.dispatch_lease_expires_at IS NULL
  OR workflow_jobs.dispatch_lease_expires_at <= now()
)
```

reserve 事务使用 `FOR UPDATE SKIP LOCKED`，写 owner/expiry 并先增加
`enqueue_attempt`；提交后才 publish。success/failure finalize 必须按
`id + status=pending + owner` 条件更新。success 还必须清
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
无锁读取 job.task_id hint
  -> Task FOR UPDATE
  -> WorkflowJob FOR UPDATE
  -> ProjectRepositoryBinding FOR UPDATE
  -> ReleaseCandidate FOR UPDATE
  -> Approval
```

dispatcher reserve 只锁 WorkflowJob；Binding PUT 只按
`Binding -> Candidate(UUID 顺序) -> Approval(UUID 顺序)` 加锁。两者不得在同一
事务反向获取 Task。Redis、HTTP、Git 或 handler 执行期间不持有数据库行锁。

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

## 测试关注点

- 参数校验和错误处理。
- 与相邻模块的集成路径。
- 顺序/并发重复 delivery、lease owner、heartbeat、dispatch 补偿和旧 owner late
  result。
- worker hard-crash、stale claimed/running、side-effect-aware reclaim。
- Redis 重启后 pending job 能由 dispatcher 恢复投递。
- Task pause/cancel 与 claim 并发。
- PostgreSQL/migration/worker 集成只创建真实 `none` job；
  `external_idempotent/external_uncertain` 仅测试纯 stale policy/registry。后续真实
  handler 用新 migration 扩展 CHECK 后再补数据库集成。
- 关键输出是否能被控制台展示和被审计追踪。
