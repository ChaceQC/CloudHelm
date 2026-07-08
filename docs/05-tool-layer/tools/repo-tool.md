# Repo Tool

    > 来源：[设计书 9.4](../../../云舵 CloudHelm 毕设设计书.md)

    ## 职责

    `Repo Tool` 是 Tool Layer 中的一个 MVP 工具组，通过 Tool Gateway 暴露给 Agent。

    ## 函数清单

    ```text
    repo.list_files(path)
repo.read_file(path)
repo.write_file(path, content)
repo.search_code(query)
repo.apply_patch(patch)
    ```

    ## 风险等级

    L1：本地 sandbox/worktree 写操作，必须审计。

    ## 实现要点

    1. 所有参数都需要 schema 校验。
    2. 工具调用必须记录到 `tool_calls`。
    3. 失败结果必须返回结构化错误，供 Orchestrator 判断重试、暂停或请求人工接管。
    4. 涉及远端环境、部署、回滚、删除、生产数据的操作必须走审批。

## M5 落地

- 已实现：`repo.read_file`、`repo.search_text`、`repo.write_file`、`repo.list_files`。
- 所有工具参数包含 `workspace_root`，路径必须解析到该根目录内。
- 拒绝 `.env`、私钥、证书、`.git`、依赖目录、构建产物和 symlink 越界。
- `repo.write_file` 为 L1，默认只写 UTF-8 文本，写入结果进入 `tool_calls.result_summary`。
