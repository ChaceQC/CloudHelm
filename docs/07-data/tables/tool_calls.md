# tool_calls

    > 来源：[设计书 11.2](../../../云舵 CloudHelm 毕设设计书.md)

    ## 业务含义

    一次工具调用及其参数、结果、风险等级和审批关联。

    ## SQL 定义

    ```sql
    CREATE TABLE tool_calls (
    id UUID PRIMARY KEY,
    task_id UUID NOT NULL REFERENCES tasks(id),
    agent_run_id UUID REFERENCES agent_runs(id),
    tool_name TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    arguments_json JSONB NOT NULL,
    result_json JSONB,
    status TEXT NOT NULL,
    approval_id UUID,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ
);
    ```

    ## 实现说明

    - 主键使用 UUID，便于跨模块和事件引用。
    - 时间字段统一使用 `TIMESTAMPTZ`。
    - JSONB 字段用于保存结构化产物、工具参数、标签和注解。
    - 与高风险动作相关的记录必须能关联 `approval_requests` 或 `event_logs`。
