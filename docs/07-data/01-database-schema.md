# 数据库关键表总览

> 来源：[设计书 11.2](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：汇总所有关键表结构、实现状态与未来 migration；单表文档放在 tables
> 目录。Desktop/Ops Hub/业务项目的数据所有权见
> [02-storage-boundary.md](02-storage-boundary.md)。

## 数据所有权边界

CloudHelm 目标架构存在三类互不复用的数据库：

|数据域|数据库|权威性|
|---|---|---|
|Ops Hub Task、Agent、审批、事件、WorkflowJob、用户/RBAC、部署和审计|PostgreSQL + Alembic|平台权威|
|Desktop server profile、UI 设置、草稿、缓存、事件游标|SQLite + 独立 migration chain|非权威、可重建|
|Agent 生成业务项目的领域数据|由业务项目自行选择|业务项目权威|

Desktop、Local Runtime、Remote Agent 和业务项目均不得直连或复用 Ops Hub
PostgreSQL schema。当前 `infra/docker-compose.dev.yml` 的 PostgreSQL 是仓库开发
依赖，不是 Windows/Linux Desktop 安装器依赖。

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

`ProjectRepositoryBinding`、`ReleaseCandidate`、`WorkflowJob` 和资源型
Approval 字段已由 `20260716_0008` 建立 migration 与 ORM 数据底座。该结论只表示
M7-2A 数据结构已经进入实现与数据库门禁。M7-2B1 已进一步交付
RepositoryProfile、Binding PUT/GET、幂等、漂移失效和并发门禁；M7-2B2 已交付
Candidate 原子创建、第一道审批 approve/reject、freshness 门禁、pending
`release_candidate_reconcile` WorkflowJob 和精确事件；M7-2C 已进一步交付
durable dispatcher/worker、lease/heartbeat、retry、Redis 补投和 stale reclaim。

`CIRun`、`Deployment` 和 `ServiceInstance` 已由 `20260716_0009` 建立 migration、
ORM、repository、严格 Pydantic/JSON Schema 与真实 PostgreSQL 门禁。该结论只
表示 M7-2D 数据底座完成，不表示 candidate ref、Gitea CI、ReleasePlan、
Deployment API/worker、Controller 或 Remote Agent operation 已交付。M7 不创建
production、Kubernetes target 或 `remote_sessions`。

M7-2 数据底座固定以下迁移语义：repository 字段统一使用
`repository_external_id`；candidate 保存安全 binding snapshot JSON 与覆盖内部
配置的 snapshot hash，状态包含 rejected；远端校验字段统一为
`remote_verified_sha`；WorkflowJob 唯一身份为
`(task_id, job_type, idempotency_key)`，并保存 side-effect class、dispatch lease
与 enqueue 补偿字段。M7-2B/C 必须复用这些字段与约束，不得另建平行状态源。

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

## M9 用户/RBAC 与离线同步 migration 目标

以下内容均为规划，当前 `0.5.1` 与已落地的 `20260716_0008` M7-2A 数据底座
都未实现：

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

授权模型固定为：

```text
role permissions
  + system/project/environment scope
  + resource attributes/version
  + domain separation-of-duty
```

关键约束：

- API 的 `scope_id` 在数据库物化为 nullable `project_id/environment_id`：
  system 两者为空、project 仅 project 非空、environment 两者非空，并使用
  `(environment_id, project_id)` 复合外键保证资源归属。
- 同一 user/role/scope 只允许一个 active binding。
- refresh token 只保存 hash，并按 token family 轮换与撤销。
- 已轮换 refresh token 的 hash 历史用于检测旧 token 重用。
- `user_sessions.session_type` 区分 Desktop 与 Local Runtime；Local Runtime session
  的 token family 为空，只签发短期 device-bound access token。
- 邀请 token 只保存 hash、单次消费；全局 security state 保存
  `permission_version` 和 bootstrap 完成状态。
- 用户、Desktop device/session、Local Runtime device 和 Remote Agent machine
  identity 分离。
- Desktop 与 Local Runtime 都只在服务端保存 Ed25519 public key/fingerprint/
  version，private key 只进入本机 OS credential store。
- fingerprint 对解码后的 32-byte public key 求 SHA-256，格式为
  `sha256:<lowercase hex>`；首次 version 固定为 1，M9 不提供原地 key rotation。
- Local Runtime pairing challenge 只保存 one-time code hash、发起 user/Desktop
  device、请求 public id/public key/fingerprint、TTL、消费状态和失败次数；
  明文 code 与 private key 不落库。
- `approval_requests`、`tasks`、`tool_calls`、`deployments` 和 `event_logs`
  后续增加真实 user actor 引用；请求体自报 `actor_id` 不作为授权身份。
- `technical_designs` 后续增加当前版本的 user/AgentRun 修改者与 content hash，
  支撑“最后修改者或其 AgentRun 发起者不得批准当前设计”。
- System Owner 也不能绕过 release/deployment 自批门禁。

为支持 Desktop 长时间离线补齐，`event_logs` 后续 migration 增加：

```text
sequence BIGINT
stream_kind TEXT
project_id UUID
aggregate_type TEXT
aggregate_id UUID
aggregate_version BIGINT
schema_version TEXT
actor_user_id UUID
actor_device_id UUID
actor_session_id UUID
subject_user_id UUID
```

`sequence` 是同一 Ops Hub 内单调递增的同步位置；现有 UUID `id` 继续作为事件
唯一身份。`stream_kind` 固定为 `project | user_control | system_audit`：
project 流必须有 `project_id`，user_control 流必须有 `subject_user_id`；
`actor_user_id` 是执行者而 `subject_user_id` 是受影响用户。Desktop SQLite 按
`ops_hub_id + user_id + stream_kind + scope_id` 保存独立的最后已应用 sequence，
不复制 `event_logs` 或其他 PostgreSQL 表。

未来 migration 至少建立 `UNIQUE(sequence)`、
`(project_id, sequence)` 和 `(subject_user_id, sequence)` 索引；后者只服务
user_control 流，`/api/me/events*` 不扫描 payload。

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
    version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

M9 为 Design approval 职责分离增加
`last_modified_source`、`last_modified_by_user_id`、
`last_modified_by_agent_run_id` 和 `content_sha256`。`user/agent_run` source
分别要求对应引用恰有一项非空；`legacy_system` 只用于 migration 历史回填且两项
均为空。`content_sha256` 使用统一 `stable_json_hash` 覆盖
`schema/design_type/content_markdown/openapi_json/db_schema_json/mermaid_diagram/
risk_level/version`。审批绑定当前 `technical_design_id + version + content_sha256`；
Agent 修改者通过 `agent_runs.initiated_by_user_id` 解析当前版本的人类发起者。

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

#### event_logs（当前已实现结构）

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

M9 的 sequence/stream/project/aggregate/schema、user/device/session actor 和
subject user 字段按本文件前述未来 migration 增加；当前 DDL 不得被误写成已经
支持 Desktop 跨项目离线同步或用户控制流。

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
        AND release_ref_prefix !~ '[[:cntrl:]]'
        AND position('[' IN release_ref_prefix) = 0
        AND position(chr(92) IN release_ref_prefix) = 0
        AND position('..' IN release_ref_prefix) = 0
        AND position('//' IN release_ref_prefix) = 0
        AND position('@{' IN release_ref_prefix) = 0
        AND release_ref_prefix !~ '(^|/)[.]'
        AND release_ref_prefix !~ '[.]lock(/|$)'
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
        AND jsonb_typeof(
          binding_snapshot_json->'schema_version'
        ) = 'string'
        AND jsonb_typeof(
          binding_snapshot_json->'provider'
        ) = 'string'
        AND jsonb_typeof(
          binding_snapshot_json->'repository_external_id'
        ) = 'string'
        AND jsonb_typeof(
          binding_snapshot_json->'repository_owner'
        ) = 'string'
        AND jsonb_typeof(
          binding_snapshot_json->'repository_name'
        ) = 'string'
        AND jsonb_typeof(
          binding_snapshot_json->'default_branch'
        ) = 'string'
        AND jsonb_typeof(
          binding_snapshot_json->'workflow_id'
        ) = 'string'
        AND jsonb_typeof(
          binding_snapshot_json->'release_ref_prefix'
        ) = 'string'
        AND length(
          btrim(binding_snapshot_json->>'repository_external_id')
        ) BETWEEN 1 AND 255
        AND length(
          btrim(binding_snapshot_json->>'repository_owner')
        ) BETWEEN 1 AND 255
        AND length(
          btrim(binding_snapshot_json->>'repository_name')
        ) BETWEEN 1 AND 255
        AND length(
          btrim(binding_snapshot_json->>'default_branch')
        ) BETWEEN 1 AND 255
        AND length(
          btrim(binding_snapshot_json->>'workflow_id')
        ) BETWEEN 1 AND 512
        AND left(
          binding_snapshot_json->>'release_ref_prefix',
          11
        ) = 'refs/heads/'
        AND length(
          binding_snapshot_json->>'release_ref_prefix'
        ) BETWEEN 12 AND 240
        AND binding_snapshot_json->>'release_ref_prefix'
          !~ '[[:space:]~^:?*]'
        AND binding_snapshot_json->>'release_ref_prefix'
          !~ '[[:cntrl:]]'
        AND position(
          '[' IN binding_snapshot_json->>'release_ref_prefix'
        ) = 0
        AND position(
          chr(92) IN binding_snapshot_json->>'release_ref_prefix'
        ) = 0
        AND position(
          '..' IN binding_snapshot_json->>'release_ref_prefix'
        ) = 0
        AND position(
          '//' IN binding_snapshot_json->>'release_ref_prefix'
        ) = 0
        AND position(
          '@{' IN binding_snapshot_json->>'release_ref_prefix'
        ) = 0
        AND binding_snapshot_json->>'release_ref_prefix'
          !~ '(^|/)[.]'
        AND binding_snapshot_json->>'release_ref_prefix'
          !~ '[.]lock(/|$)'
        AND right(
          binding_snapshot_json->>'release_ref_prefix',
          1
        ) NOT IN ('.', '/')
        AND binding_snapshot_json->>'release_ref_prefix'
          NOT LIKE '%.lock'
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
        AND target_ref !~ '[[:cntrl:]]'
        AND position('[' IN target_ref) = 0
        AND position(chr(92) IN target_ref) = 0
        AND position('..' IN target_ref) = 0
        AND position('//' IN target_ref) = 0
        AND position('@{' IN target_ref) = 0
        AND target_ref !~ '(^|/)[.]'
        AND target_ref !~ '[.]lock(/|$)'
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
          AND remote_verified_sha IS NOT NULL
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
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    pull_request_record_id UUID NOT NULL
      REFERENCES pull_request_records(id) ON DELETE NO ACTION,
    release_candidate_id UUID NOT NULL UNIQUE
      REFERENCES release_candidates(id) ON DELETE NO ACTION,
    provider TEXT NOT NULL DEFAULT 'gitea',
    repository_external_id TEXT NOT NULL,
    external_run_id TEXT,
    external_job_id TEXT,
    workflow_id TEXT NOT NULL,
    workflow_revision TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    commit_sha TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'triggered',
    idempotency_key TEXT NOT NULL,
    last_event_action TEXT,
    last_event_status TEXT,
    last_delivery_id TEXT,
    provider_head_sha TEXT,
    provider_updated_at TIMESTAMPTZ,
    artifact_manifest_id UUID REFERENCES artifacts(id) ON DELETE NO ACTION,
    image_index_digest TEXT,
    platform_manifest_digest TEXT,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (task_id, idempotency_key)
);
```

`ci_runs` 只接收唯一 `workflow_dispatch` 对应的 run/job 状态。Webhook delivery id
只用于 delivery attempt 去重，业务幂等还必须校验 repository、run/job、
action/status、head SHA 和 provider update time。状态固定为
`triggered/running/passed/failed/cancelled`；passed 必须同时绑定 manifest、
image index digest、platform manifest digest、started/finished 和与 commit 一致的
provider head SHA，其他状态不得伪造 passed 证据。`external_run_id` 仅在
`triggered` 的 provider run 尚未关联窗口可空，`running/passed` 必须具有真实
run identity；最后 event 四字段必须全空或全有。

`workflow_revision` 保存 Gitea workflow 的稳定有界 revision 文本，不假设它一定是
commit SHA。`release_candidate_id` 唯一；非空
`(provider, repository_external_id, external_run_id)` 使用部分唯一索引。

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

M7-2C 已按下述 due、lease、retry 和 reclaim 规则运行；当前 registry 仍只允许
无外部副作用的 `release_candidate_reconcile`。

dispatcher due 条件必须同时满足：

```sql
tasks.status IN ('running', 'waiting_approval')
AND workflow_jobs.status = 'pending'
AND workflow_jobs.attempt < workflow_jobs.max_attempts
AND (
  workflow_jobs.next_retry_at IS NULL
  OR workflow_jobs.next_retry_at <= clock_timestamp()
)
AND workflow_jobs.next_enqueue_at <= clock_timestamp()
AND (
  workflow_jobs.dispatch_lease_expires_at IS NULL
  OR workflow_jobs.dispatch_lease_expires_at <= clock_timestamp()
)
```

resource-blocking 状态为 pending/claimed/running/cancel_requested/
recovery_required；terminal 仅为 succeeded/failed/cancelled。
`recovery_required` 清空 lease，`finished_at` 保持 null，并阻止同资源新 job。
safe retry/stale reclaim 在 `attempt < max_attempts` 时回 pending；耗尽时进入
failed，写 `workflow_job_attempts_exhausted`、数据库完成时间并清 lease/retry/
enqueue。cancelled 必须写 `cancel_requested_at`。
worker/reclaimer 必须先无锁读取 identity hint，再按
`Task -> WorkflowJob -> ProjectRepositoryBinding -> ReleaseCandidate -> Approval`
锁序使用短事务；全部资源锁完成后重新读取一次 `clock_timestamp()` 并重验
owner/lease/expiry。Binding PUT 先取得 RepositoryBinding 配置 namespace 的
transaction-level advisory lock，再按
`Binding -> Candidate(UUID 顺序) -> Approval(UUID 顺序)` 加锁且不反向获取
Task。advisory lock 只串行化短事务中的 repository identity 变更，避免跨 Project
identity swap 死锁。状态不明时不得盲目重放 push、CI 或部署。

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
    status TEXT NOT NULL DEFAULT 'planned',
    health_summary_json JSONB,
    failure_code TEXT,
    failure_summary TEXT,
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
状态固定为 `planned/pending_approval/queued/deploying/verifying/healthy/unhealthy/
failed/rollback_requested/cancelled`。从 `pending_approval` 起绑定 Approval，
从 `queued` 起保存 approved actor，运行态必须绑定 operation 与 started time，
健康终态必须保存 JSON object health summary，failed 必须保存稳定 failure code。
`rollback_requested` 还必须具有 L3 Approval、approved actor、operation、
started/finished、health summary、另一条历史 healthy Deployment 和 rollback
request Artifact，且禁止自引用。

`image_ref` 只允许一个 digest 分隔 `@`，拒绝 URL scheme/userinfo；健康对象最多
32 个小写受控 key，value 只允许最长 512 字符 string、number、boolean 或 null，
并拒绝凭据、敏感字段和 raw logs/stdout/stderr/log。

Deployment Approval 的数据库组合固定为
`approve_deployment + deployment + L3 + requested_by_agent_run_id`；其他 action
不得冒充 deployment resource，两类资源审批 action 也不得省略 resource identity
后借 SQL NULL 绕过。ReleasePlan 内容 hash 继续使用不可变
`artifacts.sha256`，本表不复制可漂移的第二份 plan hash。

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
    status TEXT NOT NULL DEFAULT 'starting',
    health_url TEXT,
    health_result_json JSONB,
    last_health_check_at TIMESTAMPTZ,
    last_error_code TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (deployment_id, service_name)
);
```

M7 `runtime_type` 固定为 `docker_compose`，status 固定为
`starting/running/healthy/unhealthy/stopped/failed`，不增加 `unknown`。healthy
或 unhealthy 必须同时保存 JSON object health result 与 check time，failed 必须
保存稳定 last error code，health URL 不接受 userinfo。健康对象沿用 Deployment
的受控 key/scalar 和敏感字段拒绝规则。Environment、RemoteTarget 和 digest 与
父 Deployment 的一致性由后续 service 在锁内重验。

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
