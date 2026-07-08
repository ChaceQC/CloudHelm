# MVP 推荐技术组合

> 来源：[设计书 5.2](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：限定毕设阶段必须优先实现的技术组合。
## MVP 边界

Kubernetes、Argo CD、OpenBao、StackStorm、Terraform/OpenTofu 仅作为扩展设计，不作为第一阶段强制实现。

## 设计书摘录

### 5.2 MVP 推荐组合

毕设阶段推荐先实现以下组合：

```text
Tauri + React + TypeScript
FastAPI + PostgreSQL + Redis
LangGraph + LiteLLM
MCP + FastMCP
Requirement Spec + ADR + OpenAPI
Cookiecutter / Backstage Templates
OpenAPI Generator + Alembic / Prisma Migrate
pytest / vitest / Playwright / Storybook
Docker Sandbox
Gitea + Gitea Actions
Release / Deploy Agent + SSH Remote Agent + Docker Compose Deploy
Semgrep + Trivy
Langfuse
Prometheus + Grafana
```

Kubernetes、Argo CD、OpenBao、StackStorm、Terraform / OpenTofu 可以作为设计扩展，不作为第一阶段强制实现。
