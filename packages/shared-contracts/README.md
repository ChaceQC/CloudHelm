# packages/shared-contracts

共享契约包为 CloudHelm 各模块提供统一协议来源。

## 当前内容

- `openapi/cloudhelm.openapi.yaml`：M1 API 标题、版本和 `/health` 路径。
- `schemas/events/task-event.schema.json`：后续任务事件流的基础字段。
- `schemas/tools/tool-risk-level.schema.json`：Tool Gateway 风险等级 `L0` 到 `L4`。
- `types/README.md`：后续生成类型的存放说明。

## 使用方

- `modules/platform-api`：实现 OpenAPI 中声明的 REST API。
- `apps/control-console`：按契约调用平台 API 并展示结构化结果。
- `modules/orchestrator`、`modules/tool-gateway`、`modules/agent-runtime`：后续按事件和工具 schema 写入状态、工具调用和审计记录。
