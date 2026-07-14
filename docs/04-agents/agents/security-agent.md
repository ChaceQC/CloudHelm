# Security Agent

> 来源：[设计书 8.1](../../../云舵 CloudHelm 毕设设计书.md)

## 职责

消费真实 Bandit 与 pip-audit 结果，区分代码 finding、依赖漏洞、扫描器不可用、
报告解析失败和非阻断剩余风险。

## 允许工具

- `repo.read_file`
- `repo.search_text`
- `repo.list_files`
- `security.run_bandit`
- `security.run_pip_audit`
- `git.status`
- `git.diff`

## 主要输出

`SecurityAgentOutput`：verdict、blocking、scanner 结果、findings、剩余风险、
ToolCall 和 `security_report` Artifact 引用。

## 风险边界

- 不使用通用 `sandbox.run_command`、不修改源码、不关闭扫描规则。
- Bandit/pip-audit 工具不可用、超时或报告解析失败属于基础设施失败，暂停 Task。
- 代码或依赖 finding 按服务层门禁决定返工或进入 `ReadyForPR`，模型不能自行
  忽略阻断项。

## 与其他 Agent 的协作

- 输入来自上一阶段的结构化产物或平台事件。
- 输出必须被 Orchestrator 持久化，并可在控制台查看。
- 需要人工确认的结果必须生成 ApprovalRequest，而不是隐式继续执行。

## 验收点

1. 两类扫描器结果均来自真实 ToolCall。
2. findings、blocking、verdict 与服务层门禁一致。
3. 非阻断结论保存剩余风险，阻断结论回到 `Implementing`。
4. SecurityReport、ToolCall 和 EventLog 可由 API/控制台读取。
