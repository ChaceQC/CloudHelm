# Reviewer Agent

> 来源：[设计书 8.1](../../../云舵 CloudHelm 毕设设计书.md)

## 职责

审查 diff、指出风险、判断是否满足需求。

## 允许工具

- `repo.read_file`
- `repo.search_text`
- `repo.list_files`
- `git.status`
- `git.diff`

## 主要输出

`ReviewerAgentOutput`：verdict、逐 AC 结果、issues、changed files、
ToolCall 引用和 `proceed_to_security`。

## 风险边界

- 只读同一 evidence set 的 diff、TestReport 和已审批需求/计划。
- 不修改源码、不运行通用命令、不创建 commit 或 PR。
- verdict 与 `proceed_to_security` 必须一致；证据缺失时不得批准。

## 与其他 Agent 的协作

- 输入来自上一阶段的结构化产物或平台事件。
- 输出必须被 Orchestrator 持久化，并可在控制台查看。
- 需要人工确认的结果必须生成 ApprovalRequest，而不是隐式继续执行。

## 验收点

1. 每条 AC 映射到真实 diff/test 证据。
2. approved 且 `proceed_to_security=true` 才进入 SecurityScanning。
3. 要求修改时保存 ReviewReport 并回到 `Implementing`。
4. ReviewReport、ToolCall 和 EventLog 可由 API/控制台读取。
