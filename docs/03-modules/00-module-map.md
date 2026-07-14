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

## 设计书摘录

### 7.2 模块职责说明

|目录|职责|
|---|---|
|`apps/control-console`|桌面控制台，负责开发者需求输入、Agent 指导、方案审查、diff、日志、审批、远程状态和终端接管|
|`modules/platform-api`|统一 API 服务，对桌面端提供需求、任务、设计、事件、审批、配置接口|
|`modules/orchestrator`|核心编排器；M1-M6 已实现需求/设计/计划与本地开发两组显式状态机，部署/监控阶段后续接入|
|`modules/agent-runtime`|具体 Agent 实现，包括 Requirement、Planner、Architect、Coder、Tester、Reviewer、SRE 等角色，以及 prompt、LLM 调用、记忆和结构化输出|
|`modules/spec-store`|保存结构化需求、验收标准、ADR、OpenAPI、数据库 schema 和 Agent 设计产物|
|`modules/tool-gateway`|工具统一入口，负责权限、审批、审计、限流、MCP 路由|
|`modules/toolservers`|规划中的独立 MCP 工具服务；M5-M6 当前工具 adapter 位于 `modules/tool-gateway`|
|`modules/sandbox-runner`|规划中的 Docker sandbox 生命周期模块；M6 未进入生产路径|
|`modules/remote-control-plane`|管理针对远端业务项目的远程连接、远程终端、远程命令会话、WebSocket 日志流和远程操作审计|
|`modules/remote-agent`|部署在远程主机或集群中的轻量 agent，负责业务项目心跳、命令执行、日志流、指标暴露和服务发现|
|`modules/deployment-controller`|管理业务项目的部署目标、发布策略、健康检查、回滚计划和部署状态|
|`modules/monitoring-collector`|采集远端业务项目指标、日志、告警和 synthetic check 结果，并转换为平台事件|
|`modules/workflow-engine`|异步任务队列、worker、重试、定时任务|
|`modules/policy-engine`|权限策略与风险分级，后期可接 OPA|
|`modules/audit-log`|事件溯源、审计记录、状态回放|
|`modules/integrations`|外部系统适配器，例如 Gitea、GitHub、SSH、Ansible、Docker、Kubernetes、Prometheus、Loki|
|`packages/shared-contracts`|跨模块共享协议、事件 schema、OpenAPI、工具 schema|
|`infra`|本地 Agent 开发、Release / Deploy Agent 远端部署、观测系统、CI 构建配置|
|`examples`|演示需求、演示仓库、演示 issue、Release / Deploy Agent 远端部署示例，便于答辩展示|

---
