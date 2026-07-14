# Sandbox Tool

    > 来源：[设计书 9.4](../../../云舵 CloudHelm 毕设设计书.md)

    ## 职责

    `Sandbox Tool` 是 Tool Layer 中的一个 MVP 工具组，通过 Tool Gateway 暴露给 Agent。

    ## 函数清单

    ```text
    sandbox.exec(command, cwd, timeout)
sandbox.install_deps(command)
sandbox.run_tests(command)
sandbox.collect_artifacts()
sandbox.reset()
    ```

    ## 风险等级

    L1：本地 sandbox/worktree 写操作，必须审计。

    ## 实现要点

    1. 所有参数都需要 schema 校验。
    2. 工具调用必须记录到 `tool_calls`。
    3. 失败结果必须返回结构化错误，供 Orchestrator 判断重试、暂停或请求人工接管。
    4. 涉及远端环境、部署、回滚、删除、生产数据的操作必须走审批。

## M5-M6 落地

- 已实现：`sandbox.run_command`、`sandbox.collect_artifact`。
- M6 继续使用本地受控目录 + `subprocess` 超时，不接 Docker，不提供 shell 接管。
- 命令必须是数组形式，默认拒绝 shell、高危删除、网络扫描、SSH、全局依赖安装和后台常驻命令。
- stdout/stderr 只保存摘要，完整 artifact 只允许在 workspace 内收集元数据。
- 通用 `sandbox.run_command` 只供 Coder 等明确角色使用；Tester 和 Security 的
  M6 Instructions 分别要求使用 `test.run_pytest` 与 `security.run_*` profile。
- Docker CPU、内存、PID、只读挂载和网络隔离已记录为后续增强，M7 远端部署前
  再次评估。
