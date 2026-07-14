# CloudHelm 文档索引

> 来源设计书：[云舵 CloudHelm 毕设设计书.md](../云舵 CloudHelm 毕设设计书.md)  
> 生成目标：按项目架构和技术栈，将每个部分拆成独立文档并按层级放置。

## 目录层级

|目录|说明|
|---|---|
|[项目概览](00-project/README.md)|项目定位、目标与参考资料。|
|[架构文档](01-architecture/README.md)|总体架构、边界、原则和 Monorepo 结构。|
|[技术栈文档](02-tech-stack/README.md)|总体技术栈、MVP 技术组合和远端运维采集链路。|
|[模块文档](03-modules/README.md)|按 Monorepo 层级为每个应用、模块、包和基础设施生成的说明。|
|[Agent 文档](04-agents/README.md)|Agent 角色、状态机、结构化输出和单 Agent 职责。|
|[工具层文档](05-tool-layer/README.md)|Tool Gateway、风险等级、MCP Server 和 MVP 工具组。|
|[业务流程文档](06-workflows/README.md)|开发到 PR、PR 到部署、CI 修复、告警 Runbook 和远程接管流程。|
|[数据模型文档](07-data/README.md)|核心实体、数据库 schema 和单表文档。|
|[API 文档](08-api/README.md)|Task、Requirement/Design、Agent Run、Tool Call、Approval、Event、Deployment、Remote Ops、Monitoring API。|
|[桌面端控制台文档](09-control-console/README.md)|页面结构和关键交互。|
|[安全文档](10-security/README.md)|安全边界、权限策略和审计记录。|
|[可观测性文档](11-observability/README.md)|指标、日志和 trace 设计。|
|[部署文档](12-deployment/README.md)|本地开发部署、远端演示部署、答辩环境和生产扩展。|
|[测试文档](13-testing/README.md)|单元测试、集成测试和 E2E 演示测试。|
|[路线与验收文档](14-roadmap/README.md)|阶段计划、总排期流程、创新风险成果、MVP 验收和扩展方向。|
|[细化设计文档](15-detailed-design/README.md)|MVP 裁剪线、模块契约、Agent/Tool 契约、API/Data/Workflow 细化、部署观测和验收矩阵。|

## 文档清单

### 项目概览

- [00-project/00-project-positioning.md](00-project/00-project-positioning.md)
- [00-project/01-goals.md](00-project/01-goals.md)
- [00-project/02-references.md](00-project/02-references.md)

### 架构文档

- [01-architecture/00-system-architecture.md](01-architecture/00-system-architecture.md)
- [01-architecture/01-local-remote-boundary.md](01-architecture/01-local-remote-boundary.md)
- [01-architecture/02-core-principles.md](01-architecture/02-core-principles.md)
- [01-architecture/03-monorepo-structure.md](01-architecture/03-monorepo-structure.md)

### 技术栈文档

- [02-tech-stack/00-overall-tech-stack.md](02-tech-stack/00-overall-tech-stack.md)
- [02-tech-stack/01-agent-guided-development-stack.md](02-tech-stack/01-agent-guided-development-stack.md)
- [02-tech-stack/02-mvp-stack.md](02-tech-stack/02-mvp-stack.md)
- [02-tech-stack/03-remote-ops-stack.md](02-tech-stack/03-remote-ops-stack.md)
- [02-tech-stack/04-remote-data-collection-chain.md](02-tech-stack/04-remote-data-collection-chain.md)

### 模块文档

- [03-modules/00-module-map.md](03-modules/00-module-map.md)
- [03-modules/apps/control-console.md](03-modules/apps/control-console.md)
- [03-modules/database.md](03-modules/database.md)
- [03-modules/examples.md](03-modules/examples.md)
- [03-modules/infra.md](03-modules/infra.md)
- [03-modules/modules/agent-runtime.md](03-modules/modules/agent-runtime.md)
- [03-modules/modules/audit-log.md](03-modules/modules/audit-log.md)
- [03-modules/modules/deployment-controller.md](03-modules/modules/deployment-controller.md)
- [03-modules/modules/integrations.md](03-modules/modules/integrations.md)
- [03-modules/modules/monitoring-collector.md](03-modules/modules/monitoring-collector.md)
- [03-modules/modules/orchestrator.md](03-modules/modules/orchestrator.md)
- [03-modules/modules/platform-api.md](03-modules/modules/platform-api.md)
- [03-modules/modules/policy-engine.md](03-modules/modules/policy-engine.md)
- [03-modules/modules/remote-agent.md](03-modules/modules/remote-agent.md)
- [03-modules/modules/remote-control-plane.md](03-modules/modules/remote-control-plane.md)
- [03-modules/modules/sandbox-runner.md](03-modules/modules/sandbox-runner.md)
- [03-modules/modules/spec-store.md](03-modules/modules/spec-store.md)
- [03-modules/modules/tool-gateway.md](03-modules/modules/tool-gateway.md)
- [03-modules/modules/toolservers.md](03-modules/modules/toolservers.md)
- [03-modules/modules/workflow-engine.md](03-modules/modules/workflow-engine.md)
- [03-modules/packages/shared-contracts.md](03-modules/packages/shared-contracts.md)
- [03-modules/tests.md](03-modules/tests.md)

