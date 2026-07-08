# apps/control-console

> 来源：[设计书 7.1-7.2](../../../云舵 CloudHelm 毕设设计书.md)  
> 层级：`apps/control-console`

## 职责

桌面控制台，负责开发者需求输入、Agent 指导、方案审查、diff、日志、审批、远程状态和终端接管。

## 技术栈

Tauri + React + TypeScript + Tailwind CSS + shadcn/ui + Monaco Editor + xterm.js。

## 上游依赖

Project/Task/Event/Approval/Remote Ops API。

## 主要输出

需求输入、审批动作、接管动作、UI 事件订阅。

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
