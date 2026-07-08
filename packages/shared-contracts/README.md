# packages/shared-contracts

共享契约包为 CloudHelm 各模块提供统一协议来源。

## 当前内容

- `openapi/cloudhelm.openapi.yaml`：M5 Platform API 契约，覆盖 `/health`、Project、Task、Requirement、Technical Design、DevelopmentPlan、AgentRun、ToolCall、Tool Gateway、Approval、Orchestration 和 Event Timeline。
- `schemas/events/task-event.schema.json`：M2 真实 `event_logs` 事件字段和事件类型枚举。
- `schemas/tools/*.schema.json`：Tool Gateway 风险等级、ToolCallRequest/Result、Repo/Sandbox/Git/Requirement/Design Tool 契约。
- `types/README.md`：后续生成类型的存放说明。

## 使用方

- `modules/platform-api`：实现 OpenAPI 中声明的 REST API。
- `apps/control-console`：按契约调用平台 API 并展示结构化结果。
- `modules/orchestrator`、`modules/tool-gateway`、`modules/agent-runtime`：按事件和工具 schema 写入状态、工具调用和审计记录。
