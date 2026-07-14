# packages/shared-contracts

> 来源：[设计书 7.1-7.2](../../../云舵 CloudHelm 毕设设计书.md)  
> 层级：`packages/shared-contracts`

## M6 实现状态

共享契约已同步当前 M6 API：

- `openapi/cloudhelm.openapi.yaml`：由 `modules/platform-api` 当前 FastAPI
  应用导出，版本 `0.5.1`，覆盖 M6 local-development、Artifact 与本地等价
  PR record API。
- `schemas/agents/*.schema.json`：覆盖 Requirement、Architect、Planner、
  Scaffold、Coder、Tester、Reviewer、Security 的稳定结构化输出。
- `schemas/artifacts/*.schema.json`：约束 Artifact 安全引用和本地 PR record。
- `schemas/events/task-event.schema.json`：覆盖 M1-M6 当前真实事件类型。
- `schemas/tools/*.schema.json`：描述 ToolCall、风险等级和 Requirement、Design、
  Repo、Scaffold、Sandbox、Test、Security、Git 已实现工具契约；名称、风险和
  参数字段与 Tool Gateway registry 执行一致性测试。

## 职责

跨模块共享协议、事件 schema、OpenAPI、工具 schema。

## 技术栈

OpenAPI + JSON Schema + generated Python/TypeScript SDK。

## 上游依赖

Platform API、Control Console、Tool Gateway、Agent Runtime。

## 主要输出

openapi.yaml、events.schema.json、tool.schema.json、SDK。

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
