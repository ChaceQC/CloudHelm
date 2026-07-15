# release_candidates

> 来源：[数据库关键表总览](../01-database-schema.md)
> M7-2 migration：`20260716_0008_create_m7_release_jobs.py`

## 业务含义

保存 M6 PullRequestRecord 的精确 commit、受控 Gitea candidate ref、Repository
Binding snapshot、第一道 L2 Approval 和后续远端 ref 校验结果。Candidate POST
只创建审批前身份，不执行 push 或 CI。

## 字段

|字段|约束|说明|
|---|---|---|
|`id`|UUID PK|Candidate 唯一标识。|
|`task_id/project_id`|FK|所属 Task/Project。|
|`pull_request_record_id`|FK `pull_request_records.id`, NO ACTION|最新版 open M6 PR record；单独删除被阻止。|
|`repository_binding_id`|FK `project_repository_bindings.id`, NO ACTION|创建时使用的 binding；单独删除被阻止。|
|`binding_snapshot_json`|JSON object|只含八个安全字段。|
|`binding_snapshot_sha256`|`sha256:<64 hex>`|覆盖安全字段和内部 profile/clone/credential。|
|`commit_sha`|40 或 64 位小写 hex|M6 精确 commit。|
|`target_ref`|完整 `refs/heads/...`|服务端确定性派生的受控 ref。|
|`request_hash`|`sha256:<64 hex>`|第一道审批绑定内容。|
|`status`|见下节|Candidate 生命周期。|
|`approval_id`|非空 FK `approval_requests.id`, NO ACTION|第一道 Approval；单独删除被阻止。|
|`remote_verified_sha`|可空 commit SHA|发布后 `ls-remote` 校验值。|
|`idempotency_key`|任务内唯一|服务端确定性幂等身份。|
|`approved_at/published_at`|可空 UTC|批准和远端发布时间。|
|`created_at/updated_at`|UTC|审计时间。|

## 状态

```text
pending_approval
approved
rejected
published
stale
cancelled
```

- `pending_approval -> approved|rejected|stale|cancelled`
- `approved -> published|stale|cancelled`
- `rejected/published/stale/cancelled` 为 Candidate 终态。
- `published` 必须满足
  `approved_at IS NOT NULL`、`published_at IS NOT NULL` 且
  `remote_verified_sha = commit_sha`。
- 每 Task 同时最多一个 `pending_approval|approved` Candidate。published 不进入
  该部分唯一索引，因此后续新 PR/snapshot 可创建下一 Candidate，同时保留旧发布
  事实。

## Canonical snapshot 与 hash

安全 JSON 精确为八个字段：

```json
{
  "schema_version": "m7.repository-binding.snapshot.v1",
  "provider": "gitea",
  "repository_external_id": "123",
  "repository_owner": "cloudhelm",
  "repository_name": "demo",
  "default_branch": "dev",
  "workflow_id": ".gitea/workflows/ci.yml",
  "release_ref_prefix": "refs/heads/cloudhelm/candidates"
}
```

内部 snapshot 对象固定包含：

```text
schema_version=m7.repository-binding.internal-snapshot.v1
public_snapshot=<上述八字段对象>
profile_key
clone_url
credential_ref
```

所有 M7-2 hash 复用
`cloudhelm_tool_gateway.audit.stable_json_hash`：

```python
json.dumps(
    value,
    ensure_ascii=False,
    sort_keys=True,
    default=str,
).encode("utf-8")
```

随后计算 SHA-256 并返回 `sha256:<64 lowercase hex>`。UUID 在进入对象前统一为
小写标准字符串；不得直接对数据库 JSONB 文本表现或另一套紧凑 JSON 序列化计算。

## target ref、request hash 与幂等

```text
target_ref =
  {release_ref_prefix}/{task_id}/{full_commit_sha}/{snapshot_hash_hex}
```

Candidate request canonical 精确包含：

```text
schema_version=m7.release-candidate.request.v1
action=approve_release_candidate
task_id
project_id
pull_request_record_id
repository_binding_id
binding_snapshot_sha256
commit_sha
target_ref
```

其稳定 hash 写入 `request_hash`；幂等键固定为：

```text
release_candidate:v1:<request_hash hex>
```

数据库唯一性：

```text
(task_id, idempotency_key)
(repository_binding_id, target_ref)
(pull_request_record_id, binding_snapshot_sha256)
```

顺序/并发重复 POST 返回同一 Candidate、Approval 和内部 reconcile job。若记录已
rejected，仍返回原记录且不创建新审批；重新申请必须使用新的 PullRequestRecord
或新的 binding snapshot。

Candidate POST 在同一短事务按
`Task -> ProjectRepositoryBinding -> PullRequestRecord -> existing Candidate`
加锁，并全程持有 Binding `FOR UPDATE`，防止 Binding PUT 在 snapshot 生成与
Candidate 插入之间穿透。与 Binding PUT 的并发结果只能是“POST 使用新 snapshot”
或“PUT 失效刚创建的旧 snapshot Candidate”。

## API 与副作用边界

- POST 请求体固定为严格空对象 `{}`；首次创建返回 201，幂等命中返回 200。
- Candidate、Approval 和 `release_candidate_reconcile` WorkflowJob 在同一
  PostgreSQL 事务创建。
- 服务端预生成 Candidate UUID，先插入带该 `resource_id` 的 Approval，再插入
  `approval_id NOT NULL` 的 Candidate 和 WorkflowJob；不存在提交后补绑窗口。
- 最新 PullRequestRecord 必须有 `created_by_agent_run_id`，并固定写入
  `Approval.requested_by_agent_run_id`。缺失时返回
  `m6_pull_request_creator_required`；该 AgentRun 与审批 actor 规范化 UUID 相同时
  拒绝自批。
- 事务提交后使用 durable dispatcher best-effort 投递；失败由周期扫描补投。
- reconcile job 只核验 freshness，不是审批唯一门禁，不执行 push/CI。
- M7-2 create/approve/reject 不修改 Task status/current phase；完整 Orchestrator
  状态推进由后续纵切实现。
- API 不返回 clone URL、profile key、credential ref 或内部 snapshot 对象。

完整 CHECK、索引和 SQL 以
[01-database-schema.md](../01-database-schema.md) 为权威来源。
