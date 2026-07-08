# Remote Control Tool

    > 来源：[设计书 9.4](../../../云舵 CloudHelm 毕设设计书.md)

    ## 职责

    `Remote Control Tool` 是 Tool Layer 中的一个 MVP 工具组，通过 Tool Gateway 暴露给 Agent。

    ## 函数清单

    ```text
    remote.list_targets(project_id)
remote.service_status(project_id, environment_id, service_id)
remote.stream_logs(project_id, environment_id, service_id, since)
remote.ssh_exec_readonly(project_id, environment_id, command)
remote.open_terminal(project_id, environment_id)
remote.restart_service_request(project_id, environment_id, service_id)
remote.collect_diagnostics(project_id, environment_id, service_id)
    ```

    ## 风险等级

    L0/L3：查询为 L0，重启、终端、远端变更为 L3 及以上。

    ## 实现要点

    1. 所有参数都需要 schema 校验。
    2. 工具调用必须记录到 `tool_calls`。
    3. 失败结果必须返回结构化错误，供 Orchestrator 判断重试、暂停或请求人工接管。
    4. 涉及远端环境、部署、回滚、删除、生产数据的操作必须走审批。