### Agent 文档

- [04-agents/00-agent-layer.md](04-agents/00-agent-layer.md)
- [04-agents/01-collaboration-state-machine.md](04-agents/01-collaboration-state-machine.md)
- [04-agents/02-structured-output-contract.md](04-agents/02-structured-output-contract.md)
- [04-agents/agents/architect-agent.md](04-agents/agents/architect-agent.md)
- [04-agents/agents/coder-agent.md](04-agents/agents/coder-agent.md)
- [04-agents/agents/planner-agent.md](04-agents/agents/planner-agent.md)
- [04-agents/agents/release-agent.md](04-agents/agents/release-agent.md)
- [04-agents/agents/requirement-agent.md](04-agents/agents/requirement-agent.md)
- [04-agents/agents/reviewer-agent.md](04-agents/agents/reviewer-agent.md)
- [04-agents/agents/scaffold-agent.md](04-agents/agents/scaffold-agent.md)
- [04-agents/agents/security-agent.md](04-agents/agents/security-agent.md)
- [04-agents/agents/sre-agent.md](04-agents/agents/sre-agent.md)
- [04-agents/agents/tester-agent.md](04-agents/agents/tester-agent.md)

### 工具层文档

- [05-tool-layer/00-tool-gateway.md](05-tool-layer/00-tool-gateway.md)
- [05-tool-layer/01-risk-levels.md](05-tool-layer/01-risk-levels.md)
- [05-tool-layer/02-mcp-tool-server-structure.md](05-tool-layer/02-mcp-tool-server-structure.md)
- [05-tool-layer/tools/approval-tool.md](05-tool-layer/tools/approval-tool.md)
- [05-tool-layer/tools/browser-tool.md](05-tool-layer/tools/browser-tool.md)
- [05-tool-layer/tools/ci-tool.md](05-tool-layer/tools/ci-tool.md)
- [05-tool-layer/tools/deploy-tool.md](05-tool-layer/tools/deploy-tool.md)
- [05-tool-layer/tools/design-tool.md](05-tool-layer/tools/design-tool.md)
- [05-tool-layer/tools/git-tool.md](05-tool-layer/tools/git-tool.md)
- [05-tool-layer/tools/monitoring-tool.md](05-tool-layer/tools/monitoring-tool.md)
- [05-tool-layer/tools/remote-control-tool.md](05-tool-layer/tools/remote-control-tool.md)
- [05-tool-layer/tools/repo-tool.md](05-tool-layer/tools/repo-tool.md)
- [05-tool-layer/tools/requirement-tool.md](05-tool-layer/tools/requirement-tool.md)
- [05-tool-layer/tools/sandbox-tool.md](05-tool-layer/tools/sandbox-tool.md)
- [05-tool-layer/tools/scaffold-tool.md](05-tool-layer/tools/scaffold-tool.md)
- [05-tool-layer/tools/security-tool.md](05-tool-layer/tools/security-tool.md)
- [05-tool-layer/tools/test-tool.md](05-tool-layer/tools/test-tool.md)

### 业务流程文档

- [06-workflows/00-development-to-pr.md](06-workflows/00-development-to-pr.md)
- [06-workflows/01-pr-to-remote-deploy.md](06-workflows/01-pr-to-remote-deploy.md)
- [06-workflows/02-ci-failure-fix.md](06-workflows/02-ci-failure-fix.md)
- [06-workflows/03-incident-runbook.md](06-workflows/03-incident-runbook.md)
- [06-workflows/04-remote-takeover.md](06-workflows/04-remote-takeover.md)

### 数据模型文档

