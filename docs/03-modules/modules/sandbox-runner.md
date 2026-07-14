# modules/sandbox-runner

> 来源：[设计书 7.1-7.2](../../../云舵 CloudHelm 毕设设计书.md)  
> 层级：`modules/sandbox-runner`

## 职责

目标职责是创建、销毁和清理 Docker sandbox，并以只读/可写挂载策略接入仓库
工作区。

## M1-M6 实现状态

独立 `modules/sandbox-runner` 尚未进入生产代码。M6 的 Sandbox Tool 由
`modules/tool-gateway` 提供，使用服务端 allowlist 的 Task 独立目录和受控
`subprocess`，具备：

- 命令数组和正向 command profile。
- 环境变量白名单。
- 超时、进程树清理和输出上限。
- workspace 路径边界和审计。

当前不具备 Docker 的 CPU、内存、PID、只读挂载和网络隔离，也不应把
Tool Gateway 的本地受控执行描述为已交付 Docker sandbox。

## 目标技术栈

Docker Engine + workspace manager + resource limits。引入前需补充 Windows
开发环境与 Linux 演示环境的兼容性、镜像来源、清理策略和故障注入测试。

## 上游依赖

Repo Tool、Sandbox Tool、Agent Runtime、Tool Gateway。

## 主要输出

目标输出为命令结果、测试报告、Artifact 和 sandbox session 状态。M6 当前只
持久化 ToolCall/Artifact，不存在 Docker sandbox session。

## MVP 实现要点

1. 先实现与全流程演示直接相关的 Docker 隔离能力，不重复实现 Tool Gateway
   已有的命令策略和审计。
2. 所有跨模块调用优先通过共享契约和 API，不直接耦合内部实现。
3. 状态变化、工具调用、审批、远程操作都必须写入事件或审计记录。
4. 与远端业务项目相关的操作必须绑定 `project_id + environment_id + deployment_id + service_id`。

## 测试关注点

- 参数校验和错误处理。
- 只读/可写挂载、CPU/内存/PID/网络限制与容器逃逸边界。
- 容器创建、超时终止、进程清理和残留资源回收。
- 与 Tool Gateway、Task workspace 和 Artifact 的集成路径。
- 关键输出是否能被控制台展示和被审计追踪。
