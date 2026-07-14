# Coder Agent

> 来源：[设计书 8.1](../../../云舵 CloudHelm 毕设设计书.md)

## 职责

根据需求和技术方案实现功能、修改代码、补测试、生成 patch。

## 允许工具

- `repo.read_file`
- `repo.search_text`
- `repo.list_files`
- `repo.write_file`
- `sandbox.run_command`
- `git.status`
- `git.diff`
- `git.create_branch`
- `git.commit`

## 主要输出

`CoderAgentOutput`：`branch_name`、`diff_paths`、changed files、verification、
tests added、ToolCall/Artifact 引用和 implementation summary。

## 风险边界

- 只能调用当前 execution recipe 按工具名、规范化参数和次数批准的动作。
- `repo.write_file` 只允许幂等 `replace`，可使用 `expected_sha256` 乐观锁。
- 本阶段只创建本地 branch/commit，不 push、不创建远端 PR。

## 与其他 Agent 的协作

- 输入来自上一阶段的结构化产物或平台事件。
- 输出必须被 Orchestrator 持久化，并可在控制台查看。
- 需要人工确认的结果必须生成 ApprovalRequest，而不是隐式继续执行。

## 验收点

1. 真实修改受控 workspace，生成非空 diff。
2. 输出 changed files、branch 和 diff 路径与 Tool/Git 证据一致。
3. 失败时保留已发生的配对 tool call/output 和可恢复原因。
4. 关键结果进入 AgentRun、ToolCall、Artifact 和 EventLog。
