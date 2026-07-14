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

## M7 目标迁移边界

以下 M7 表结构是 `0.6.0` 的目标设计，只有 migration、ORM、repository/service、
黑盒/白盒测试和真实远端 E2E 全部落地后才能写成已实现。M7 只支持
staging/demo Linux Remote Agent，不创建 production、Kubernetes target 或
`remote_sessions`。

M7 数据门禁固定为：

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
    task_id UUID NOT NULL REFERENCES tasks(id),
    action TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    reason TEXT NOT NULL,
    resource_type TEXT,
    resource_id UUID,
    request_hash TEXT,
    status TEXT NOT NULL,
    requested_by_agent_run_id UUID REFERENCES agent_runs(id),
    decided_by TEXT,
    decided_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    consumed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
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
    project_id UUID NOT NULL UNIQUE REFERENCES projects(id),
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
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

API 只接受 `profile_key`，读取响应不返回 `credential_ref`，也不允许普通调用方
自由提交 clone URL、workflow path 或 refspec。

#### release_candidates（M7）

```sql
CREATE TABLE release_candidates (
    id UUID PRIMARY KEY,
    task_id UUID NOT NULL REFERENCES tasks(id),
    project_id UUID NOT NULL REFERENCES projects(id),
    pull_request_record_id UUID NOT NULL REFERENCES pull_request_records(id),
    repository_binding_id UUID NOT NULL REFERENCES project_repository_bindings(id),
    commit_sha TEXT NOT NULL,
    target_ref TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    approval_id UUID REFERENCES approval_requests(id),
    remote_verified_sha TEXT,
    status TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at TIMESTAMPTZ,
    UNIQUE (task_id, idempotency_key),
    UNIQUE (repository_binding_id, target_ref)
);
```

#### ci_runs（M7）

```sql
CREATE TABLE ci_runs (
    id UUID PRIMARY KEY,
    task_id UUID NOT NULL REFERENCES tasks(id),
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
    task_id UUID NOT NULL REFERENCES tasks(id),
    job_type TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id UUID NOT NULL,
    request_hash TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    status TEXT NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 1,
    lease_owner TEXT,
    lease_expires_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    next_retry_at TIMESTAMPTZ,
    cancel_requested_at TIMESTAMPTZ,
    payload_json JSONB NOT NULL DEFAULT '{}',
    result_json JSONB,
    error_code TEXT,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (task_id, idempotency_key)
);
```

PostgreSQL `workflow_jobs` 是业务权威；Redis/Celery 只投递
`workflow_job_id`。worker 必须用短事务 claim/lease/heartbeat，状态不明时进入
`recovery_required`，不得盲目重放 push、CI 或部署。

#### environments

```sql
CREATE TABLE environments (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id),
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    status TEXT NOT NULL,
    base_url TEXT,
    env_profile_ref TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, name)
);
```

M7 的 `type` 只允许 `staging`、`demo`；`production` 是增强版。

#### remote_targets

```sql
CREATE TABLE remote_targets (
    id UUID PRIMARY KEY,
    environment_id UUID NOT NULL REFERENCES environments(id),
    display_name TEXT NOT NULL,
    target_type TEXT NOT NULL DEFAULT 'linux_remote_agent',
    agent_id TEXT NOT NULL,
    agent_endpoint TEXT NOT NULL,
    credential_ref TEXT NOT NULL,
    tls_fingerprint TEXT NOT NULL,
    agent_version TEXT,
    capabilities JSONB NOT NULL DEFAULT '[]',
    status TEXT NOT NULL,
    last_heartbeat_at TIMESTAMPTZ,
    last_error_code TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (environment_id, agent_id)
);
```

`agent_endpoint`、`credential_ref` 和 TLS 材料来自服务端受控 profile。读取 API
不返回 `credential_ref`，只返回脱敏 endpoint 与 fingerprint。M7 不保存
`host`、`ssh_user`、`kube_context` 或 `namespace` 作为可提交部署参数；
Kubernetes target 属于增强版独立 schema。

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
