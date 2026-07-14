# modules/agent-runtime

> 来源：[设计书 7.1-7.2](../../../云舵 CloudHelm 毕设设计书.md)  
> 层级：`modules/agent-runtime`

## 职责

具体 Agent 实现，包括 Requirement、Planner、Architect、Coder、Tester、Reviewer、Security、Release、SRE 等角色。

## M4-M6 实现状态

`modules/agent-runtime` `0.4.0` 已实现八类普通 Agent：

- Requirement Agent：生成需求规格、约束和验收标准。
- Architect Agent：生成技术设计、OpenAPI 草案、DB schema 草案、Mermaid 和风险点。
- Planner Agent：生成 Development Plan 任务图和风险说明。
- Scaffold Agent：请求 `scaffold.prepare_workspace` 并引用真实 baseline/workspace
  证据。
- Coder Agent：根据已批准 recipe 提出 Repo/Sandbox/Git 调用并引用真实 diff。
- Tester Agent：只通过 `test.run_pytest` 消费 pytest/JUnit 证据。
- Reviewer Agent：逐条映射 AC、diff 与测试证据。
- Security Agent：只通过 `security.run_bandit` 和
  `security.run_pip_audit` 消费真实扫描结果。

默认 provider 为 `local_structured`，基于真实任务、已审批产物、execution
recipe 和工具结果生成结构化对象；`openai_compatible` provider 通过 HTTP SSE
Responses API 请求稳定扁平 JSON Schema 输出。八类普通角色共享完整 Task root
conversation，只有显式 spawn 才创建 child；瞬时请求和无效结构化响应执行可配置
有界重试。Agent Runtime 不写数据库、不直接执行工具，副作用统一由 Platform API
和 Tool Gateway 完成。

M6 工具步骤失败时，已真实发生的 function/custom call 与匹配 output 会和
`<failed_step_context>` 一并保存，供恢复后审计重试；失败步骤不会生成成功
业务产物。

## 技术栈

Python + Pydantic structured output + urllib HTTP SSE；工作流状态由
`modules/orchestrator` 的显式状态机负责。

## 上游依赖

LLM Gateway、Spec Store、Tool Gateway。

## 主要输出

结构化 Agent 输出、工具调用请求、评审结论。

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
