# remote_targets

    > 来源：[设计书 11.2](../../../云舵 CloudHelm 毕设设计书.md)

    ## 业务含义

    远端部署目标，例如云服务器、Linux 主机、K8s namespace。

    ## SQL 定义

    ```sql
    CREATE TABLE remote_targets (
    id UUID PRIMARY KEY,
    environment_id UUID NOT NULL REFERENCES environments(id),
    target_type TEXT NOT NULL,
    host TEXT,
    ssh_user TEXT,
    agent_id TEXT,
    kube_context TEXT,
    namespace TEXT,
    status TEXT NOT NULL,
    last_heartbeat_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
    ```

    ## 实现说明

    - 主键使用 UUID，便于跨模块和事件引用。
    - 时间字段统一使用 `TIMESTAMPTZ`。
    - JSONB 字段用于保存结构化产物、工具参数、标签和注解。
    - 与高风险动作相关的记录必须能关联 `approval_requests` 或 `event_logs`。
