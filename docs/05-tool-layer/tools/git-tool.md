# Git Tool

    > 来源：[设计书 9.4](../../../云舵 CloudHelm 毕设设计书.md)

    ## 职责

    `Git Tool` 是 Tool Layer 中的一个 MVP 工具组，通过 Tool Gateway 暴露给 Agent。

    ## 函数清单

    ```text
    git.status()
git.diff()
git.create_branch(name)
git.commit(message)
git.revert(commit_id)
git.create_pr(title, body, base, head)
    ```

    ## 风险等级

    L2/L3：协作平台写操作和审批动作必须审计。

    ## 实现要点

    1. 所有参数都需要 schema 校验。
    2. 工具调用必须记录到 `tool_calls`。
    3. 失败结果必须返回结构化错误，供 Orchestrator 判断重试、暂停或请求人工接管。
    4. 涉及远端环境、部署、回滚、删除、生产数据的操作必须走审批。

## M5 落地

- 已实现：`git.status`、`git.diff`、`git.create_branch`、`git.commit`。
- `git.status`、`git.diff` 为 L0；`git.create_branch`、`git.commit` 为 L2。
- 只操作受控 `repo_root`，且要求传入路径是 Git 仓库根目录。
- 不实现 `push`、`create_pr`、`rebase`、`tag release`、`reset --hard`、`clean -fdx`。
