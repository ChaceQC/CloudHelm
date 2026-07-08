# modules/agent-runtime

> 来源：[设计书 7.1-7.2](../../../云舵 CloudHelm 毕设设计书.md)  
> 层级：`modules/agent-runtime`

## 职责

具体 Agent 实现，包括 Requirement、Planner、Architect、Coder、Tester、Reviewer、Security、Release、SRE 等角色。

## 技术栈

Python + LiteLLM + Pydantic structured output + LangGraph node。

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
