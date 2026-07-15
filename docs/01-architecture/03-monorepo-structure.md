# Monorepo 目录架构

> 来源：[设计书 7.1](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：定义未来代码仓库的推荐目录结构。
## 放置规则

- 桌面端进入 `apps/control-console`。
- 随 Desktop 分发的本机执行 sidecar 进入 `modules/local-runtime`。
- 平台后端、Agent、工具、远端控制、部署、监控等进入 `modules/*`。
- OpenAPI、事件 schema、工具 schema 等跨语言契约进入 `packages/shared-contracts`。
- 本地与远端基础设施配置进入 `infra`。

## 设计书摘录

### 7.1 推荐目录结构

```text
cloudhelm/
├── README.md
├── docs/
│   ├── architecture.md
│   ├── api.md
│   ├── requirements-and-design.md
│   ├── agent-workflow.md
│   ├── tool-permission.md
│   ├── remote-control.md
│   ├── deployment-targets.md
│   ├── monitoring-and-ops.md
│   ├── database-schema.md
│   ├── deployment.md
│   └── references.md
│
├── apps/
│   └── control-console/
│       ├── src-tauri/
│       ├── src/
│       │   ├── pages/
│       │   ├── components/
│       │   ├── features/
│       │   │   ├── requirement-editor/
│       │   │   ├── design-review/
│       │   │   ├── task-board/
│       │   │   ├── agent-timeline/
│       │   │   ├── diff-viewer/
│       │   │   ├── terminal-panel/
│       │   │   ├── approval-panel/
│       │   │   ├── remote-env-panel/
│       │   │   ├── deployment-panel/
│       │   │   └── observability-panel/
│       │   ├── api/
│       │   └── store/
│       └── package.json
│
├── modules/
│   ├── platform-api/
│   │   ├── app/
│   │   │   ├── routers/
│   │   │   ├── services/
│   │   │   ├── schemas/
│   │   │   ├── dependencies/
│   │   │   └── main.py
│   │   └── pyproject.toml
│   │
│   ├── orchestrator/
│   │   ├── workflows/
│   │   │   ├── requirement_to_feature.py
│   │   │   ├── scaffold_project.py
│   │   │   ├── issue_to_pr.py
│   │   │   ├── ci_failure_fix.py
│   │   │   └── incident_triage.py
│   │   ├── state_machines/
│   │   ├── policies/
│   │   └── tests/
│   │
│   ├── local-runtime/
│   │   ├── src/
│   │   ├── workspace/
│   │   ├── transport/
│   │   ├── policy/
│   │   └── tests/
│   │
│   ├── agent-runtime/
│   │   ├── agents/
│   │   │   ├── requirement_agent.py
│   │   │   ├── planner_agent.py
│   │   │   ├── architect_agent.py
│   │   │   ├── scaffold_agent.py
│   │   │   ├── coder_agent.py
│   │   │   ├── tester_agent.py
│   │   │   ├── reviewer_agent.py
│   │   │   ├── security_agent.py
│   │   │   ├── release_agent.py
│   │   │   └── sre_agent.py
│   │   ├── prompts/
│   │   ├── memory/
│   │   ├── llm/
│   │   └── tests/
│   │
│   ├── spec-store/
│   │   ├── requirements/
│   │   ├── adr/
│   │   ├── openapi/
│   │   ├── database-schema/
│   │   └── acceptance-criteria/
│   │
│   ├── tool-gateway/
│   │   ├── gateway/
│   │   │   ├── router.py
│   │   │   ├── permission.py
│   │   │   ├── approval.py
│   │   │   ├── audit.py
│   │   │   ├── rate_limit.py
│   │   │   └── mcp_client.py
│   │   └── tests/
│   │
│   ├── toolservers/
│   │   ├── requirement-tool/
│   │   │   ├── server.py
│   │   │   └── tools/
│   │   │       ├── parse_requirement.py
│   │   │       ├── generate_acceptance_criteria.py
│   │   │       └── update_spec.py
│   │   ├── design-tool/
│   │   │   ├── server.py
│   │   │   └── tools/
│   │   │       ├── generate_api_design.py
│   │   │       ├── generate_db_design.py
│   │   │       └── update_technical_plan.py
│   │   ├── scaffold-tool/
│   │   │   ├── server.py
│   │   │   └── tools/
│   │   │       ├── list_templates.py
│   │   │       ├── generate_project.py
│   │   │       ├── generate_module.py
│   │   │       └── generate_ci_config.py
│   │   ├── repo-tool/
│   │   │   ├── server.py
│   │   │   └── tools/
│   │   │       ├── read_file.py
│   │   │       ├── write_file.py
│   │   │       └── search_code.py
│   │   ├── git-tool/
│   │   │   ├── server.py
│   │   │   └── tools/
│   │   │       ├── status.py
│   │   │       ├── diff.py
│   │   │       ├── branch.py
│   │   │       ├── commit.py
│   │   │       └── create_pr.py
│   │   ├── sandbox-tool/
│   │   │   ├── server.py
│   │   │   └── tools/
│   │   │       ├── exec.py
│   │   │       ├── run_tests.py
│   │   │       └── collect_artifacts.py
│   │   ├── browser-tool/
│   │   │   ├── server.py
│   │   │   └── playwright/
│   │   ├── ci-tool/
│   │   ├── deploy-tool/
│   │   │   ├── server.py
│   │   │   └── tools/
│   │   │       ├── deploy_staging.py
│   │   │       ├── check_release.py
│   │   │       ├── rollback.py
│   │   │       └── render_manifest.py
│   │   ├── remote-control-tool/
│   │   │   ├── server.py
│   │   │   └── tools/
│   │   │       ├── ssh_exec.py
│   │   │       ├── stream_logs.py
│   │   │       ├── service_status.py
│   │   │       └── open_terminal.py
│   │   ├── security-tool/
│   │   ├── observability-tool/
│   │   └── approval-tool/
│   │
│   ├── sandbox-runner/
│   │   ├── images/
│   │   ├── runner/
│   │   ├── workspace-manager/
│   │   └── cleanup/
│   │
│   ├── remote-control-plane/
│   │   ├── connections/
│   │   ├── sessions/
│   │   ├── ssh/
│   │   ├── websocket/
│   │   └── audit/
│   │
│   ├── remote-agent/
│   │   ├── heartbeat/
│   │   ├── command-runner/
│   │   ├── log-streamer/
│   │   ├── metrics-exporter/
│   │   └── service-discovery/
│   │
│   ├── deployment-controller/
│   │   ├── targets/
│   │   ├── strategies/
│   │   │   ├── docker_compose.py
│   │   │   ├── ansible.py
│   │   │   ├── kubernetes.py
│   │   │   └── gitops.py
│   │   ├── release_plan.py
│   │   ├── rollback_plan.py
│   │   └── health_check.py
│   │
│   ├── monitoring-collector/
│   │   ├── prometheus/
│   │   ├── loki/
│   │   ├── alertmanager/
│   │   ├── synthetic-checks/
│   │   └── incident-events/
│   │
│   ├── workflow-engine/
│   │   ├── queue.py
│   │   ├── workers.py
│   │   ├── retry.py
│   │   └── scheduler.py
│   │
│   ├── policy-engine/
│   │   ├── rules/
│   │   │   ├── tool_permissions.rego
│   │   │   └── deployment_policy.rego
│   │   ├── evaluator.py
│   │   └── tests/
│   │
│   ├── audit-log/
│   │   ├── event_store.py
│   │   ├── append_event.py
│   │   └── replay.py
│   │
│   └── integrations/
│       ├── gitea/
│       ├── github/
│       ├── ssh/
│       ├── ansible/
│       ├── docker/
│       ├── kubernetes/
│       ├── argocd/
│       ├── prometheus/
│       ├── grafana-loki/
│       ├── alertmanager/
│       ├── sentry/
│       └── notification/
│
├── packages/
│   ├── shared-contracts/
│   │   ├── openapi.yaml
│   │   ├── events.schema.json
│   │   ├── tool.schema.json
│   │   ├── task.schema.json
│   │   ├── requirement.schema.json
│   │   └── technical-design.schema.json
│   ├── python-sdk/
│   └── typescript-sdk/
│
├── database/
│   ├── migrations/
│   ├── seed/
│   └── schema.sql
│
├── infra/
│   ├── desktop/
│   │   ├── windows/
│   │   ├── linux/
│   │   └── release/
│   ├── ops-hub/
│   │   ├── compose.yaml
│   │   ├── install.sh
│   │   ├── upgrade.sh
│   │   ├── backup.sh
│   │   └── restore.sh
│   ├── docker-compose/
│   │   ├── docker-compose.dev.yml
│   │   └── docker-compose.observability.yml
│   ├── remote-agent/
│   ├── ansible/
│   ├── cloud-init/
│   ├── k8s/
│   ├── helm/
│   └── scripts/
│
├── examples/
│   ├── sample-repo-python/
│   │   ├── cloudhelm.project.yaml
│   │   └── cloudhelm.env.schema.json
│   ├── sample-repo-node/
│   └── demo-issues/
│
└── tests/
    ├── integration/
    ├── e2e/
    └── fixtures/
```
