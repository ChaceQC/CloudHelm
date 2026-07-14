# packages/shared-contracts

共享契约包为 CloudHelm 各模块提供统一协议来源。

## 当前内容

- `openapi/cloudhelm.openapi.yaml`：Platform API 契约，覆盖 `/health`、Project、Task、Requirement、Technical Design、DevelopmentPlan、AgentRun、逐请求 Provider usage、ToolCall、Tool Gateway、Approval、Orchestration、M6 本地开发闭环和 Event Timeline。
- `schemas/events/task-event.schema.json`：M2-M6 真实 `event_logs` 字段和事件类型枚举，包括 `AgentConversationStopped` / `SubagentStopped` 会话终止事件、`ToolCallRejected` claim 前/重放策略拒绝、AgentRun/ToolCall 取消、Approval 过期和本地开发证据事件；Task 取消时由 `TaskCancelled.payload.cancelled_agent_conversations` 记录关闭数量。
- `schemas/agents/agent-common.schema.json`：八类普通 Agent 共用的稳定传输
  前缀，约束 schema 版本、角色、状态、摘要、证据引用、风险、阻塞项和
  ToolCall 摘要。
- `schemas/agents/*-agent-output.schema.json`：Requirement、Architect、
  Planner、Scaffold、Coder、Tester、Reviewer、Security 的角色专属严格输出；
  M6 Scaffold/Coder 额外绑定 workspace、baseline、branch、diff 等真实执行
  字段，字段集合与 Agent Runtime Pydantic model 精确一致。
- `schemas/artifacts/*.schema.json`：Artifact 安全详情与本地等价 PullRequestRecord 响应契约；不暴露内部 storage key 或工作区绝对路径。
- `schemas/tools/*.schema.json`：Tool Gateway 风险等级、ToolCallRequest/Result、
  Requirement、Design、Repo、Scaffold、Sandbox、Test、Security、Git Tool 契约。
  ToolCallRequest 覆盖成对的 Agent 与 provider call 身份；工具 schema 与当前
  Pydantic/registry 的名称、风险和参数字段执行一致性测试。
- `types/README.md`：后续生成类型的存放说明。

## 使用方

- `modules/platform-api`：实现 OpenAPI 中声明的 REST API。
- `apps/control-console`：按契约调用平台 API 并展示结构化结果。
- `modules/orchestrator`、`modules/tool-gateway`、`modules/agent-runtime`：按事件和工具 schema 写入状态、工具调用和审计记录。
