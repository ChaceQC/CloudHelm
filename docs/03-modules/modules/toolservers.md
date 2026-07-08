# modules/toolservers

> 来源：[设计书 7.1-7.2](../../../云舵 CloudHelm 毕设设计书.md)  
> 层级：`modules/toolservers`

## 职责

具体 MCP 工具服务，包括需求解析、设计生成、脚手架、代码仓库、Git、沙箱、部署和监控工具。

## 技术栈

FastMCP / MCP Python SDK + domain adapters。

## 上游依赖

Tool Gateway、Sandbox、Git、CI、Deploy、Remote、Monitoring。

## 主要输出

标准 MCP tools、工具执行结果、错误摘要。

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
