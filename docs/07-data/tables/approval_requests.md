# approval_requests

> 来源：[数据库关键表总览](../01-database-schema.md)
> M7-2 migration：`20260716_0008_create_m7_release_jobs.py`

## 业务含义

保存设计、计划、工具动作和 M7 资源动作的人工审批。审批 HTTP 请求只记录决策；
发布、CI、部署等副作用必须由后续显式 workflow 步骤消费已批准记录。

M7-2 在保留 M1-M6 非资源审批兼容性的同时增加：

- `resource_type`
- `resource_id`
- `request_hash`
- `expires_at`
- `consumed_at`

## 字段

|字段|约束|说明|
|---|---|---|
|`id`|UUID PK|审批唯一标识。|
|`task_id`|FK `tasks.id`, `ON DELETE CASCADE`|所属 Task。|
|`action`|非空|被审批动作。|
|`risk_level`|非空|L0-L4；ReleaseCandidate 固定 L2。|
|`reason`|非空|审批原因。|
|`resource_type/resource_id/request_hash/expires_at`|成组为空或成组非空|资源审批身份、稳定 hash 和有效期。|
|`status`|pending/approved/rejected/expired/cancelled|审批状态。|
|`requested_by_agent_run_id`|可空 FK, `ON DELETE SET NULL`|发起审批的 AgentRun。|
|`decided_by/decided_at`|pending 时为空，其他状态非空|决策审计。|
|`consumed_at`|可空|后续副作用步骤的单次消费时间。|
|`created_at`|非空 UTC|创建时间。|

## 资源审批不变量

ReleaseCandidate 审批固定为：

```text
action=approve_release_candidate
risk_level=L2
resource_type=release_candidate
resource_id=<candidate UUID>
request_hash=<candidate request hash>
```

`request_hash` 格式为 `sha256:<64 lowercase hex>`。同一
`resource_type/resource_id/action` 只允许一条审批记录；rejected 后不会为同一
Candidate 重建审批。

`action=approve_release_candidate` 与
`resource_type=release_candidate + risk_level=L2` 是双向等价约束。通用
`POST /api/tasks/{task_id}/approvals` 对该保留 action 返回
`422 approval_action_reserved`；只有 CandidateService 的内部原子事务可以创建。

CandidateService 固定写
`requested_by_agent_run_id=PullRequestRecord.created_by_agent_run_id`，且 PR
缺少该字段时拒绝创建 Candidate。approve/reject 把 trim 后的 plain UUID 或
`agent-run:<UUID>` actor id 规范化为 UUID；若等于该实现 AgentRun，返回
`403 approval_self_decision_forbidden`。

数据库约束同步要求 `approve_release_candidate` 的
`requested_by_agent_run_id IS NOT NULL`。该列为兼容其他审批类型和历史删除仍保持
可空、外键仍为 `ON DELETE SET NULL`；Candidate 与 PR creator 的跨表等值关系由
CandidateService 在既定锁序内重验。

## 决策与消费

- ReleaseCandidate approve/reject 先用无锁 hint 找到资源，再固定按
  `Task -> ProjectRepositoryBinding -> ReleaseCandidate -> Approval` 加锁并重验
  task/resource/hash/expiry；不得先锁 Approval 再反向锁 Candidate。
- 资源审批必须在 `PostgreSQL now() < expires_at` 时决策；数据库同时约束
  approved/rejected 的 `decided_at < expires_at`。
- approve/reject 同一事务更新 Approval 与 ReleaseCandidate，但不 push、不 dispatch
  CI，也不写 `consumed_at`。
- binding/PR/hash 漂移把 pending Approval 标记 expired 时，必须同时写
  `decided_by=system:release_candidate_freshness` 与数据库 `decided_at=now()`，
  满足非 pending 状态的决策审计约束。
- 消费审批时必须重新校验：

  ```text
  status=approved
  consumed_at IS NULL
  expires_at > PostgreSQL now()
  resource_type/resource_id/request_hash 与当前资源完全一致
  ```

- 校验成功后在同一行锁事务写 `consumed_at=now()`。
- `consumed_at` 只允许出现在 approved、未过期的资源审批上，且必须满足
  `decided_at <= consumed_at < expires_at`。
- `DecisionRequest.actor_id` 当前是受控入口传入的审计身份；M7-2 会按 AgentRun ID
  执行领域自批门禁，但不把它描述为独立认证系统。

## 索引

```sql
CREATE UNIQUE INDEX ux_approval_requests_resource_action
  ON approval_requests(resource_type, resource_id, action)
  WHERE resource_type IS NOT NULL;

CREATE INDEX ix_approval_requests_resource_status
  ON approval_requests(resource_type, resource_id, status)
  WHERE resource_type IS NOT NULL;

CREATE INDEX ix_approval_requests_pending_expiry
  ON approval_requests(expires_at, id)
  WHERE status = 'pending' AND expires_at IS NOT NULL;
```

完整 CHECK 与最终 DDL 以
[01-database-schema.md](../01-database-schema.md) 为权威来源。
