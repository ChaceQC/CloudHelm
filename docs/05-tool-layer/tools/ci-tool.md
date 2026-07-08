# CI Tool

    > 来源：[设计书 9.4](../../../云舵 CloudHelm 毕设设计书.md)

    ## 职责

    `CI Tool` 是 Tool Layer 中的一个 MVP 工具组，通过 Tool Gateway 暴露给 Agent。

    ## 函数清单

    ```text
    ci.get_workflow_status(repo, run_id)
ci.get_failed_jobs(repo, run_id)
ci.get_job_logs(repo, job_id)
ci.rerun_job(repo, job_id)
    ```

    ## 风险等级

    L0-L1：以只读或本地设计/规格写入为主，按具体函数判定。

    ## 实现要点

    1. 所有参数都需要 schema 校验。
    2. 工具调用必须记录到 `tool_calls`。
    3. 失败结果必须返回结构化错误，供 Orchestrator 判断重试、暂停或请求人工接管。
    4. 涉及远端环境、部署、回滚、删除、生产数据的操作必须走审批。
