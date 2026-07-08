# 总体架构

> 来源：[设计书 6.1](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：定义系统组件、数据流和控制流。
## 架构分层

1. 用户入口：Desktop Control Console。
2. 控制平面：FastAPI、Orchestrator、Tool Gateway、PostgreSQL、Redis。
3. Agent 运行层：Requirement / Planner / Architect / Coder / Tester / Reviewer / Release / SRE。
4. 工具层：MCP Tool Servers、Sandbox、Git、CI、Deploy、Remote、Monitoring、Security。
5. 远端业务运行层：Remote Agent、Docker Compose/K8s、业务服务。
6. 观测层：Prometheus、Grafana、Loki、Langfuse、Alertmanager。

## 设计书摘录

### 6.1 架构图

```mermaid
flowchart TB
    User["开发者 / 运维人员"]
    Console["Desktop Control Console\nTauri + React"]
    Guidance["Developer Guidance\n需求 / 约束 / 验收标准 / 反馈"]
    Spec["Spec & Design Store\nRequirement / ADR / OpenAPI / DB Schema"]
    LocalDev["Agent Dev Workspace\nGit Worktree + Docker Sandbox"]
    API["Control Plane API\nFastAPI"]
    Orchestrator["Orchestrator\nLangGraph State Machine"]
    AgentRuntime["Agent Runtime\nRequirement / Planner / Architect / Coder / Tester / Reviewer"]
    LLM["LLM Gateway\nLiteLLM"]
    ToolGateway["Tool Gateway\n权限 / 审批 / 审计 / 限流"]
    MCP["MCP Tool Servers"]
    DevTools["Development Tools\nScaffold / Design / OpenAPI / DB Migration"]
    Sandbox["Docker Sandbox"]
    Git["Gitea / GitHub"]
    CI["CI Runner"]
    Deploy["Deploy Controller\nSSH / Ansible / Docker Compose / K8s"]
    RemoteAgent["Remote Runtime Agent\n远程主机 / 云服务器 / K8s Node"]
    RemoteEnv["Remote Project Runtime Env\n远端业务项目 staging / demo / production"]
    Monitor["Project Monitoring Agent\n项目 Metrics / Logs / Alerts"]
    Security["Semgrep / Trivy"]
    Obs["Prometheus / Grafana / Loki / Langfuse"]
    DB["PostgreSQL"]
    Redis["Redis Queue"]

    User --> Console
    User --> Guidance
    Guidance --> Console
    Console --> API
    Console --> LocalDev
    API --> Spec
    API --> DB
    API --> Redis
    API --> Orchestrator
    Orchestrator --> Spec
    Orchestrator --> AgentRuntime
    AgentRuntime --> LLM
    AgentRuntime --> ToolGateway
    ToolGateway --> MCP
    MCP --> DevTools
    DevTools --> LocalDev
    LocalDev --> Sandbox
    MCP --> Sandbox
    MCP --> Git
    MCP --> CI
    CI --> Deploy
    Deploy --> RemoteAgent
    RemoteAgent --> RemoteEnv
    RemoteEnv --> Monitor
    Monitor --> Obs
    Monitor --> API
    MCP --> Security
    API --> Obs
    Orchestrator --> Obs
    ToolGateway --> Obs
```
