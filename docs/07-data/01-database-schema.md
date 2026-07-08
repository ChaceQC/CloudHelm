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
    status TEXT NOT NULL,
    requested_by_agent_run_id UUID REFERENCES agent_runs(id),
    decided_by TEXT,
    decided_at TIMESTAMPTZ,
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

#### environments

```sql
CREATE TABLE environments (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id),
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    status TEXT NOT NULL,
    base_url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

#### remote_targets

```sql
CREATE TABLE remote_targets (
    id UUID PRIMARY KEY,
    environment_id UUID NOT NULL REFERENCES environments(id),
    target_type TEXT NOT NULL,
    host TEXT,
    ssh_user TEXT,
    agent_id TEXT,
    kube_context TEXT,
    namespace TEXT,
    status TEXT NOT NULL,
    last_heartbeat_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

#### deployments

```sql
CREATE TABLE deployments (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id),
    environment_id UUID NOT NULL REFERENCES environments(id),
    commit_sha TEXT NOT NULL,
    image_tag TEXT,
    release_version TEXT NOT NULL,
    status TEXT NOT NULL,
    deployed_by TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    rollback_from UUID REFERENCES deployments(id)
);
```

#### service_instances

```sql
CREATE TABLE service_instances (
    id UUID PRIMARY KEY,
    deployment_id UUID NOT NULL REFERENCES deployments(id),
    environment_id UUID NOT NULL REFERENCES environments(id),
    service_name TEXT NOT NULL,
    runtime_type TEXT NOT NULL,
    runtime_ref TEXT,
    status TEXT NOT NULL,
    health_url TEXT,
    last_health_check_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

#### project_alerts

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

#### remote_sessions

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

---
