# 总体技术栈

> 来源：[设计书 5.1](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：按模块记录技术选型和职责关系。
## 选型摘要

- 桌面端：Tauri + React + TypeScript + Tailwind CSS + shadcn/ui。
- 后端：FastAPI + PostgreSQL + Redis。
- Agent：LangGraph + LiteLLM + Pydantic structured output。
- 工具：MCP + FastMCP / MCP Python SDK。
- 隔离执行：Docker Sandbox。
- DevOps：Gitea / GitHub API、Gitea Actions / GitHub Actions、Docker Compose、Ansible。
- 远端运维：Remote Agent、Prometheus、Grafana、Loki、Alertmanager、Sentry 可选。

## 设计书摘录

### 5.1 主要技术栈

|模块|技术选型|说明|
|---|---|---|
|桌面端控制台|Tauri + React + TypeScript|轻量桌面端，支持本地文件、终端、系统集成|
|UI 组件|Tailwind CSS + shadcn/ui|快速构建现代化管理台|
|代码编辑 / Diff|Monaco Editor|展示代码、diff、patch|
|终端组件|xterm.js|嵌入式终端输出和接管|
|后端 API|Python + FastAPI|提供任务、审批、事件、Agent 控制 API|
|Agent 编排|LangGraph|实现状态机、多 Agent、human-in-the-loop|
|模型接入|LiteLLM|统一接入 OpenAI、Claude、本地模型等|
|需求规格化|Markdown Spec + JSON Schema + Pydantic|把开发者自然语言目标转为结构化需求、验收标准和任务边界|
|技术设计产物|ADR + OpenAPI + Mermaid + 数据库 schema|让 Architect Agent 输出可审查的架构决策、接口设计和数据模型|
|项目脚手架|Cookiecutter / Backstage Templates / Yeoman|从需求生成项目骨架、模块目录、基础配置和 CI 文件|
|接口生成|OpenAPI Generator|根据 API 规范生成客户端、服务端 stub 和类型定义|
|数据库迁移|Alembic / Prisma Migrate|生成和审查数据库 schema 与 migration|
|前端组件开发|Storybook + Playwright|组件级开发、视觉检查和端到端验收|
|工具协议|MCP|工具标准化调用|
|工具开发|FastMCP / MCP Python SDK|开发自定义 Tool Server|
|任务队列|Redis + Celery / RQ|执行异步 Agent 任务|
|数据库|PostgreSQL|任务、事件、审批、工具调用、审计记录|
|沙箱|Docker Sandbox|隔离代码执行、测试和文件修改|
|Git 服务|Gitea / GitHub API|MVP 推荐 Gitea，便于本地部署演示|
|CI|Gitea Actions / GitHub Actions|跑测试、安全扫描和构建，产出镜像 / artifact；部署动作由 Agent 编排执行|
|远程控制|SSH + WebSocket Terminal + Remote Agent|面向远端已部署业务项目的远程命令、日志拉取、服务状态、人工接管|
|Agent 化远程部署|Release / Deploy Agent + Deploy Tool + Deployment Controller + Remote Agent + Ansible / Docker Compose / Kubernetes|MVP 由 Agent 在审批后通过 Tool Gateway 调用部署工具，用 SSH / Remote Agent + Docker Compose 将业务项目部署到远端 staging / demo；增强版扩展到 K8s + Argo CD|
|部署目标|云服务器 / 远程 Linux 主机 / K8s 集群|支持 staging、demo、production 等环境|
|配置管理|环境变量 + Secret Store + 部署清单|管理远程服务配置、密钥引用和版本|
|远端服务管理|systemd + Docker Engine + Docker Compose|MVP 远端业务项目以 Docker Compose 栈或 systemd 服务运行|
|远端反向代理|Caddy / Traefik / Nginx Proxy Manager|管理远端业务项目域名、HTTPS、路由和健康检查|
|远端主机指标|node_exporter|采集远端主机 CPU、内存、磁盘、网络|
|远端容器指标|cAdvisor|采集远端业务容器 CPU、内存、网络、重启次数|
|远端日志采集|Grafana Alloy / Fluent Bit / Vector|将业务项目日志采集到 Loki 或其他日志后端|
|远端可用性探测|blackbox_exporter / Uptime Kuma|对远端业务项目 HTTP 接口、端口、页面进行探活|
|远端异常追踪|Sentry|采集业务项目运行时异常、堆栈、release 关联|
|安全扫描|Semgrep + Trivy|代码和依赖安全检查|
|可观测性|OpenTelemetry + Prometheus + Grafana + Loki|系统指标、日志、trace|
|LLM 观测|Langfuse|Agent prompt、trace、token 成本|
|权限策略|OPA / 自研 Policy Engine|工具调用权限和审批规则|
|密钥管理|OpenBao / 本地加密配置|保存 API token 和临时凭据|
