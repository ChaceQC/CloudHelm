# Scaffold Agent

> 来源：[设计书 8.1](../../../云舵 CloudHelm 毕设设计书.md)

## 职责

在已审批 DevelopmentPlan 和服务端 execution recipe 约束下，把只读 fixture
准备为 Task 独立 Git workspace，并返回 baseline 身份与文件证据。

## 允许工具

- `scaffold.prepare_workspace`
- `repo.read_file`
- `repo.search_text`
- `repo.list_files`

## 主要输出

`ScaffoldAgentOutput`：`workspace_key`、`baseline_branch`、
`baseline_commit`、`baseline_files`、verification、ToolCall 与 Artifact 引用。

## 风险边界

- fixture、workspace parent 和目标目录由 Platform API 绑定，模型不可提交本机路径。
- 相同 Task/baseline 的重放复用原 workspace，不覆盖 Coder 已修改文件。
- 仅准备本地 workspace，不 push、不部署。

## 与其他 Agent 的协作

- 输入来自上一阶段的结构化产物或平台事件。
- 输出必须被 Orchestrator 持久化，并可在控制台查看。
- 需要人工确认的结果必须生成 ApprovalRequest，而不是隐式继续执行。

## 验收点

1. `scaffold.prepare_workspace` 只调用一次并产生真实 ToolCall。
2. 输出 workspace/baseline 字段与 Tool 结果一致。
3. 越界路径、marker 冲突或 baseline 不一致时给出稳定失败原因。
4. 成功后进入 `Implementing`，关键结果进入 EventLog 与 Artifact。
