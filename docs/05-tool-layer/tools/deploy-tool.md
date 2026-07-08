# Deploy Tool

    > 来源：[设计书 9.4](../../../云舵 CloudHelm 毕设设计书.md)

    ## 职责

    `Deploy Tool` 是 Tool Layer 中的一个 MVP 工具组，通过 Tool Gateway 暴露给 Release / Deploy Agent。CI 只负责构建和交付制品，真实远端变更由 Agent 经审批后调用本工具执行。

    ## 函数清单

    ```text
    deploy.render_manifest(project_id, environment_id, version)
deploy.deploy_staging(project_id, version)
deploy.get_release_status(project_id, environment_id, deployment_id)
deploy.health_check(project_id, environment_id, service_id)
deploy.rollback_request(project_id, environment_id, target_version)
    ```

    ## 风险等级

    L3/L4：部署、回滚和 production 操作必须审批。

    ## 实现要点

    1. 所有参数都需要 schema 校验。
    2. 工具调用必须记录到 `tool_calls`。
    3. 失败结果必须返回结构化错误，供 Orchestrator 判断重试、暂停或请求人工接管。
    4. 涉及远端环境、部署、回滚、删除、生产数据的操作必须走审批。
    5. `deploy.deploy_staging` 的调用者应是 Release / Deploy Agent；工具内部再调用 Deployment Controller 和 Remote Agent 完成远端执行。
