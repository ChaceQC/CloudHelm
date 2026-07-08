# approval_requests

    > 来源：[设计书 11.2](../../../云舵 CloudHelm 毕设设计书.md)

    ## 业务含义

    审批请求，承载高风险工具或设计动作的人工决策。

    ## SQL 定义

    ```sql
    CREATE TABLE approval_requests (
    id UUID PRIMARY KEY,
    task_id UUID NOT NULL REFERENCES tasks(id),
    action TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL,
    requested_by_agent_run_id UUID REFERENCES agent_runs(id),
    decided_by TEXT,
    decided_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
    ```

    ## 实现说明

    - 主键使用 UUID，便于跨模块和事件引用。
    - 时间字段统一使用 `TIMESTAMPTZ`。
    - JSONB 字段用于保存结构化产物、工具参数、标签和注解。
    - 与高风险动作相关的记录必须能关联 `approval_requests` 或 `event_logs`。
