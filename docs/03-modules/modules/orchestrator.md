# modules/orchestrator

> 来源：[设计书 7.1-7.2](../../../云舵 CloudHelm 毕设设计书.md)  
> 层级：`modules/orchestrator`

## 职责

核心编排器，定义需求到设计、实现、测试、PR、部署、监控的状态机和 Agent 协作流程。

## M4 实现状态

`modules/orchestrator` 已实现 M4 显式状态机，当前覆盖：

```text
Created -> RequirementClarifying -> Designing -> WaitingDesignApproval -> Planning
Designing -> Planning
```

该模块保持纯状态机和边界类型，不直接写数据库；Platform API 的 `OrchestrationService` 负责事务内持久化 Task、AgentRun、业务产物和 EventLog。LangGraph / Redis worker 暂未引入，后续如需要异步图执行再按 M5+ 计划补充。

## 技术栈

LangGraph + Python workers + Redis queue。

## 上游依赖

Task、RequirementSpec、TechnicalDesign、Agent Runtime、Tool Gateway。

## 主要输出

workflow_run、状态迁移、重试、human-in-the-loop 事件。

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
