# types

本目录预留给 OpenAPI 和 JSON Schema 生成的 Python/TypeScript 类型。M6 仍由
Platform API Pydantic、Agent Runtime Pydantic、Tool Gateway Pydantic 与前端
手写类型配合精确一致性测试维护契约，尚未提交生成 SDK。

后续启用生成链路时，生成源只能是
`packages/shared-contracts/openapi/cloudhelm.openapi.yaml` 和
`packages/shared-contracts/schemas/`，生成文件必须可复现且随契约变更更新。
