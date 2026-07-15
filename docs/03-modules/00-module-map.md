# 模块职责总览

> 来源：[设计书 7.2](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：按 Monorepo 目录说明每个模块职责。
## 文档拆分

本目录下已为每个顶层应用、模块、包和基础设施部分生成单独文档。实现时以对应模块文档为入口，再回查总体架构、API、数据库和工具层文档。

## M1-M6 实现说明

- 当前已有生产代码目录：`apps/control-console`、`modules/platform-api`、
  `modules/orchestrator`、`modules/agent-runtime`、`modules/tool-gateway`、
  `packages/shared-contracts`、`infra` 和 `examples`。
- `modules/orchestrator` 当前是显式 Python 状态机。
- 独立 `modules/sandbox-runner`、MCP `modules/toolservers`、远端部署、监控等
  目录仍是目标模块；M6 的本地执行由 Tool Gateway 受控 `subprocess` 提供，
  不得仅依据下表把规划模块写成已交付。
- `apps/control-console` 当前仍是 Web 工程；Tauri、Desktop SQLite、
  `modules/local-runtime`、用户/RBAC 和安装器均为后续目标。

## 设计书摘录

### 7.2 模块职责说明

|目录|职责|
|---|---|
|`apps/control-console`|Windows/Linux Desktop，负责 server profile、登录、需求、审查、diff、审批、远程状态和权限化 UI；本地 SQLite 非权威|
|`modules/local-runtime`|随 Desktop 分发的本机 sidecar，负责 workspace、Git、测试和受控工具；不连接远端数据库|
|`modules/platform-api`|Ops Hub 统一 API，提供认证、用户/RBAC、需求、任务、设计、事件、审批、同步和配置接口|
|`modules/orchestrator`|核心编排器；M1-M6 已实现需求/设计/计划与本地开发两组显式状态机，部署/监控阶段后续接入|
|`modules/agent-runtime`|具体 Agent 实现，包括 Requirement、Planner、Architect、Coder、Tester、Reviewer、SRE 等角色，以及 prompt、LLM 调用、记忆和结构化输出|
|`modules/spec-store`|保存结构化需求、验收标准、ADR、OpenAPI、数据库 schema 和 Agent 设计产物|
|`modules/tool-gateway`|工具统一入口，负责权限、审批、审计、限流、MCP 路由|
|`modules/toolservers`|规划中的独立 MCP 工具服务；M5-M6 当前工具 adapter 位于 `modules/tool-gateway`|
|`modules/sandbox-runner`|规划中的 Docker sandbox 生命周期模块；M6 未进入生产路径|
|`modules/remote-control-plane`|增强版远程 session/terminal 网关；不是常在线 Ops Hub 的名称|
|`modules/remote-agent`|部署在远程主机或集群中的轻量 agent，负责业务项目心跳、命令执行、日志流、指标暴露和服务发现|
|`modules/deployment-controller`|管理业务项目的部署目标、发布策略、健康检查、回滚计划和部署状态|
|`modules/monitoring-collector`|采集远端业务项目指标、日志、告警和 synthetic check 结果，并转换为平台事件|
|`modules/workflow-engine`|异步任务队列、worker、重试、定时任务|
|`modules/policy-engine`|权限策略与风险分级，后期可接 OPA|
|`modules/audit-log`|事件溯源、审计记录、状态回放|
|`modules/integrations`|外部系统适配器，例如 Gitea、GitHub、SSH、Ansible、Docker、Kubernetes、Prometheus、Loki|
|`packages/shared-contracts`|跨模块共享协议、事件 schema、OpenAPI、工具 schema|
|`infra`|Desktop 发行、Ops Hub bootstrap/backup、Remote Agent、本地开发、远端部署、观测与 CI 配置|
|`examples`|独立可运行且可选接入 CloudHelm manifest 的演示项目、需求和 E2E|

---
