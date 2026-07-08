# modules/platform-api

> 来源：[设计书 7.1-7.2](../../../云舵 CloudHelm 毕设设计书.md)  
> 层级：`modules/platform-api`

## M2 实现状态

`modules/platform-api` 已从 M1 `/health` 扩展为真实数据库 API：

- 技术组合：FastAPI、Pydantic v2、SQLAlchemy 2.x、Alembic、PostgreSQL。
- 分层：`api`、`schemas`、`services`、`repositories`、`models`、`db`。
- 已实现：Project、Task、Requirement、Technical Design、AgentRun、ToolCall、Approval、Event Timeline。
- 未实现：Agent 自动执行、Tool Gateway 真实工具执行、Git PR、远端部署和监控。

写操作必须通过 service 层在同一事务内写业务表和 `event_logs`。

## M4 实现状态

`modules/platform-api` 已扩展到 `0.3.0`：

- 新增 Orchestration API：`start`、`run-next`、`orchestration state`。
- 新增 DevelopmentPlan API 和 `development_plans` 表。
- 扩展 `agent_runs`，记录结构化输出、摘要和失败错误。
- 每个 M4 Agent 步骤在同一事务中写入 AgentRun、业务产物、Task 状态和 EventLog。
- M4 仍不执行 Tool Gateway、Git PR、远端部署或监控动作。

## 职责

统一 API 服务，对桌面端提供需求、任务、设计、事件、审批、配置接口。

## 技术栈

Python + FastAPI + Pydantic + PostgreSQL + Redis。

## 上游依赖

PostgreSQL、Redis、Orchestrator、Tool Gateway。

## 主要输出

REST/SSE/WebSocket API、任务状态、事件流。

## MVP 实现要点

1. 先实现与全流程演示直接相关的最小能力。
2. 所有跨模块调用优先通过共享契约和 API，不直接耦合内部实现。
3. 状态变化、工具调用、审批、远程操作都必须写入事件或审计记录。
4. 与远端业务项目相关的操作必须绑定 `project_id + environment_id + deployment_id + service_id`。

## 测试关注点

- 参数校验和错误处理。
- 与相邻模块的集成路径。
- 失败重试、暂停、审批和人工接管场景。
- 关键输出是否能被控制台展示和被审计追踪。
