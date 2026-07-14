# modules/platform-api

> 来源：[设计书 7.1-7.2](../../../云舵 CloudHelm 毕设设计书.md)  
> 层级：`modules/platform-api`

## M2-M6 实现状态

`modules/platform-api` `0.5.0` 已从 M1 `/health` 扩展为真实数据库 API 和
本地开发工作流：

- 技术组合：FastAPI、Pydantic v2、SQLAlchemy 2.x、Alembic、PostgreSQL。
- 分层：`api`、`schemas`、`services`、`repositories`、`models`、`db`。
- 已实现：Project、Task、Requirement、Technical Design、DevelopmentPlan、
  AgentRun、ToolCall、Approval、Event Timeline、Artifact、本地
  PullRequestRecord。
- 已实现 M4 `start/run-next` 与 M6 `local-development/start/run-next`。
- 已接入 Agent Runtime 与 Tool Gateway，执行真实受控文件、pytest、Bandit、
  pip-audit、branch、commit 和 format patch。
- 远端 push、真实 GitHub/Gitea PR、CI/CD、SSH、部署和监控仍在 M7-M8。

普通写操作通过 service 层在同一事务内写业务表和 `event_logs`。文件、Git 和
进程副作用使用短事务先抢占 ToolCall，再执行 handler，最后在后续事务写终态。

## M4 实现状态

`modules/platform-api` 已保留 M4 需求设计入口：

- 新增 Orchestration API：`start`、`run-next`、`orchestration state`。
- 新增 DevelopmentPlan API 和 `development_plans` 表。
- 扩展 `agent_runs`，记录结构化输出、摘要和失败错误。
- 每个 M4 Agent 步骤在同一事务中写入 AgentRun、业务产物、Task 状态和 EventLog。
- M4 入口本身不执行 M6 工具；已审批 DevelopmentPlan 由独立 M6 API 接续。

## M6 实现状态

- `GET/POST /api/tasks/{task_id}/local-development...` 每次推进一个可审计动作。
- `GET /api/tasks/{task_id}/artifacts` 与 Artifact 详情只返回安全引用和有界预览。
- `GET /api/tasks/{task_id}/pull-request-records` 返回本地等价 PR record；
  `provider=local` 时 `url=null`。
- 带 `workflow_step` 的 AgentRun 工具调用只接受内部 Agent executor；公开 Tool
  Gateway HTTP 入口返回稳定边界错误。
- execution recipe 按工具名、规范化模型参数和允许调用次数精确绑定。
- M6 基础设施失败会保存已发生的配对 provider call/output 与失败上下文，
  Task 按可恢复性暂停或失败。

## 职责

统一 API 服务，对桌面端提供需求、任务、设计、事件、审批、配置接口。

## 当前技术栈

Python + FastAPI + Pydantic v2 + SQLAlchemy 2.x + Alembic + PostgreSQL。
Redis 当前只是预留配置，尚未进入生产路径。

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
