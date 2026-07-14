# modules/tool-gateway

> 来源：[设计书 7.1-7.2](../../../云舵 CloudHelm 毕设设计书.md)  
> 层级：`modules/tool-gateway`

## 职责

工具统一入口，负责权限、审批、审计、限流、MCP 路由。

## M5-M6 实现状态

`modules/tool-gateway` `0.5.0` 当前注册：

- `requirement.normalize`、`design.render_markdown`
- `repo.read_file`、`repo.search_text`、`repo.list_files`、`repo.write_file`
- `scaffold.prepare_workspace`
- `sandbox.run_command`、`sandbox.collect_artifact`
- `test.run_pytest`
- `security.run_bandit`、`security.run_pip_audit`
- `git.status`、`git.diff`、`git.create_branch`、`git.commit`、
  `git.format_patch`
- `approval.request_remote_action`

Gateway 负责 Pydantic 参数校验、角色 allowlist、风险比对、审批拦截、workspace
边界、进程超时、输出脱敏和统一结果。数据库 ToolCall、Approval 与 EventLog 由
Platform API service 持久化；本模块本身不依赖 FastAPI 或数据库。

M6 仍使用受控目录与 `subprocess`，未启用独立 MCP Tool Server、Docker
sandbox 或分布式限流。

## 当前技术栈

Python + Pydantic + 本地工具 adapter。MCP Client、Redis 分布式限流和独立
Policy Engine 属于后续扩展。

## 上游依赖

Agent Runtime、Policy Engine、Approval API、MCP Tool Servers。

## 主要输出

tool_call、policy_decision、approval_request、审计事件。

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
