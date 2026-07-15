# 数据库关键表总览

> 来源：[设计书 11.2](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：汇总所有关键表结构；单表文档放在 tables 目录。

## M2 实现状态

`modules/platform-api/migrations/versions/20260708_0001_create_core_m2_tables.py`
已创建 `projects`、`tasks`、`requirement_specs`、`technical_designs`、
`agent_runs`、`tool_calls`、`approval_requests`、`event_logs`。迁移连接串来自
`CLOUDHELM_DATABASE_URL`，本地开发默认使用
`postgresql+psycopg://cloudhelm:cloudhelm_dev@127.0.0.1:15432/cloudhelm`。

M2 已落地索引：

- `ix_tasks_project_status`
- `ix_event_logs_task_created_at`
- `ix_requirement_specs_task_status`
- `ix_technical_designs_task_status`
- `ix_agent_runs_task_status`
- `ix_tool_calls_task_status`
- `ix_approval_requests_task_status`

## M4-M6 迁移同步

- `20260708_0002_create_m4_agent_tables.py`：新增 `development_plans`，扩展
  AgentRun 结构化输出、错误和事件。
- `20260709_0003_create_m5_tool_gateway.py`：扩展 ToolCall 的幂等键、参数/结果
  摘要、stdout/stderr、耗时、错误码和服务端审计字段。
- `20260710_0004_harden_m1_m5_data_integrity.py`：补版本、唯一性、状态与引用约束。
- `20260711_0005_create_agent_conversations.py`：新增 Task root/subagent
  conversation、完整 ResponseItem、Prompt Cache 与逐请求 usage。
- `20260714_0006_create_m6_local_development.py`：
  - `agent_conversations.revision`
  - `agent_runs.workflow_step/attempt/idempotency_key`
  - `tool_calls.provider_call_id/provider_item_type`
  - 新增 `artifacts`
  - 新增 `pull_request_records`

M6 关键数据库门禁：

- partial unique index 保证每个 Task 只有一个 root conversation。
- partial unique index 保证每个 Task 同时最多一个 active M6 AgentRun。
- `(task_id, idempotency_key)` 分别约束 AgentRun、ToolCall、Artifact 和 PR
  record 的任务内幂等身份。
- `(agent_run_id, provider_call_id)` 保证一个 provider call 只映射一个 ToolCall。
- Artifact 的 producer 类型与 AgentRun/ToolCall 引用必须互斥匹配，API 不返回
  `storage_key`。
- local PullRequestRecord 必须 `url IS NULL`，base/head 不同，且四类门禁
  Artifact 引用不可为空。

## M7 迁移状态与目标边界

`20260715_0007_create_m7_environment_remote_target.py` 已落地并验证：

- `environments`
- `remote_targets`
- `remote_agent_credentials`
- `remote_agent_replay_nonces`

这四张表已经具备 ORM、repository/service、真实 PostgreSQL 黑盒/白盒测试、
upgrade/downgrade/check 和共享契约证据。M7-1 只实现 staging/demo Environment、
profile-only Linux RemoteTarget 和 machine-auth heartbeat；尚未表示完整 M7
远端部署闭环完成。

其余 `ProjectRepositoryBinding`、`ReleaseCandidate`、`WorkflowJob`、CIRun、
Deployment 和 ServiceInstance 数据仍是 `0.6.0` 目标设计，必须随对应纵切完成
migration、ORM、repository/service、黑盒/白盒测试和真实流程证据后，才能逐项
写成已实现。M7 不创建 production、Kubernetes target 或 `remote_sessions`。

M7-2 已先冻结以下迁移语义：repository 字段统一使用
`repository_external_id`；candidate 保存安全 binding snapshot JSON 与覆盖内部
配置的 snapshot hash，状态包含 rejected；远端校验字段统一为
`remote_verified_sha`；WorkflowJob 唯一身份为
`(task_id, job_type, idempotency_key)`，并保存 side-effect class、dispatch lease
与 enqueue 补偿字段。代码和 migration 尚未完成前，本段只表示执行契约已定稿。

M7 数据门禁固定为：

- RemoteTarget 只由服务端 profile 派生 endpoint、TLS 和 credential 引用；普通
  API 不接受任意连接目标或 secret。
- HMAC secret 不入库；数据库只保存 credential ref、scope、生命周期和
  SHA-256 fingerprint。已认证 nonce 只保存 hash，并由 PostgreSQL 唯一约束裁决
  顺序与并发重放。
- `release_candidates.approval_id` 记录第一道 release candidate approval；
  审批前不得发布 candidate ref 或触发 CI。
- `deployments.approval_id` 记录第二道 deployment approval；审批事务不直接
  触发远端副作用，审批消费后仍由 workflow worker 显式推进。
- 每个 candidate 只允许一个有效 CIRun，Gitea workflow 不监听 push，只接受
  Platform API 对固定 workflow 发起的 `workflow_dispatch`；CI 只生成测试、
  安全、构建和制品证据，不执行部署。
- CIRun、ReleasePlan 和 Deployment 绑定精确 commit 与不可变 OCI digest；
  可变 tag、容器 image id 或日志文本不能作为部署身份。
- M7 健康失败只保存 rollback candidate/request，不执行 restart 或 rollback；
  健康成功写 `MonitoringRegistered` 并把 Task 交接到 `Monitoring`。

## 迁移要求

- 使用 Alembic / Prisma Migrate 管理 schema 变更。
- destructive migration 必须进入 ApprovalRequest。
- 所有审计和事件表保持 append-only 思路。

## 设计书摘录

### 11.2 关键表设计

#### projects

```sql
CREATE TABLE projects (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    repo_url TEXT NOT NULL,
    default_branch TEXT NOT NULL DEFAULT 'main',
    provider TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

#### tasks

```sql
CREATE TABLE tasks (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id),
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_ref TEXT,
    status TEXT NOT NULL,
    risk_level TEXT NOT NULL DEFAULT 'L0',
    current_phase TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

#### requirement_specs

```sql
CREATE TABLE requirement_specs (
    id UUID PRIMARY KEY,
    task_id UUID NOT NULL REFERENCES tasks(id),
    project_id UUID NOT NULL REFERENCES projects(id),
    source_type TEXT NOT NULL,
    raw_input TEXT NOT NULL,
    user_story TEXT,
    constraints_json JSONB NOT NULL DEFAULT '[]',
    acceptance_criteria_json JSONB NOT NULL DEFAULT '[]',
    status TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

#### technical_designs

```sql
CREATE TABLE technical_designs (
    id UUID PRIMARY KEY,
    task_id UUID NOT NULL REFERENCES tasks(id),
    requirement_spec_id UUID NOT NULL REFERENCES requirement_specs(id),
    design_type TEXT NOT NULL,
    content_markdown TEXT NOT NULL,
    openapi_json JSONB,
    db_schema_json JSONB,
    mermaid_diagram TEXT,
    risk_level TEXT NOT NULL DEFAULT 'L0',
    status TEXT NOT NULL,
    created_by_agent_run_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

#### agent_runs

```sql
CREATE TABLE agent_runs (
    id UUID PRIMARY KEY,
    task_id UUID NOT NULL REFERENCES tasks(id),
    agent_type TEXT NOT NULL,
    status TEXT NOT NULL,
    model_name TEXT,
    prompt_hash TEXT,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cost_usd NUMERIC(12, 6) DEFAULT 0,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ
);
```

#### tool_calls

```sql
CREATE TABLE tool_calls (
    id UUID PRIMARY KEY,
    task_id UUID NOT NULL REFERENCES tasks(id),
    agent_run_id UUID REFERENCES agent_runs(id),
    tool_name TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    arguments_json JSONB NOT NULL,
    result_json JSONB,
    status TEXT NOT NULL,
    approval_id UUID,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ
);
```

#### approval_requests

```sql
CREATE TABLE approval_requests (
    id UUID PRIMARY KEY,
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    reason TEXT NOT NULL,
    resource_type TEXT,
    resource_id UUID,
    request_hash TEXT,
    status TEXT NOT NULL,
    requested_by_agent_run_id UUID REFERENCES agent_runs(id) ON DELETE SET NULL,
    decided_by TEXT,
    decided_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    consumed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_approval_requests_status
      CHECK (status IN ('pending', 'approved', 'rejected', 'expired', 'cancelled')),
    CONSTRAINT ck_approval_requests_resource_group
      CHECK (
        (
          resource_type IS NULL
          AND resource_id IS NULL
          AND request_hash IS NULL
          AND expires_at IS NULL
          AND consumed_at IS NULL
        )
        OR (
          resource_type IS NOT NULL
          AND resource_id IS NOT NULL
          AND request_hash IS NOT NULL
          AND expires_at IS NOT NULL
        )
      ),
    CONSTRAINT ck_approval_requests_request_hash
      CHECK (request_hash IS NULL OR request_hash ~ '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT ck_approval_requests_decision
      CHECK (
        (
          status = 'pending'
          AND decided_by IS NULL
          AND decided_at IS NULL
        )
        OR (
          status IN ('approved', 'rejected', 'expired', 'cancelled')
          AND decided_by IS NOT NULL
          AND decided_at IS NOT NULL
        )
      ),
    CONSTRAINT ck_approval_requests_release_candidate
      CHECK (
        (
          action = 'approve_release_candidate'
          AND resource_type = 'release_candidate'
          AND risk_level = 'L2'
          AND requested_by_agent_run_id IS NOT NULL
        )
        OR (
          action <> 'approve_release_candidate'
          AND resource_type IS DISTINCT FROM 'release_candidate'
        )
      ),
    CONSTRAINT ck_approval_requests_expiry
      CHECK (expires_at IS NULL OR expires_at > created_at),
    CONSTRAINT ck_approval_requests_decision_before_expiry
      CHECK (
        resource_type IS NULL
        OR status NOT IN ('approved', 'rejected')
        OR (
          decided_at IS NOT NULL
          AND expires_at IS NOT NULL
          AND decided_at < expires_at
        )
      ),
    CONSTRAINT ck_approval_requests_consumed
      CHECK (
        consumed_at IS NULL
        OR (
          resource_type IS NOT NULL
          AND status = 'approved'
          AND decided_at IS NOT NULL
          AND expires_at IS NOT NULL
          AND consumed_at >= decided_at
          AND consumed_at < expires_at
        )
      ),
    CONSTRAINT ck_approval_requests_time_order
      CHECK (decided_at IS NULL OR decided_at >= created_at)
);

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

#### event_logs

```sql
CREATE TABLE event_logs (
    id UUID PRIMARY KEY,
    task_id UUID REFERENCES tasks(id),
    event_type TEXT NOT NULL,
    actor_type TEXT NOT NULL,
    actor_id TEXT,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

#### project_repository_bindings（M7）

```sql
CREATE TABLE project_repository_bindings (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    provider TEXT NOT NULL DEFAULT 'gitea',
    profile_key TEXT NOT NULL,
    repository_external_id TEXT NOT NULL,
    repository_owner TEXT NOT NULL,
    repository_name TEXT NOT NULL,
    clone_url TEXT NOT NULL,
    default_branch TEXT NOT NULL,
    credential_ref TEXT NOT NULL,
    workflow_id TEXT NOT NULL,
    release_ref_prefix TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_project_repository_bindings_project UNIQUE (project_id),
    CONSTRAINT uq_project_repository_bindings_external
      UNIQUE (provider, repository_external_id),
    CONSTRAINT ck_project_repository_bindings_provider
      CHECK (provider = 'gitea'),
    CONSTRAINT ck_project_repository_bindings_status
      CHECK (status IN ('active', 'disabled')),
    CONSTRAINT ck_project_repository_bindings_profile_key
      CHECK (profile_key ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'),
    CONSTRAINT ck_project_repository_bindings_identity
      CHECK (
        length(btrim(repository_external_id)) BETWEEN 1 AND 255
        AND length(btrim(repository_owner)) BETWEEN 1 AND 255
        AND length(btrim(repository_name)) BETWEEN 1 AND 255
      ),
    CONSTRAINT ck_project_repository_bindings_clone_url
      CHECK (
        clone_url ~ '^https://[^[:space:]]+$'
        AND clone_url !~ '^https://[^/]*@'
      ),
    CONSTRAINT ck_project_repository_bindings_config
      CHECK (
        length(btrim(default_branch)) BETWEEN 1 AND 255
        AND length(btrim(credential_ref)) BETWEEN 1 AND 512
        AND length(btrim(workflow_id)) BETWEEN 1 AND 512
      ),
    CONSTRAINT ck_project_repository_bindings_release_ref_prefix
      CHECK (
        left(release_ref_prefix, 11) = 'refs/heads/'
        AND length(release_ref_prefix) BETWEEN 12 AND 240
        AND release_ref_prefix !~ '[[:space:]~^:?*]'
        AND position('[' IN release_ref_prefix) = 0
        AND position(chr(92) IN release_ref_prefix) = 0
        AND position('..' IN release_ref_prefix) = 0
        AND position('//' IN release_ref_prefix) = 0
        AND position('@{' IN release_ref_prefix) = 0
        AND right(release_ref_prefix, 1) NOT IN ('.', '/')
        AND release_ref_prefix NOT LIKE '%.lock'
      ),
    CONSTRAINT ck_project_repository_bindings_time_order
      CHECK (updated_at >= created_at)
);

CREATE UNIQUE INDEX ux_project_repository_bindings_owner_name
  ON project_repository_bindings(
    provider,
    lower(repository_owner),
    lower(repository_name)
  );

CREATE INDEX ix_project_repository_bindings_status_updated
  ON project_repository_bindings(status, updated_at DESC);
```

API 只接受 `profile_key`，读取响应不返回 `credential_ref`，也不允许普通调用方
自由提交 clone URL、workflow path 或 refspec。服务层还必须用等价
`git check-ref-format` 校验 `release_ref_prefix`；数据库 CHECK 是第二道门禁。

#### release_candidates（M7）

```sql
CREATE TABLE release_candidates (
    id UUID PRIMARY KEY,
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    pull_request_record_id UUID NOT NULL
      REFERENCES pull_request_records(id) ON DELETE NO ACTION,
    repository_binding_id UUID NOT NULL
      REFERENCES project_repository_bindings(id) ON DELETE NO ACTION,
    binding_snapshot_json JSONB NOT NULL,
    binding_snapshot_sha256 TEXT NOT NULL,
    commit_sha TEXT NOT NULL,
    target_ref TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    approval_id UUID NOT NULL
      REFERENCES approval_requests(id) ON DELETE NO ACTION,
    remote_verified_sha TEXT,
    status TEXT NOT NULL DEFAULT 'pending_approval',
    idempotency_key TEXT NOT NULL,
    approved_at TIMESTAMPTZ,
    published_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_release_candidates_task_idempotency
      UNIQUE (task_id, idempotency_key),
    CONSTRAINT uq_release_candidates_binding_ref
      UNIQUE (repository_binding_id, target_ref),
    CONSTRAINT uq_release_candidates_pr_snapshot
      UNIQUE (pull_request_record_id, binding_snapshot_sha256),
    CONSTRAINT ck_release_candidates_status
      CHECK (
        status IN (
          'pending_approval',
          'approved',
          'rejected',
          'published',
          'stale',
          'cancelled'
        )
      ),
    CONSTRAINT ck_release_candidates_snapshot
      CHECK (
        jsonb_typeof(binding_snapshot_json) = 'object'
        AND binding_snapshot_json ?& ARRAY[
          'schema_version',
          'provider',
          'repository_external_id',
          'repository_owner',
          'repository_name',
          'default_branch',
          'workflow_id',
          'release_ref_prefix'
        ]
        AND (
          binding_snapshot_json - ARRAY[
            'schema_version',
            'provider',
            'repository_external_id',
            'repository_owner',
            'repository_name',
            'default_branch',
            'workflow_id',
            'release_ref_prefix'
          ]
        ) = '{}'::jsonb
        AND binding_snapshot_json->>'schema_version'
          = 'm7.repository-binding.snapshot.v1'
        AND binding_snapshot_json->>'provider' = 'gitea'
      ),
    CONSTRAINT ck_release_candidates_snapshot_hash
      CHECK (binding_snapshot_sha256 ~ '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT ck_release_candidates_commit_sha
      CHECK (commit_sha ~ '^[0-9a-f]{40}([0-9a-f]{24})?$'),
    CONSTRAINT ck_release_candidates_remote_sha
      CHECK (
        remote_verified_sha IS NULL
        OR remote_verified_sha ~ '^[0-9a-f]{40}([0-9a-f]{24})?$'
      ),
    CONSTRAINT ck_release_candidates_request_hash
      CHECK (request_hash ~ '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT ck_release_candidates_idempotency_key
      CHECK (length(idempotency_key) BETWEEN 1 AND 180),
    CONSTRAINT ck_release_candidates_target_ref
      CHECK (
        left(target_ref, 11) = 'refs/heads/'
        AND length(target_ref) BETWEEN 12 AND 1024
        AND target_ref !~ '[[:space:]~^:?*]'
        AND position('[' IN target_ref) = 0
        AND position(chr(92) IN target_ref) = 0
        AND position('..' IN target_ref) = 0
        AND position('//' IN target_ref) = 0
        AND position('@{' IN target_ref) = 0
        AND right(target_ref, 1) NOT IN ('.', '/')
        AND target_ref NOT LIKE '%.lock'
      ),
    CONSTRAINT ck_release_candidates_lifecycle
      CHECK (
        (
          status = 'pending_approval'
          AND approved_at IS NULL
          AND published_at IS NULL
          AND remote_verified_sha IS NULL
        )
        OR (
          status = 'approved'
          AND approved_at IS NOT NULL
          AND published_at IS NULL
          AND remote_verified_sha IS NULL
        )
        OR (
          status = 'rejected'
          AND approved_at IS NULL
          AND published_at IS NULL
          AND remote_verified_sha IS NULL
        )
        OR (
          status = 'published'
          AND approved_at IS NOT NULL
          AND published_at IS NOT NULL
          AND remote_verified_sha = commit_sha
        )
        OR (
          status IN ('stale', 'cancelled')
          AND published_at IS NULL
          AND remote_verified_sha IS NULL
        )
      ),
    CONSTRAINT ck_release_candidates_time_order
      CHECK (
        updated_at >= created_at
        AND (approved_at IS NULL OR approved_at >= created_at)
        AND (
          published_at IS NULL
          OR (
            approved_at IS NOT NULL
            AND published_at >= approved_at
          )
        )
      )
);

CREATE UNIQUE INDEX ux_release_candidates_approval
  ON release_candidates(approval_id)
  WHERE approval_id IS NOT NULL;

CREATE UNIQUE INDEX ux_release_candidates_task_active
  ON release_candidates(task_id)
  WHERE status IN ('pending_approval', 'approved');

CREATE INDEX ix_release_candidates_task_status_created
  ON release_candidates(task_id, status, created_at DESC);

CREATE INDEX ix_release_candidates_project_created
  ON release_candidates(project_id, created_at DESC);
```

安全 `binding_snapshot_json` 精确包含 schema version、provider、repository
external id/owner/name、default branch、workflow id 和 release ref prefix。
内部 snapshot hash 还覆盖 profile key、clone URL 和 credential ref，但内部对象
不进入 API、EventLog 或该 JSONB 字段。三类 hash 都复用
`stable_json_hash`，格式固定为 `sha256:<64 lowercase hex>`。

`target_ref` 固定为
`{release_ref_prefix}/{task_id}/{full_commit_sha}/{snapshot_hash_hex}`。
Candidate request canonical 固定包含
`schema_version=m7.release-candidate.request.v1`、
`action=approve_release_candidate`、Task、Project、PR record、binding、snapshot
hash、commit 和 target ref；其稳定 hash 写 `request_hash`，
`idempotency_key=release_candidate:v1:<request_hash hex>`。
Candidate 唯一身份为 `(pull_request_record_id, binding_snapshot_sha256)`；rejected
后重复 POST 返回原记录，不创建新审批。每 Task 同时只允许一个
`pending_approval|approved` candidate；published 是不可改写的历史发布事实。

#### ci_runs（M7）

```sql
CREATE TABLE ci_runs (
    id UUID PRIMARY KEY,
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id),
    release_candidate_id UUID NOT NULL UNIQUE REFERENCES release_candidates(id),
    provider TEXT NOT NULL DEFAULT 'gitea',
    external_run_id TEXT NOT NULL,
    external_job_id TEXT,
    workflow_id TEXT NOT NULL,
    workflow_revision TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    commit_sha TEXT NOT NULL,
    status TEXT NOT NULL,
    artifact_manifest_id UUID REFERENCES artifacts(id),
    image_index_digest TEXT,
    platform_manifest_digest TEXT,
    provider_updated_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    UNIQUE (provider, external_run_id)
);
```

`ci_runs` 只接收唯一 `workflow_dispatch` 对应的 run/job 状态。Webhook delivery id
只用于 delivery attempt 去重，业务幂等还必须校验 repository、run/job、
action/status、head SHA 和 provider update time。

#### workflow_jobs（M7）

```sql
CREATE TABLE workflow_jobs (
    id UUID PRIMARY KEY,
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    job_type TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id UUID NOT NULL,
    side_effect_class TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempt INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    lease_owner TEXT,
    lease_expires_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    next_retry_at TIMESTAMPTZ,
    cancel_requested_at TIMESTAMPTZ,
    dispatch_lease_owner TEXT,
    dispatch_lease_expires_at TIMESTAMPTZ,
    next_enqueue_at TIMESTAMPTZ DEFAULT now(),
    last_enqueued_at TIMESTAMPTZ,
    enqueue_attempt INTEGER NOT NULL DEFAULT 0,
    last_enqueue_error_code TEXT,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    result_json JSONB,
    error_code TEXT,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_workflow_jobs_task_type_idempotency
      UNIQUE (task_id, job_type, idempotency_key),
    CONSTRAINT ck_workflow_jobs_m7_2_handler
      CHECK (
        job_type = 'release_candidate_reconcile'
        AND resource_type = 'release_candidate'
        AND side_effect_class = 'none'
      ),
    CONSTRAINT ck_workflow_jobs_status
      CHECK (
        status IN (
          'pending',
          'claimed',
          'running',
          'succeeded',
          'failed',
          'cancel_requested',
          'cancelled',
          'recovery_required'
        )
      ),
    CONSTRAINT ck_workflow_jobs_request_hash
      CHECK (request_hash ~ '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT ck_workflow_jobs_idempotency_key
      CHECK (length(idempotency_key) BETWEEN 1 AND 180),
    CONSTRAINT ck_workflow_jobs_attempts
      CHECK (
        attempt >= 0
        AND max_attempts >= 1
        AND attempt <= max_attempts
      ),
    CONSTRAINT ck_workflow_jobs_payload_object
      CHECK (jsonb_typeof(payload_json) = 'object'),
    CONSTRAINT ck_workflow_jobs_result_object
      CHECK (result_json IS NULL OR jsonb_typeof(result_json) = 'object'),
    CONSTRAINT ck_workflow_jobs_worker_lease_pair
      CHECK ((lease_owner IS NULL) = (lease_expires_at IS NULL)),
    CONSTRAINT ck_workflow_jobs_dispatch_lease_pair
      CHECK (
        (dispatch_lease_owner IS NULL)
        = (dispatch_lease_expires_at IS NULL)
      ),
    CONSTRAINT ck_workflow_jobs_dispatch_lease_status
      CHECK (dispatch_lease_owner IS NULL OR status = 'pending'),
    CONSTRAINT ck_workflow_jobs_retry_enqueue
      CHECK (
        next_retry_at IS NULL
        OR (
          status = 'pending'
          AND next_enqueue_at IS NOT NULL
          AND next_enqueue_at >= next_retry_at
        )
      ),
    CONSTRAINT ck_workflow_jobs_enqueue_attempt
      CHECK (enqueue_attempt >= 0),
    CONSTRAINT ck_workflow_jobs_lifecycle
      CHECK (
        (
          status = 'pending'
          AND attempt < max_attempts
          AND lease_owner IS NULL
          AND heartbeat_at IS NULL
          AND finished_at IS NULL
          AND next_enqueue_at IS NOT NULL
        )
        OR (
          status = 'claimed'
          AND lease_owner IS NOT NULL
          AND heartbeat_at IS NOT NULL
          AND finished_at IS NULL
          AND next_retry_at IS NULL
          AND next_enqueue_at IS NULL
          AND dispatch_lease_owner IS NULL
        )
        OR (
          status IN ('running', 'cancel_requested')
          AND lease_owner IS NOT NULL
          AND heartbeat_at IS NOT NULL
          AND started_at IS NOT NULL
          AND finished_at IS NULL
          AND next_retry_at IS NULL
          AND next_enqueue_at IS NULL
          AND dispatch_lease_owner IS NULL
        )
        OR (
          status IN ('succeeded', 'failed', 'cancelled')
          AND lease_owner IS NULL
          AND finished_at IS NOT NULL
          AND next_retry_at IS NULL
          AND next_enqueue_at IS NULL
          AND dispatch_lease_owner IS NULL
        )
        OR (
          status = 'recovery_required'
          AND lease_owner IS NULL
          AND finished_at IS NULL
          AND next_retry_at IS NULL
          AND next_enqueue_at IS NULL
          AND dispatch_lease_owner IS NULL
        )
      ),
    CONSTRAINT ck_workflow_jobs_cancel
      CHECK (
        (status <> 'cancel_requested' OR cancel_requested_at IS NOT NULL)
        AND (status <> 'cancelled' OR cancel_requested_at IS NOT NULL)
        AND (
          cancel_requested_at IS NULL
          OR status IN (
            'cancel_requested',
            'succeeded',
            'failed',
            'cancelled',
            'recovery_required'
          )
        )
      ),
    CONSTRAINT ck_workflow_jobs_result_semantics
      CHECK (
        (status <> 'succeeded' OR (result_json IS NOT NULL AND error_code IS NULL))
        AND (
          status NOT IN ('failed', 'cancelled', 'recovery_required')
          OR error_code IS NOT NULL
        )
      ),
    CONSTRAINT ck_workflow_jobs_time_order
      CHECK (
        updated_at >= created_at
        AND (started_at IS NULL OR started_at >= created_at)
        AND (
          finished_at IS NULL
          OR finished_at >= COALESCE(started_at, created_at)
        )
        AND (heartbeat_at IS NULL OR heartbeat_at >= created_at)
        AND (
          lease_expires_at IS NULL
          OR (
            heartbeat_at IS NOT NULL
            AND lease_expires_at > heartbeat_at
          )
        )
        AND (
          cancel_requested_at IS NULL
          OR cancel_requested_at >= created_at
        )
        AND (
          last_enqueued_at IS NULL
          OR last_enqueued_at >= created_at
        )
      )
);

CREATE UNIQUE INDEX ux_workflow_jobs_blocking_resource
  ON workflow_jobs(job_type, resource_type, resource_id)
  WHERE status IN (
    'pending',
    'claimed',
    'running',
    'cancel_requested',
    'recovery_required'
  );

CREATE INDEX ix_workflow_jobs_task_created
  ON workflow_jobs(task_id, created_at DESC);

CREATE INDEX ix_workflow_jobs_resource_created
  ON workflow_jobs(resource_type, resource_id, created_at DESC);

CREATE INDEX ix_workflow_jobs_status_lease
  ON workflow_jobs(status, lease_expires_at)
  WHERE status IN ('claimed', 'running', 'cancel_requested');

CREATE INDEX ix_workflow_jobs_due_enqueue
  ON workflow_jobs(next_enqueue_at, id)
  WHERE status = 'pending';

CREATE INDEX ix_workflow_jobs_due_retry
  ON workflow_jobs(next_retry_at, id)
  WHERE status = 'pending' AND next_retry_at IS NOT NULL;
```

PostgreSQL `workflow_jobs` 是业务权威；Redis/Celery 只投递
`workflow_job_id`。M7-2 数据库 CHECK 暂时只允许
`release_candidate_reconcile -> release_candidate -> none`，后续新增 publish、
CI 或 deploy handler 时必须由新 migration 扩展映射。

dispatcher due 条件必须同时满足：

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

resource-blocking 状态为 pending/claimed/running/cancel_requested/
recovery_required；terminal 仅为 succeeded/failed/cancelled。
`recovery_required` 清空 lease，`finished_at` 保持 null，并阻止同资源新 job。
safe retry/stale reclaim 在 `attempt < max_attempts` 时回 pending；耗尽时进入
failed，写 `workflow_job_attempts_exhausted`、数据库完成时间并清 lease/retry/
enqueue。cancelled 必须写 `cancel_requested_at`。
worker 必须按
`Task -> WorkflowJob -> ProjectRepositoryBinding -> ReleaseCandidate -> Approval`
锁序使用短事务；Binding PUT 只按
`Binding -> Candidate(UUID 顺序) -> Approval(UUID 顺序)` 加锁且不反向获取
Task。状态不明时不得盲目重放 push、CI 或部署。

#### environments

```sql
CREATE TABLE environments (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    environment_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    base_url TEXT NOT NULL,
    env_profile_ref TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (environment_type IN ('staging', 'demo')),
    CHECK (status IN ('active', 'disabled', 'degraded')),
    UNIQUE (project_id, name)
);
```

M7 的 `environment_type` 只允许 `staging`、`demo`；`production` 是增强版。
`env_profile_ref` 是内部字段，M7-1 创建请求不接受也不返回。`base_url` 在本切片
只用于标识和展示；后续健康检查前必须经过服务端 profile/allowlist。

#### remote_targets

```sql
CREATE TABLE remote_targets (
    id UUID PRIMARY KEY,
    environment_id UUID NOT NULL REFERENCES environments(id) ON DELETE CASCADE,
    display_name TEXT NOT NULL,
    target_type TEXT NOT NULL DEFAULT 'linux_remote_agent',
    agent_id TEXT NOT NULL,
    agent_endpoint TEXT NOT NULL,
    credential_ref TEXT NOT NULL,
    tls_fingerprint TEXT NOT NULL,
    agent_version TEXT,
    capabilities_json JSONB NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'offline',
    last_heartbeat_at TIMESTAMPTZ,
    last_error_code TEXT,
    last_event_at TIMESTAMPTZ,
    last_status_changed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (environment_id, agent_id)
);
```

`agent_endpoint`、`credential_ref` 和 TLS 材料来自服务端受控 profile。读取 API
不返回 `credential_ref`，只返回脱敏 endpoint 与 fingerprint。M7 不保存
`host`、`ssh_user`、`kube_context` 或 `namespace` 作为可提交部署参数；
Kubernetes target 属于增强版独立 schema。

#### remote_agent_credentials

```sql
CREATE TABLE remote_agent_credentials (
    id UUID PRIMARY KEY,
    target_id UUID NOT NULL REFERENCES remote_targets(id) ON DELETE CASCADE,
    agent_id TEXT NOT NULL,
    key_id TEXT NOT NULL,
    credential_ref TEXT NOT NULL,
    scopes_json JSONB NOT NULL DEFAULT '[]',
    secret_fingerprint TEXT NOT NULL,
    active_from TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (target_id, key_id)
);
```

数据库只保存 secret 引用与 fingerprint。真实 secret 不进入数据库、API、事件
或日志；新旧 key 可短期重叠，原地替换同一 ref 的 secret 会被 fingerprint
校验阻断。

#### remote_agent_replay_nonces

```sql
CREATE TABLE remote_agent_replay_nonces (
    id UUID PRIMARY KEY,
    credential_id UUID NOT NULL
      REFERENCES remote_agent_credentials(id) ON DELETE CASCADE,
    nonce_hash TEXT NOT NULL,
    request_timestamp TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (credential_id, nonce_hash)
);
```

nonce 只保存 SHA-256；保留时间覆盖完整 timestamp 容差窗口，并由 PostgreSQL
唯一约束裁决并发 replay。

#### deployments

```sql
CREATE TABLE deployments (
    id UUID PRIMARY KEY,
    task_id UUID NOT NULL REFERENCES tasks(id),
    project_id UUID NOT NULL REFERENCES projects(id),
    environment_id UUID NOT NULL REFERENCES environments(id),
    remote_target_id UUID NOT NULL REFERENCES remote_targets(id),
    ci_run_id UUID NOT NULL REFERENCES ci_runs(id),
    release_plan_artifact_id UUID NOT NULL REFERENCES artifacts(id),
    commit_sha TEXT NOT NULL,
    image_ref TEXT NOT NULL,
    image_digest TEXT NOT NULL,
    platform_manifest_digest TEXT NOT NULL,
    release_version TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    approval_id UUID REFERENCES approval_requests(id),
    remote_operation_id TEXT,
    status TEXT NOT NULL,
    requested_by_actor TEXT NOT NULL,
    approved_by_actor TEXT,
    dispatched_by_agent_run_id UUID REFERENCES agent_runs(id),
    idempotency_key TEXT NOT NULL,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    rollback_candidate_id UUID REFERENCES deployments(id),
    rollback_request_artifact_id UUID REFERENCES artifacts(id),
    UNIQUE (task_id, idempotency_key),
    UNIQUE (environment_id, release_version)
);
```

M7 `deployments.status` 不包含 `restarting` 或 `rolled_back`。rollback request
只保存 candidate/plan；后续如实现执行，必须创建新的 Deployment 和独立审批。

#### service_instances

```sql
CREATE TABLE service_instances (
    id UUID PRIMARY KEY,
    deployment_id UUID NOT NULL REFERENCES deployments(id),
    environment_id UUID NOT NULL REFERENCES environments(id),
    remote_target_id UUID NOT NULL REFERENCES remote_targets(id),
    service_name TEXT NOT NULL,
    compose_project TEXT NOT NULL,
    runtime_type TEXT NOT NULL,
    runtime_ref TEXT,
    image_digest TEXT NOT NULL,
    status TEXT NOT NULL,
    health_url TEXT,
    last_health_check_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (deployment_id, service_name)
);
```

#### project_alerts（M8）

```sql
CREATE TABLE project_alerts (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id),
    environment_id UUID NOT NULL REFERENCES environments(id),
    service_instance_id UUID REFERENCES service_instances(id),
    alert_name TEXT NOT NULL,
    severity TEXT NOT NULL,
    status TEXT NOT NULL,
    source TEXT NOT NULL,
    labels JSONB NOT NULL DEFAULT '{}',
    annotations JSONB NOT NULL DEFAULT '{}',
    fired_at TIMESTAMPTZ NOT NULL,
    resolved_at TIMESTAMPTZ
);
```

#### remote_sessions（增强版，非 M7）

```sql
CREATE TABLE remote_sessions (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id),
    environment_id UUID NOT NULL REFERENCES environments(id),
    user_id TEXT NOT NULL,
    session_type TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at TIMESTAMPTZ
);
```

`remote_sessions`、终端 WebSocket 与任意命令审计只保留增强版设计；M7 migration、
API、控制台和验收不得创建或依赖该表。

---
