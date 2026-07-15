# workflow_jobs

> 来源：[数据库关键表总览](../01-database-schema.md)
> M7-2 migration：`20260716_0008_create_m7_release_jobs.py`

## 业务含义

保存异步业务 job 的权威状态。PostgreSQL 是业务权威；Redis/Celery 只投递
`workflow_job_id`，Celery task id 不作为业务身份。

M7-2 数据库 handler registry 只允许：

```text
release_candidate_reconcile -> release_candidate -> none
```

后续新增 publish、CI 或 deploy handler 时必须通过新 migration 扩展映射和
side-effect 规则，不能写空 handler。

## 字段

|字段|说明|
|---|---|
|`task_id`|所属 Task。|
|`job_type/resource_type/resource_id`|handler 与领域资源身份。|
|`side_effect_class`|none/external_idempotent/external_uncertain。|
|`status`|业务状态。|
|`idempotency_key/request_hash`|稳定业务身份和输入 hash。|
|`attempt/max_attempts`|业务执行次数；claim 时递增。|
|`lease_owner/lease_expires_at/heartbeat_at`|worker lease。|
|`next_retry_at/cancel_requested_at`|安全业务重试和取消。|
|`dispatch_lease_owner/dispatch_lease_expires_at`|broker publish reserve。|
|`next_enqueue_at/last_enqueued_at/enqueue_attempt/last_enqueue_error_code`|durable dispatch 补偿。|
|`payload_json/result_json/error_code`|安全输入、结果和稳定错误码。|
|`started_at/finished_at/created_at/updated_at`|执行与审计时间。|

## 状态分类

```text
claimable         = pending
lease-active      = claimed | running | cancel_requested
resource-blocking = pending | claimed | running | cancel_requested | recovery_required
terminal          = succeeded | failed | cancelled
manual-blocking   = recovery_required
```

`recovery_required` 清空 worker/dispatch lease，`next_retry_at`、
`next_enqueue_at` 和 `finished_at` 均为 null，并通过部分唯一索引阻止同资源创建
第二个 job。

## 状态转移

|当前状态|条件|目标|
|---|---|---|
|pending|claim 成功且 attempt 未耗尽|claimed|
|pending|Task/调用方取消|cancelled|
|claimed|owner 匹配且允许执行|running|
|claimed|handler 尚未开始且取消|cancelled|
|claimed|lease 过期且仍可尝试|pending|
|claimed|lease 过期且 attempt 已耗尽|failed|
|running|handler 成功/确定失败|succeeded/failed|
|running|安全重试成立且 attempt 未耗尽|pending|
|running|需要重试但 attempt 已耗尽|failed|
|running|Task/调用方取消|cancel_requested|
|running|外部状态未知|recovery_required|
|cancel_requested|确认未执行/已取消|cancelled|
|cancel_requested|远端已有确定终态|succeeded/failed|
|cancel_requested|仍运行或状态未知|recovery_required|

terminal 不再迁移；M7-2 不提供 `recovery_required` 自动退出路径。
attempt 耗尽的 failed 固定写
`error_code=workflow_job_attempts_exhausted`、数据库完成时间并清两类 lease、
retry/enqueue。已请求取消且确认无副作用时，cancelled 优先于 attempts exhausted。

`release_candidate_reconcile` 只允许 Task `running|waiting_approval`：

- dispatcher 不选择 paused/cancelled/failed/done Task。
- mark-running 发现 paused 时 `claimed -> pending`、清 worker lease；Task resume
  把相关 pending job 的 `next_enqueue_at` 推进到数据库当前时间。
- mark-running 发现 cancelled/failed/done 时收敛为 cancelled，并写
  `cancel_requested_at` 与稳定错误码。

## side-effect stale 规则

- `none`：stale claimed/running 在未取消时安全回 pending；stale
  cancel_requested 进入 cancelled。
- `external_idempotent`：先查询相同远端 operation identity。明确终态时收敛；
  明确未执行或可附着到同一幂等 operation 时才回 pending；unknown 进入
  recovery_required。
- `external_uncertain`：running 后只接受明确 succeeded/failed；其他结果进入
  recovery_required，不自动重放。