- [07-data/00-entity-model.md](07-data/00-entity-model.md)
- [07-data/01-database-schema.md](07-data/01-database-schema.md)
- [07-data/tables/agent_conversations.md](07-data/tables/agent_conversations.md)
- [07-data/tables/agent_runs.md](07-data/tables/agent_runs.md)
- [07-data/tables/approval_requests.md](07-data/tables/approval_requests.md)
- [07-data/tables/artifacts.md](07-data/tables/artifacts.md)
- [07-data/tables/development_plans.md](07-data/tables/development_plans.md)
- [07-data/tables/deployments.md](07-data/tables/deployments.md)
- [07-data/tables/environments.md](07-data/tables/environments.md)
- [07-data/tables/event_logs.md](07-data/tables/event_logs.md)
- [07-data/tables/project_alerts.md](07-data/tables/project_alerts.md)
- [07-data/tables/projects.md](07-data/tables/projects.md)
- [07-data/tables/pull_request_records.md](07-data/tables/pull_request_records.md)
- [07-data/tables/remote_sessions.md](07-data/tables/remote_sessions.md)
- [07-data/tables/remote_targets.md](07-data/tables/remote_targets.md)
- [07-data/tables/requirement_specs.md](07-data/tables/requirement_specs.md)
- [07-data/tables/service_instances.md](07-data/tables/service_instances.md)
- [07-data/tables/tasks.md](07-data/tables/tasks.md)
- [07-data/tables/technical_designs.md](07-data/tables/technical_designs.md)
- [07-data/tables/tool_calls.md](07-data/tables/tool_calls.md)

### API 文档

- [08-api/00-api-overview.md](08-api/00-api-overview.md)
- [08-api/01-task-api.md](08-api/01-task-api.md)
- [08-api/02-requirement-design-api.md](08-api/02-requirement-design-api.md)
- [08-api/03-agent-run-api.md](08-api/03-agent-run-api.md)
- [08-api/04-tool-call-api.md](08-api/04-tool-call-api.md)
- [08-api/05-approval-api.md](08-api/05-approval-api.md)
- [08-api/06-event-stream-api.md](08-api/06-event-stream-api.md)
- [08-api/07-environment-deployment-api.md](08-api/07-environment-deployment-api.md)
- [08-api/08-remote-ops-api.md](08-api/08-remote-ops-api.md)
- [08-api/09-monitoring-incident-api.md](08-api/09-monitoring-incident-api.md)

### 桌面端控制台文档

- [09-control-console/00-page-structure.md](09-control-console/00-page-structure.md)
- [09-control-console/01-key-interactions.md](09-control-console/01-key-interactions.md)

### 安全文档

- [10-security/00-security-boundary.md](10-security/00-security-boundary.md)
- [10-security/01-permission-policy.md](10-security/01-permission-policy.md)
- [10-security/02-audit-log.md](10-security/02-audit-log.md)

### 可观测性文档

- [11-observability/00-observability-design.md](11-observability/00-observability-design.md)

### 部署文档

- [12-deployment/00-local-development.md](12-deployment/00-local-development.md)
- [12-deployment/01-remote-demo-deployment.md](12-deployment/01-remote-demo-deployment.md)
- [12-deployment/02-demo-environment.md](12-deployment/02-demo-environment.md)
- [12-deployment/03-production-extension.md](12-deployment/03-production-extension.md)

### 测试文档

- [13-testing/00-testing-strategy.md](13-testing/00-testing-strategy.md)

### 路线与验收文档

- [14-roadmap/00-graduation-plan.md](14-roadmap/00-graduation-plan.md)
- [14-roadmap/01-innovation-risk-deliverables.md](14-roadmap/01-innovation-risk-deliverables.md)
- [14-roadmap/02-mvp-acceptance-and-extension.md](14-roadmap/02-mvp-acceptance-and-extension.md)
- [14-roadmap/03-implementation-milestone-flow.md](14-roadmap/03-implementation-milestone-flow.md)

### 细化设计文档

- [15-detailed-design/00-mvp-scope-and-cutline.md](15-detailed-design/00-mvp-scope-and-cutline.md)
- [15-detailed-design/01-module-contracts.md](15-detailed-design/01-module-contracts.md)
- [15-detailed-design/02-agent-tool-contract.md](15-detailed-design/02-agent-tool-contract.md)
- [15-detailed-design/03-api-detail.md](15-detailed-design/03-api-detail.md)
- [15-detailed-design/04-data-detail.md](15-detailed-design/04-data-detail.md)
- [15-detailed-design/05-workflow-state-events.md](15-detailed-design/05-workflow-state-events.md)
- [15-detailed-design/06-deployment-observability-detail.md](15-detailed-design/06-deployment-observability-detail.md)
- [15-detailed-design/07-testing-acceptance-matrix.md](15-detailed-design/07-testing-acceptance-matrix.md)
