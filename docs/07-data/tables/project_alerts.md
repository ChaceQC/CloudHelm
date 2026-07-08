# project_alerts

    > 来源：[设计书 11.2](../../../云舵 CloudHelm 毕设设计书.md)

    ## 业务含义

    远端业务项目告警。

    ## SQL 定义

    ```sql
    CREATE TABLE project_alerts (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id),
    environment_id UUID NOT NULL REFERENCES environments(id),
    service_instance_id UUID REFERENCES service_instances(id),
    alert_name TEXT NOT NULL,
    severity TEXT NOT NULL,
    status TEXT NOT NULL,
    source TEXT NOT NULL,
    labels JSONB NOT NULL DEFAULT '{}',
    annotations JSONB NOT NULL DEFAULT '{}',
    fired_at TIMESTAMPTZ NOT NULL,
    resolved_at TIMESTAMPTZ
);
    ```

    ## 实现说明

    - 主键使用 UUID，便于跨模块和事件引用。
    - 时间字段统一使用 `TIMESTAMPTZ`。
    - JSONB 字段用于保存结构化产物、工具参数、标签和注解。
    - 与高风险动作相关的记录必须能关联 `approval_requests` 或 `event_logs`。