`side_effect_class` 只能由服务端 handler registry 派生，创建方不能提交或覆盖。

对 external job，cancel_requested 覆盖上述 stale 规则：不得再次调用原副作用。
remote cancelled/not_started -> cancelled，succeeded -> succeeded，failed ->
failed，running/unknown -> recovery_required。

## Durable dispatcher

新 job 初值：

```text
status=pending
attempt=0
enqueue_attempt=0
next_enqueue_at=PostgreSQL now()
next_retry_at=null
worker/dispatch lease=null
```

due 条件：

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

dispatcher 使用 `FOR UPDATE SKIP LOCKED ORDER BY next_enqueue_at,id`：

1. reserve 短事务写 dispatch owner/expiry 并先增加 `enqueue_attempt`。
2. 提交后 publish 仅含 job UUID 的 JSON message。
3. success finalize 以 `id + status=pending + owner` 条件写
   `last_enqueued_at`、下一 redispatch 时间，清
   `last_enqueue_error_code` 与 lease。
4. failure finalize 使用同一条件写稳定错误码和指数退避。
5. worker 已先 claim 时 finalize 为 no-op，不能覆盖 claimed 状态。

enqueue 失败退避：

```text
min(max_enqueue_backoff, enqueue_backoff * 2 ** (enqueue_attempt - 1))
```

safe business retry：

```text
min(max_retry_backoff, retry_backoff * 2 ** max(attempt - 1, 0))
```

M7-2 不加 jitter，便于确定性并发与时钟测试。

## `release_candidate_reconcile`

Candidate POST 同一事务创建：

```text
job_type=release_candidate_reconcile
resource_type=release_candidate
resource_id=<candidate UUID>
side_effect_class=none
max_attempts=3
```

request canonical：

```text
schema_version=m7.workflow-job.release-candidate-reconcile.v1
job_type
resource_type
resource_id
candidate_request_hash
approval_id
```

`request_hash=stable_json_hash(canonical)`；
`idempotency_key=release_candidate_reconcile:v1:<request_hash hex>`。

payload 精确为：

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

两者所有字段 required 且 `additionalProperties=false`。`valid` 只对应
pending/pending 或 approved/approved；本次漂移为 stale，pending Approval 转
expired，已 approved 的 Approval 保留 approved；terminal_noop 只对应
rejected/published/stale/cancelled Candidate。

检测到 PR/binding/hash 漂移时，handler 在同一事务把 Candidate 标记 stale、把
pending Approval 标记 expired，并写
`decided_by=system:release_candidate_freshness` 与数据库决策时间，但 job 自身
succeeded；检测到 rejected/stale/cancelled/published 时返回 terminal_noop。
对仍为 pending/approved 的 Candidate，Approval 已过期、已消费、状态为
expired/cancelled，或 action/resource/hash 不匹配时也进入 stale；仅 pending
Approval 改 expired，已 approved/expired/cancelled 的审批历史不改写。Approval
缺失或 pending/approved/rejected 决策状态组合违反原子事务时，job failed +
`release_candidate_approval_state_invalid`。
transient DB error 只有在 `attempt < max_attempts` 时回 pending，否则 failed +
`workflow_job_attempts_exhausted`。

## 锁顺序

同时访问 Task/job/resource 的事务固定：

```text
Task -> WorkflowJob -> ProjectRepositoryBinding -> ReleaseCandidate -> Approval
```

dispatcher reserve 只锁 WorkflowJob；stale reserve 提交后再用新事务按上述顺序
收敛。Binding PUT 只按
`Binding -> Candidate(UUID 顺序) -> Approval(UUID 顺序)` 加锁，不反向获取
Task。Redis、HTTP、Git 或 handler 执行期间不持有数据库行锁。

完整 CHECK、部分唯一索引和 SQL 以
[01-database-schema.md](../01-database-schema.md) 为权威来源。

M7-2 的 PostgreSQL/migration/worker 集成测试只创建真实 `none` job；
`external_idempotent/external_uncertain` 只测试纯 stale policy/handler registry。
后续真实外部 handler 通过新 migration 扩展数据库 CHECK 后，再补对应数据库集成。
