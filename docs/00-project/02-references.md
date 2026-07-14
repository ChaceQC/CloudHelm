# 参考项目与借鉴点

> 来源：[设计书 4 章](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：按技术方向记录调研对象和借鉴点，避免实现时偏离设计。
## 使用方式

- 参考项目只作为架构和交互借鉴，不要求全部集成。
- MVP 优先参考：Codex-like 控制台、MCP 工具生态、LangGraph 编排、M7 的
  Gitea/CI 制品与 Remote Agent + Docker Compose 部署链，以及 M8 的
  Prometheus/Loki 观测链；SSH 只作为审批后的固定只读诊断。
- M7 对参考项目的采用结论固定为：release candidate approval 后发布受控 ref，
  Platform API 只用固定 workflow 的 `workflow_dispatch` 触发 CI；CI 只产出测试、
  安全、构建结果和不可变 OCI digest，deployment approval 后才允许 Remote Agent
  执行 Linux staging / demo 部署。
- Ansible、Kubernetes、GitOps、production 和交互式远程终端仅作为后续增强参考，
  不属于 M7 已选实现。

## 设计书摘录

## 4. 参考开源项目与借鉴点

以下项目用于技术调研和架构参考，不要求全部集成。

### 4.1 Agent 与自治软件工程

|项目|地址|借鉴点|
|---|---|---|
|OpenHands|[github.com/OpenHands/openhands](https://github.com/OpenHands/openhands)|自托管 coding agent 控制中心，参考任务执行、浏览器、终端、文件操作、运行时隔离等设计|
|Open SWE|[github.com/langchain-ai/open-swe](https://github.com/langchain-ai/open-swe)|异步软件工程 Agent，参考 GitHub issue 触发、sandbox、自动 PR、多任务并行|
|SWE-agent|[github.com/SWE-agent/SWE-agent](https://github.com/SWE-agent/SWE-agent)|面向真实 GitHub issue 的修复 Agent，参考软件工程 benchmark 和命令执行循环|
|SWE-ReX|[github.com/SWE-agent/swe-rex](https://github.com/SWE-agent/swe-rex)|远程执行与 sandbox shell 框架，参考本地 / Docker / 云端执行环境抽象|
|Aider|[github.com/aider-ai/aider](https://github.com/aider-ai/aider)|参考终端内 AI pair programming 与 Git diff 工作流|
|PR-Agent|[github.com/The-PR-Agent/pr-agent](https://github.com/The-PR-Agent/pr-agent)|参考自动 PR 描述、PR review、代码建议生成|

### 4.2 Codex 风格桌面端参考

|项目 / 文档|地址|借鉴点|
|---|---|---|
|Codex App 官方文档|[developers.openai.com/codex/app](https://developers.openai.com/codex/app)|参考桌面端项目线程、并行任务、worktree、终端、Git 工作流、自动化任务等交互模式|
|Codex CLI|[github.com/openai/codex](https://github.com/openai/codex)|参考本地 coding agent 的权限、文件系统、shell、MCP、Git 集成方式|

本项目不复制 Codex，而是实现一个面向毕设场景的 **Codex-like DevOps Control Console**。

### 4.3 工具协议与工具生态

|项目|地址|借鉴点|
|---|---|---|
|Model Context Protocol|[modelcontextprotocol.io](https://modelcontextprotocol.io/)|作为 Agent 调用工具的标准协议|
|MCP Python SDK|[github.com/modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk)|开发 MCP Server / MCP Client|
|MCP Servers|[github.com/modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers)|参考文件系统、GitHub、数据库等工具服务形态|
|FastMCP|[github.com/jlowin/fastmcp](https://github.com/jlowin/fastmcp)|快速开发 Python MCP 工具服务|
|GitHub MCP Server|[github.com/github/github-mcp-server](https://github.com/github/github-mcp-server)|参考 Issue、PR、仓库、Actions 等 GitHub 工具能力|
|Playwright MCP|[github.com/microsoft/playwright-mcp](https://github.com/microsoft/playwright-mcp)|参考浏览器自动化工具接入|

### 4.4 编排、模型与观测

|项目|地址|借鉴点|
|---|---|---|
|LangGraph|[github.com/langchain-ai/langgraph](https://github.com/langchain-ai/langgraph)|有状态 Agent 工作流、human-in-the-loop、任务恢复|
|LiteLLM|[github.com/BerriAI/litellm](https://github.com/BerriAI/litellm)|统一模型网关，支持多模型供应商|
|Langfuse|[github.com/langfuse/langfuse](https://github.com/langfuse/langfuse)|LLM tracing、prompt、cost、eval 管理|
|OpenTelemetry|[opentelemetry.io](https://opentelemetry.io/)|日志、指标、trace 统一采集|

### 4.5 DevOps、安全与自动化

|项目|地址|借鉴点|
|---|---|---|
|Gitea|[about.gitea.com](https://about.gitea.com/)|M7 自托管 Git 与 Actions 服务；固定 workflow 仅由 Platform API 通过 `workflow_dispatch` 触发，不监听 push|
|Argo CD|[github.com/argoproj/argo-cd](https://github.com/argoproj/argo-cd)|生产扩展版 GitOps 持续部署参考，不进入 M7|
|Prometheus|[prometheus.io](https://prometheus.io/)|指标采集与告警|
|Grafana|[github.com/grafana/grafana](https://github.com/grafana/grafana)|观测面板|
|Loki|[grafana.com/oss/loki](https://grafana.com/oss/loki/)|日志聚合|
|Semgrep|[github.com/semgrep/semgrep](https://github.com/semgrep/semgrep)|SAST 静态安全扫描|
|Trivy|[github.com/aquasecurity/trivy](https://github.com/aquasecurity/trivy)|依赖、容器、文件系统漏洞扫描|
|OPA|[github.com/open-policy-agent/opa](https://github.com/open-policy-agent/opa)|Policy-as-Code 权限控制|
|OpenBao|[openbao.org](https://openbao.org/)|密钥管理，作为 Vault 开源替代参考|
|n8n|[github.com/n8n-io/n8n](https://github.com/n8n-io/n8n)|可视化工作流与 human-in-the-loop 参考|
|StackStorm|[github.com/StackStorm/st2](https://github.com/StackStorm/st2)|事件驱动运维自动化与 runbook 参考|

### 4.6 远程控制与远程部署参考

|项目|地址|借鉴点|
|---|---|---|
|Ansible|[github.com/ansible/ansible](https://github.com/ansible/ansible)|增强版配置管理参考；M7 部署执行入口固定为 Remote Agent，不使用 Ansible/SSH 部署|
|Rundeck|[github.com/rundeck/rundeck](https://github.com/rundeck/rundeck)|参考远端作业的审批、受控执行、执行记录和回滚脚本管理，用于设计 Agent 经审批后执行部署动作|
|Windmill|[github.com/windmill-labs/windmill](https://github.com/windmill-labs/windmill)|参考把脚本封装为可审批、可审计的自动化动作，辅助设计 Deploy Tool / Runbook Tool|
|Kestra|[github.com/kestra-io/kestra](https://github.com/kestra-io/kestra)|参考事件驱动工作流和远端任务编排，辅助设计 Release / Deploy Agent 的部署流程|
|Apache Guacamole|[github.com/apache/guacamole-client](https://github.com/apache/guacamole-client)|增强版远程桌面 / SSH / RDP / VNC 会话管理参考；M7 不提供交互会话|
|MeshCentral|[github.com/Ylianst/MeshCentral](https://github.com/Ylianst/MeshCentral)|M7 借鉴 agent 心跳和设备状态；远程终端、文件管理属于增强版|
|Teleport|[github.com/gravitational/teleport](https://github.com/gravitational/teleport)|借鉴主机身份、SSH host verification 和访问审计；Kubernetes/交互访问属于生产扩展版|
|Terraform / OpenTofu|[github.com/opentofu/opentofu](https://github.com/opentofu/opentofu)|云资源声明式管理，后续扩展云主机、网络、Kubernetes 集群创建|

本项目的远程部署不是“CI/CD 独立把代码推到远端”，而是参考上述受控远程执行与
Runbook 系统：第一道审批允许发布 release candidate 并触发唯一
`workflow_dispatch`，CI 负责测试、安全扫描、构建和不可变 OCI 制品交付；
第二道 deployment approval 通过后，Release / Deploy Agent 才通过 Tool
Gateway、Deploy Tool、Deployment Controller 与 Remote Agent 完成远端部署。
SSH 诊断不是部署回退路径。

### 4.7 远端业务项目运维参考

本项目的运维对象是远端已经部署的业务项目，因此参考项目应重点覆盖 **远端部署、服务管理、容器管理、应用监控、日志采集、告警、故障处理和回滚**。

|类别|项目|地址|借鉴点|
|---|---|---|---|
|远端容器管理|Portainer|[github.com/portainer/portainer](https://github.com/portainer/portainer)|参考 Docker / Kubernetes 环境可视化管理、容器状态、日志、重启、部署栈管理|
|自托管部署平台|Coolify|[github.com/coollabsio/coolify](https://github.com/coollabsio/coolify)|参考将 Git 仓库部署到远程服务器、服务状态、环境变量、域名、日志的一体化体验|
|自托管部署平台|Dokploy|[github.com/Dokploy/dokploy](https://github.com/Dokploy/dokploy)|参考 Docker Compose / Traefik 风格的远程应用部署与管理|
|自托管 PaaS|CapRover|[github.com/caprover/caprover](https://github.com/caprover/caprover)|参考一键部署、应用管理、域名、SSL、容器运行状态|
|远程主机管理|Cockpit|[github.com/cockpit-project/cockpit](https://github.com/cockpit-project/cockpit)|参考 Linux 主机 Web 管理、服务状态、日志、终端和系统资源查看|
|监控告警|Prometheus Alertmanager|[github.com/prometheus/alertmanager](https://github.com/prometheus/alertmanager)|参考告警分组、静默、路由和通知|
|主机指标|node_exporter|[github.com/prometheus/node_exporter](https://github.com/prometheus/node_exporter)|采集远端主机 CPU、内存、磁盘、网络等指标|
|容器指标|cAdvisor|[github.com/google/cadvisor](https://github.com/google/cadvisor)|采集远端容器资源使用、重启、文件系统和网络指标|
|黑盒探测|blackbox_exporter|[github.com/prometheus/blackbox_exporter](https://github.com/prometheus/blackbox_exporter)|对远端业务项目做 HTTP/TCP/ICMP 健康检查|
|日志采集|Grafana Alloy|[github.com/grafana/alloy](https://github.com/grafana/alloy)|统一采集 metrics、logs、traces，向 Prometheus / Loki / OTLP 发送数据|
|日志采集|Fluent Bit|[github.com/fluent/fluent-bit](https://github.com/fluent/fluent-bit)|轻量日志采集器，适合部署在远端主机或容器节点|
|日志管道|Vector|[github.com/vectordotdev/vector](https://github.com/vectordotdev/vector)|高性能日志 / 指标管道，参考日志解析、过滤、路由|
|可用性监控|Uptime Kuma|[github.com/louislam/uptime-kuma](https://github.com/louislam/uptime-kuma)|参考服务可用性监控、状态页、通知和探测配置|
|错误追踪|Sentry|[github.com/getsentry/sentry](https://github.com/getsentry/sentry)|参考应用异常聚合、release 关联、错误堆栈和影响范围分析|
|链路追踪|OpenTelemetry Collector|[github.com/open-telemetry/opentelemetry-collector](https://github.com/open-telemetry/opentelemetry-collector)|远端业务项目 traces / metrics / logs 的采集和转发|
|Runbook 自动化|Rundeck|[github.com/rundeck/rundeck](https://github.com/rundeck/rundeck)|参考运维任务编排、审批、执行记录、远程命令|
|Runbook 自动化|Kestra|[github.com/kestra-io/kestra](https://github.com/kestra-io/kestra)|参考事件驱动工作流、脚本任务、定时任务和执行记录|
|Runbook 自动化|Windmill|[github.com/windmill-labs/windmill](https://github.com/windmill-labs/windmill)|参考把 Python / Bash / TypeScript 脚本变成可审批、可审计的运维动作|
|安全接入|WireGuard|[github.com/WireGuard/wireguard-tools](https://github.com/WireGuard/wireguard-tools)|用于控制平面与远端部署目标之间的安全网络连接|
|内网接入|Headscale|[github.com/juanfont/headscale](https://github.com/juanfont/headscale)|自托管 Tailscale 控制面，参考远端节点接入和 ACL|

### 4.8 Agent 指导开发与项目生成参考

本项目的“本地开发”不是开发者亲自写代码，而是开发者通过控制台指导 Agents 完成软件开发。因此还需要参考 **需求澄清、项目脚手架、代码生成、AI 编程代理、接口生成、组件开发和规格驱动开发** 相关项目。

|类别|项目|地址|借鉴点|
|---|---|---|---|
|AI 编程 Agent|Continue|[github.com/continuedev/continue](https://github.com/continuedev/continue)|参考 IDE 内 AI 编程助手、上下文选择、模型适配和开发者指导交互|
|AI 编程 Agent|Cline|[github.com/cline/cline](https://github.com/cline/cline)|参考可调用终端、文件、浏览器、MCP 工具的编码 Agent 工作流|
|AI 编程 Agent|Roo Code|[github.com/RooCodeInc/Roo-Code](https://github.com/RooCodeInc/Roo-Code)|参考多模式 AI 编码、工具调用审批、代码修改和任务执行体验|
|AI 编程 Agent|OpenHands|[github.com/OpenHands/openhands](https://github.com/OpenHands/openhands)|参考从任务目标到代码实现、测试、浏览器和终端操作的一体化 Agent 环境|
|AI 编程 Agent|Aider|[github.com/aider-ai/aider](https://github.com/aider-ai/aider)|参考通过 Git diff 驱动的 AI 结对编程和 commit 工作流|
|软件模板 / 脚手架|Backstage Software Templates|[github.com/backstage/backstage](https://github.com/backstage/backstage)|参考从模板创建服务、生成项目骨架、登记服务目录|
|软件模板 / 脚手架|Cookiecutter|[github.com/cookiecutter/cookiecutter](https://github.com/cookiecutter/cookiecutter)|参考基于模板生成项目骨架、配置变量和工程结构|
|软件模板 / 脚手架|Yeoman|[github.com/yeoman/yo](https://github.com/yeoman/yo)|参考通用脚手架生成器和 generator 生态|
|Monorepo / 工程化|Nx|[github.com/nrwl/nx](https://github.com/nrwl/nx)|参考多应用、多包、任务图、构建缓存和工程生成器|
|Monorepo / 工程化|Turborepo|[github.com/vercel/turborepo](https://github.com/vercel/turborepo)|参考前端 / 全栈 monorepo 构建、缓存和任务编排|
|接口生成|OpenAPI Generator|[github.com/OpenAPITools/openapi-generator](https://github.com/OpenAPITools/openapi-generator)|参考从 OpenAPI 规范生成客户端、服务端 stub 和类型定义|
|数据库开发|Prisma|[github.com/prisma/prisma](https://github.com/prisma/prisma)|参考 schema-first 数据模型、迁移和类型安全数据库访问|
|前端组件开发|Storybook|[github.com/storybookjs/storybook](https://github.com/storybookjs/storybook)|参考组件开发、组件文档、交互测试和 UI 验收|
|浏览器测试|Playwright|[github.com/microsoft/playwright](https://github.com/microsoft/playwright)|参考前端功能验收、端到端测试和截图验证|

---
