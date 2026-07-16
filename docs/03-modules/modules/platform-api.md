# modules/platform-api

> 来源：[设计书 7.1-7.2](../../../云舵 CloudHelm 毕设设计书.md)  
> 层级：`modules/platform-api`

## M2-M7-2D 实现状态

`modules/platform-api` `0.5.1` 已从 M1 `/health` 扩展为真实数据库 API 和
本地开发工作流：

- 技术组合：FastAPI、Pydantic v2、SQLAlchemy 2.x、Alembic、PostgreSQL。
- 分层：`api`、`schemas`、`services`、`repositories`、`models`、`db`。
- 已实现：Project、Task、Requirement、Technical Design、DevelopmentPlan、
  AgentRun、ToolCall、Approval、Event Timeline、Artifact、本地
  PullRequestRecord。
- 已实现 M4 `start/run-next` 与 M6 `local-development/start/run-next`。
- 已接入 Agent Runtime 与 Tool Gateway，执行真实受控文件、pytest、Bandit、
  pip-audit、branch、commit 和 format patch。
- M7-1 已新增 Environment、受控 profile RemoteTarget、machine credential
  metadata/replay nonce、HMAC heartbeat 和 online/offline/recovery EventLog。
- M7-2B1 已新增 server-controlled RepositoryProfile、ProjectRepositoryBinding
  PUT/GET、配置幂等、repository identity advisory lock、Candidate/Approval
  漂移失效和 CORS PUT。
- M7-2B2 已新增严格空对象的 Candidate POST、active-first Candidate GET、
  第一道 L2 Approval approve/reject、PR/Binding/request freshness、自批门禁、
  原子 `release_candidate_reconcile` WorkflowJob 和精确事件。
- M7-2C 已交付 PostgreSQL 权威 dispatcher/worker、lease/heartbeat、retry、
  Redis 补投、stale reclaim 与纯数据库 reconcile handler。
- M7-2D 已新增 CIRun、Deployment、ServiceInstance migration/ORM/repository、
  第二道 L3 Approval CHECK、受控健康证据、真实行锁/部分唯一并发门禁，以及
  含 `allOf/if/then` 生命周期的严格共享 Record 契约。
- 远端 push、真实 Gitea CI、ReleasePlan、Deployment Controller、实际 Compose
  部署和监控仍在后续 M7-M8。

普通写操作通过 service 层在同一事务内写业务表和 `event_logs`。文件、Git 和
进程副作用使用短事务先抢占 ToolCall，再执行 handler，最后在后续事务写终态。

## M4 实现状态

`modules/platform-api` 已保留 M4 需求设计入口：

- 新增 Orchestration API：`start`、`run-next`、`orchestration state`。
- `start/run-next` 在 Task 行锁内推进；调用方可发送 `expected_phase`，阶段漂移
  返回 `409 orchestration_phase_changed`。
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
- `diff_patch` / `format_patch` Artifact 保存原始 UTF-8 bytes 与 SHA，ToolCall
  和 API preview 只返回脱敏安全投影。
- M6 基础设施失败会保存已发生的配对 provider call/output 与失败上下文，
  Task 按可恢复性暂停或失败。

## M7-1 实现状态

- `POST/GET /api/projects/{project_id}/environments` 与 Environment 详情。
- `POST/GET /api/environments/{environment_id}/remote-targets`；调用方只提交
  profile key，响应隐藏 credential ref 和完整 endpoint。
- `POST /api/remote-agents/heartbeat` 使用六个必填 HMAC headers、原始 body
  hash、timestamp tolerance 和 PostgreSQL nonce 唯一约束。
- machine-auth 使用独立短 Session 在线程池提交 nonce；heartbeat 状态事务使用
  Target 行锁。
- heartbeat 请求体默认限制 16 KiB；validation detail 不回显原始输入。
- secret fingerprint、credential lifecycle/scope、新旧 key 重叠和并发 replay
  均有真实 PostgreSQL 测试。
- 离线状态暂由目标列表或下一次 heartbeat reconciliation 触发；周期 worker、
  项目/环境 EventLog API 与实时 SSE 尚未实现。

## M7-2B1 实现状态

- `PUT/GET /api/projects/{project_id}/repository-binding` 只允许普通调用方提交
  profile key，响应隐藏 clone URL 与 credential ref。
- 首次创建以 Project 行作为 mutex；跨 Project identity 变更先取得事务级
  advisory namespace lock，避免并发 swap 死锁。
- 相同 active internal snapshot 不更新时间、不写事件；配置漂移使旧 active
  Candidate stale，并过期 pending Approval。
- RepositoryProfile 支持严格 UTF-8 JSON 文件或环境变量 map，拒绝重复 key、
  非 HTTPS URL、非法 Git ref 和缺失 credential。

## M7-2B2 实现状态

- `POST/GET /api/tasks/{task_id}/release-candidate` 已进入 FastAPI 与共享
  OpenAPI；POST 严格只接受 `{}`，首次创建 `201`，幂等命中 `200`。
- Candidate、第一道 L2 Approval、pending `release_candidate_reconcile`
  WorkflowJob 和创建事件在同一 PostgreSQL 事务写入，公开响应不包含 job id、
  clone URL、profile 或 credential。
- approve/reject 按 Task-first 锁序重验最新版 PR、Binding snapshot/hash、
  request hash、expiry、consumed 状态和实现 AgentRun 自批门禁。
- 新 PR 或 Binding 漂移会原子 stale 旧 Candidate，并使 pending Approval
  expired；锁等待后的决策时间使用 PostgreSQL `clock_timestamp()`。
- B2 没有 push、CI 或远端副作用。Redis/Celery durable Workflow Engine 属于
  M7-2C，现已由独立模块实现；Platform API 只提供 PostgreSQL repository、严格
  DTO、reconcile 事务服务与 Task pause/resume/cancel 联动，不反向依赖 Celery
  运行模块。

## 职责

统一 API 服务，对桌面端提供需求、任务、设计、事件、审批、配置接口。

## 当前技术栈

Python + FastAPI + Pydantic v2 + SQLAlchemy 2.x + Alembic + PostgreSQL。
Redis/Celery 由 `modules/workflow-engine` 使用，Platform API 仍不把 Redis 作为
业务权威或直接执行 worker。

## 上游依赖

PostgreSQL、Orchestrator、Tool Gateway。Redis 是 Ops Hub 中供独立 Workflow
Engine 使用的基础设施，不是 Platform API 的直接运行依赖。

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
