# MVP 推荐技术组合

> 来源：[设计书 5.2](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：限定毕设阶段必须优先实现的技术组合。
## MVP 边界

Kubernetes、Argo CD、OpenBao、StackStorm、Terraform/OpenTofu 仅作为扩展设计，不作为第一阶段强制实现。

## 设计书摘录

### 5.2 MVP 推荐组合

毕设阶段推荐先实现以下组合：

```text
Tauri v2 + React + TypeScript
Desktop SQLite + OS credential store + Local Runtime sidecar
Linux Ops Hub: FastAPI + PostgreSQL + Redis/Celery
User / Device / Session + scoped RBAC
LangGraph + LiteLLM
MCP + FastMCP
Requirement Spec + ADR + OpenAPI
Cookiecutter / Backstage Templates
OpenAPI Generator + Alembic / Prisma Migrate
pytest / vitest / Playwright / Storybook
Docker Sandbox
Gitea + Gitea Actions
Release / Deploy Agent + Deploy Tool + Deployment Controller + Remote Agent
Docker Compose Deploy + OCI digest + Redis/Celery workflow worker
cloudhelm.project.yaml + standalone Dockerfile/Compose
Semgrep + Trivy
Langfuse
Prometheus + Grafana
```

Kubernetes、Argo CD、OpenBao、StackStorm、Terraform / OpenTofu 可以作为设计扩展，不作为第一阶段强制实现。

发行边界：

- Windows 必须有 setup `.exe`，Linux 必须有 AppImage 和 `.deb`。
- Desktop 最终用户不安装 Docker/PostgreSQL/Redis。
- PostgreSQL/Redis 位于常在线 Ops Hub；本地 Compose 只供开发或 all-in-one demo。
- 同一业务项目必须通过 standalone 与 CloudHelm-managed 两条路径验收。
