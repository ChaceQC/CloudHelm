# Approval Tool

    > 来源：[设计书 9.4](../../../云舵 CloudHelm 毕设设计书.md)

    ## 职责

    `Approval Tool` 是 Tool Layer 中的一个 MVP 工具组，通过 Tool Gateway 暴露给 Agent。

    ## 函数清单

    ```text
    approval.request(task_id, action, risk_level, reason)
approval.approve(approval_id)
approval.reject(approval_id, reason)
approval.pause(task_id)
approval.takeover(task_id)
    ```

    ## 风险等级

    L2/L3：协作平台写操作和审批动作必须审计。

    ## 实现要点

    1. 所有参数都需要 schema 校验。
    2. 工具调用必须记录到 `tool_calls`。
    3. 失败结果必须返回结构化错误，供 Orchestrator 判断重试、暂停或请求人工接管。
    4. 涉及远端环境、部署、回滚、删除、生产数据的操作必须走审批。

## M5 落地

- 已实现：`approval.request_remote_action`。
- 该工具是 L3 审批占位工具，只验证参数并创建 `ApprovalRequest`，不执行远端命令。
- 审批通过或拒绝只改变审批状态；M5 不自动恢复执行高风险动作。
