# service_instances

    > 来源：[设计书 11.2](../../../云舵 CloudHelm 毕设设计书.md)

    ## 业务含义

    远端业务服务实例，例如 API、Worker、Frontend。

    ## SQL 定义

    ```sql
    CREATE TABLE service_instances (
    id UUID PRIMARY KEY,
    deployment_id UUID NOT NULL REFERENCES deployments(id),
    environment_id UUID NOT NULL REFERENCES environments(id),
    service_name TEXT NOT NULL,
    runtime_type TEXT NOT NULL,
    runtime_ref TEXT,
    status TEXT NOT NULL,
    health_url TEXT,
    last_health_check_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
    ```

    ## 实现说明

    - 主键使用 UUID，便于跨模块和事件引用。
    - 时间字段统一使用 `TIMESTAMPTZ`。
    - JSONB 字段用于保存结构化产物、工具参数、标签和注解。
    - 与高风险动作相关的记录必须能关联 `approval_requests` 或 `event_logs`。
