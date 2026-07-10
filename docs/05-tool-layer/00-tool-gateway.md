# Tool Layer 与 Tool Gateway

> 来源：[设计书 9.1-9.2](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：说明 Agent 调用工具时的统一入口和控制职责。
## Gateway 必须保证

- 参数校验在工具执行前完成。
- 风险等级和审批判断在工具执行前完成。
- 执行前后都写入 tool_calls / event_logs。
- 工具结果返回前需要脱敏和摘要化。

## M5 落地状态

- 新增 `modules/tool-gateway`，提供 `ToolRegistry`、`ToolGateway`、`ToolPolicy` 和默认本地工具集。
- 执行流程为：查找工具声明 -> Pydantic 参数校验 -> 风险等级比对 -> L3/L4 审批拦截 -> handler 执行 -> 输出摘要和审计 hash。
- Platform API 新增 `GET /api/tool-gateway/tools` 与 `POST /api/tasks/{task_id}/tool-gateway/call`，所有调用写入 `tool_calls` 和 `event_logs`。
- L3/L4 或工具声明要求审批时，只创建 `approval_requests`，ToolCall 状态为 `waiting_approval`，不执行 handler。
- M5 使用按 `task_id` / `agent_run_id` 分组的进程内滑动窗口限流，默认 60 秒 60 次；超额调用写入失败 ToolCall 与 `ToolCallFailed` 事件，错误码为 `rate_limit_exceeded`。
- Agent 调用必须同时携带 `agent_run_id` 和由 Platform API 从数据库解析的 `agent_type`；AgentRun 必须属于当前任务且状态为 `running`。
- Git commit 只接受显式文件路径，拒绝仓库根目录和目录 pathspec，避免用 `.` 混入未审查改动。
- M5 Sandbox Tool 暂用本地受控目录 + `subprocess` 超时，Docker sandbox、网络隔离和资源 quota 留到 M6 前置增强。

限流参数通过 `CLOUDHELM_TOOL_RATE_LIMIT_CALLS` 和
`CLOUDHELM_TOOL_RATE_LIMIT_WINDOW_SECONDS` 配置。该实现满足 M5 本地单实例
边界；多 worker、跨进程或远端阶段必须迁移到 Redis 等共享存储。

## 设计书摘录

### 9.1 为什么要单独设计 Tool Layer

Agent 必须能调用工具，否则只能“建议怎么做”，不能完成真实软件工程闭环。但工具能力不能直接暴露给 Agent，否则会产生不可控风险。

因此采用三层结构：

```text
Agent
  -> Tool Gateway
      -> MCP Tool Server
          -> Requirement / Design / Scaffold / Sandbox / Git / CI / Deploy / Monitor / Security
```

### 9.2 Tool Gateway 职责

1. 工具注册与发现。
2. 工具参数校验。
3. 权限判断。
4. 风险分级。
5. 人类审批。
6. 限流和预算控制。
7. 工具调用审计。
8. 结果脱敏。
9. 失败重试。
10. trace 上报。
