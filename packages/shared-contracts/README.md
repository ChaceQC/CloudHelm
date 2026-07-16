# packages/shared-contracts

共享契约包为 CloudHelm 各模块提供统一协议来源。

## 当前内容

- `openapi/cloudhelm.openapi.yaml`：Platform API 契约，覆盖 `/health`、Project、Task、Requirement、Technical Design、DevelopmentPlan、AgentRun、逐请求 Provider usage、ToolCall、Tool Gateway、Approval、Orchestration、M6 本地开发闭环、Event Timeline，以及 M7 Environment、RemoteTarget、machine-auth heartbeat 和 RepositoryBinding PUT/GET。
- `openapi/cloudhelm-remote-agent.openapi.yaml`：M7-1 Remote Agent
  `/health`、`/version`、`/capabilities` 运行时契约；文件使用 JSON 语法保存，仍是
  有效 YAML，便于模块只用标准库执行精确匹配测试。
- `schemas/events/task-event.schema.json`：M2-M7-2C 真实 `event_logs` 字段和事件类型枚举，包括 `AgentConversationStopped` / `SubagentStopped` 会话终止事件、`ToolCallRejected` claim 前/重放策略拒绝、AgentRun/ToolCall 取消、Approval 过期、本地开发证据、WorkflowJob dispatch/worker/retry/cancel/recovery 事件，以及 Environment/RemoteTarget/RemoteAgent heartbeat 状态事件。
- `schemas/workflow/workflow-job.schema.json`：严格 broker message、
  `release_candidate_reconcile` payload/result 和 PostgreSQL WorkflowJob 读取
  契约；所有对象拒绝额外字段，broker 只允许 `workflow_job_id`。
- `schemas/ci/ci-run.schema.json`：M7-2D CIRun 完整 Record，绑定 Gitea
  workflow、candidate ref、commit、provider 幂等线索、run identity 和不可变
  制品证据；使用 `allOf/if/then` 表达可验证生命周期。
- `schemas/deployment/*.schema.json`：M7-2D Deployment 与 ServiceInstance 完整
  Record，约束 L3 Approval 投影、digest、operation、rollback、健康/失败证据和
  固定 `docker_compose` runtime；健康对象只允许小写受控 key 与 scalar value，
  拒绝凭据、敏感字段和原始日志。
- `schemas/agents/agent-common.schema.json`：八类普通 Agent 共用的稳定传输
  前缀，约束 schema 版本、角色、状态、摘要、证据引用、风险、阻塞项和
  ToolCall 摘要。
- `schemas/agents/*-agent-output.schema.json`：Requirement、Architect、
  Planner、Scaffold、Coder、Tester、Reviewer、Security 的角色专属严格输出；
  M6 Scaffold/Coder 额外绑定 workspace、baseline、branch、diff 等真实执行
  字段，字段集合与 Agent Runtime Pydantic model 精确一致。
- `schemas/artifacts/*.schema.json`：Artifact 安全详情与本地等价 PullRequestRecord 响应契约；不暴露内部 storage key 或工作区绝对路径。
- `schemas/remote/*.schema.json`：Environment create/read、RemoteTarget
  profile-only create/脱敏 read，以及 heartbeat request/ack。Platform API 与
  Remote Agent Pydantic model 会对共享 defs 做一致性测试。
- `schemas/tools/*.schema.json`：Tool Gateway 风险等级、ToolCallRequest/Result、
  Requirement、Design、Repo、Scaffold、Sandbox、Test、Security、Git Tool 契约。
  ToolCallRequest 覆盖成对的 Agent 与 provider call 身份；工具 schema 与当前
  Pydantic/registry 的名称、风险和参数字段执行一致性测试。
- `types/README.md`：后续生成类型的存放说明。

## 使用方

- `modules/platform-api`：实现 OpenAPI 中声明的 REST API。
- `modules/remote-agent`：实现独立 Remote Agent OpenAPI，并发送共享 heartbeat。
- `apps/control-console`：按契约调用平台 API 并展示结构化结果。
- `modules/workflow-engine`：按 workflow schema 解析 broker message，并把
  dispatch、lease、retry 与 terminal 结果写回 PostgreSQL。
- `modules/orchestrator`、`modules/tool-gateway`、`modules/agent-runtime`：按事件和工具 schema 写入状态、工具调用和审计记录。
