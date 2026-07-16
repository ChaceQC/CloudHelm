# 数据模型文档

核心实体、数据库 schema 和单表文档。

## 细化参考

- [数据模型细化设计](../15-detailed-design/04-data-detail.md)

## 文件

- [00-entity-model.md](00-entity-model.md)
- [01-database-schema.md](01-database-schema.md)
- [02-storage-boundary.md](02-storage-boundary.md)
- [tables/agent_conversations.md](tables/agent_conversations.md)
- [tables/agent_runs.md](tables/agent_runs.md)
- [tables/approval_requests.md](tables/approval_requests.md)
- [tables/artifacts.md](tables/artifacts.md)
- [tables/ci_runs.md](tables/ci_runs.md)
- [tables/development_plans.md](tables/development_plans.md)
- [tables/deployments.md](tables/deployments.md)
- [tables/environments.md](tables/environments.md)
- [tables/event_logs.md](tables/event_logs.md)
- [tables/project_alerts.md](tables/project_alerts.md)
- [tables/projects.md](tables/projects.md)
- [tables/project_repository_bindings.md](tables/project_repository_bindings.md)
- [tables/pull_request_records.md](tables/pull_request_records.md)
- [tables/release_candidates.md](tables/release_candidates.md)
- [tables/remote_agent_credentials.md](tables/remote_agent_credentials.md)
- [tables/remote_agent_replay_nonces.md](tables/remote_agent_replay_nonces.md)
- [tables/remote_sessions.md](tables/remote_sessions.md)

M9 规划的 users/devices/sessions/invitations/roles/permissions/bindings/security
state 当前统一定义在
[../15-detailed-design/11-identity-access-control.md](../15-detailed-design/11-identity-access-control.md)；
开始对应 migration 时再创建逐表文档，不能把规划表写成当前已落地。
- [tables/remote_targets.md](tables/remote_targets.md)
- [tables/requirement_specs.md](tables/requirement_specs.md)
- [tables/service_instances.md](tables/service_instances.md)
- [tables/tasks.md](tables/tasks.md)
- [tables/technical_designs.md](tables/technical_designs.md)
- [tables/tool_calls.md](tables/tool_calls.md)
- [tables/workflow_jobs.md](tables/workflow_jobs.md)
