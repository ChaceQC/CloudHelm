# 总体技术栈

> 来源：[设计书 5.1](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：按模块记录技术选型和职责关系。
## 选型摘要

- 桌面端：Tauri v2 + React + TypeScript + Tailwind CSS + shadcn/ui。
- Desktop 本地：SQLite 非权威 store + OS credential store + Local Runtime
  sidecar。
- 常在线 Ops Hub：FastAPI + PostgreSQL + Redis/Celery。
- 身份权限：用户/session/device + scoped RBAC + 服务端 domain policy。
- Agent：LangGraph + LiteLLM + Pydantic structured output。
- 工具：MCP + FastMCP / MCP Python SDK。
- 隔离执行：Docker Sandbox。
- M7 DevOps：Gitea API、唯一 `workflow_dispatch`、Gitea Actions、OCI Registry、
  Deployment Controller、Remote Agent、Docker Compose。
- 远端运维：M7 使用 Remote Agent 受限状态/日志/diagnostics；M8 接入
  Prometheus、Grafana、Loki、Alertmanager，Sentry 可选。

M7 中 CI 只执行测试、安全扫描、构建和制品发布；release candidate approval
控制受控 ref 与 CI 启动，deployment approval 控制 Remote Agent 远端副作用。
部署身份使用不可变 OCI digest，不使用可变 tag。SSH 只提供单独审批的固定只读
诊断；Kubernetes、production 和交互式远程终端属于后续增强。

## 设计书摘录

### 5.1 主要技术栈

|模块|技术选型|说明|
|---|---|---|
|桌面端控制台|Tauri + React + TypeScript|轻量桌面端，支持本地文件、终端、系统集成|
|Desktop 本地数据|SQLite|只保存 server profile、UI 设置、草稿、缓存和事件 sequence；不保存权威业务状态|
|Desktop 凭据|OS credential store / Tauri Stronghold|保存 access/refresh token 与 Ed25519 device private key，不写 SQLite|
|本地执行|Tauri sidecar + `modules/local-runtime`|Windows/Linux 本机 workspace、Git、测试和受控工具；不连接远端数据库|
|UI 组件|Tailwind CSS + shadcn/ui|快速构建现代化管理台|
|代码编辑 / Diff|Monaco Editor|展示代码、diff、patch|
|终端组件|xterm.js|用于本地开发终端输出和接管；交互式远程终端不进入 M7|
|后端 API|Python + FastAPI|提供任务、审批、事件、Agent 控制 API|
|用户与权限|User/Session/Device + scoped RBAC + domain policy|按 system/project/environment 作用域控制 Desktop 与 API 功能；默认拒绝、职责分离|
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
|任务队列|Redis + Celery|M7 worker 投递；PostgreSQL WorkflowJob 保存业务状态、lease 和幂等|
|Ops Hub 数据库|PostgreSQL|任务、事件、审批、工具调用、WorkflowJob、用户/RBAC、部署和审计的权威存储|
|沙箱|Docker Sandbox|隔离代码执行、测试和文件修改|
|Git 服务|Gitea API|M7 使用受控 repository binding、精确 commit/ref；GitHub 为后续适配|
|CI|Gitea Actions + 固定 `workflow_dispatch`|workflow 不监听 push；只跑测试、安全扫描和构建并产出 artifact，禁止部署命令|
|制品身份|OCI Registry + manifest + `sha256` digest|审批、ReleasePlan、部署和远端复核都绑定不可变 digest，不以 tag 或本地 image id 代替|
|远程控制|Remote Agent + 审批后的固定 SSH 诊断|M7 提供服务状态、受限日志和 diagnostics，不提供交互终端|
|Agent 化远程部署|Release / Deploy Agent + Deploy Tool + Deployment Controller + Remote Agent + Docker Compose|MVP 由 Agent 在两道审批后部署不可变 CI 制品；SSH 不作为部署执行器，K8s 属于增强版|
|部署目标|M7：云服务器 / 远程 Linux 主机；增强版：K8s 集群|M7 只支持 staging / demo，production 与 Kubernetes 后续扩展|
|配置管理|环境变量 + Secret Store + 部署清单|管理远程服务配置、密钥引用和版本|
|远端服务管理|systemd + Docker Engine + Docker Compose|M7 由 systemd 管理 Remote Agent，业务项目固定使用 Docker Compose project|
|Ops Hub 部署|Linux + Docker Compose/systemd|App 可离线；Platform API、Agents、Workflow、PostgreSQL/Redis 常在线|
|项目兼容契约|`cloudhelm.project.yaml` + `cloudhelm.env.schema.json`|可删除的受管适配；Project Core 可独立构建和部署|
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
