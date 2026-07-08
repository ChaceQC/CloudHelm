# Tool Layer 与 Tool Gateway

> 来源：[设计书 9.1-9.2](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：说明 Agent 调用工具时的统一入口和控制职责。
## Gateway 必须保证

- 参数校验在工具执行前完成。
- 风险等级和审批判断在工具执行前完成。
- 执行前后都写入 tool_calls / event_logs。
- 工具结果返回前需要脱敏和摘要化。

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
