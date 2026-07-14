# packages

本目录保存跨模块共享包。当前 `shared-contracts` 承载：

- Platform API OpenAPI；
- M2-M6 Task Event JSON Schema；
- 八类普通 Agent 输出 JSON Schema；
- Artifact 与 PullRequestRecord JSON Schema；
- ToolCall、风险等级以及 Requirement、Design、Repo、Scaffold、Sandbox、
  Test、Security、Git 工具 JSON Schema。

`types/` 仍只保留生成类型的目录约定；正式生成 Python/TypeScript SDK 时必须
由当前 OpenAPI/JSON Schema 自动生成并纳入一致性验证。
