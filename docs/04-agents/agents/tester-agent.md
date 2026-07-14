# Tester Agent

> 来源：[设计书 8.1](../../../云舵 CloudHelm 毕设设计书.md)

## 职责

按照已审批 execution recipe 运行真实 pytest，解析退出码、JUnit 和 AC 映射，
生成可审计 TestReport。

## 允许工具

- `repo.read_file`
- `repo.list_files`
- `test.run_pytest`
- `git.status`
- `git.diff`

## 主要输出

`TesterAgentOutput`：commands、通过/失败/跳过计数、逐 AC 结果、失败原因、
ToolCall 和 `junit_xml` / `test_report` Artifact 引用。

## 风险边界

- workspace root、JUnit 路径、timeout 和输出上限由服务端绑定或校验。
- 不使用通用 `sandbox.run_command` 代替测试 profile。
- 不修改生产源码或测试来掩盖失败，不执行远端 CI。

## 与其他 Agent 的协作

- 输入来自上一阶段的结构化产物或平台事件。
- 输出必须被 Orchestrator 持久化，并可在控制台查看。
- 需要人工确认的结果必须生成 ApprovalRequest，而不是隐式继续执行。

## 验收点

1. pytest exit code、JUnit 统计、stdout/stderr 和结构化计数一致。
2. 每条 AC 均有可追溯结果。
3. 测试失败进入真实返工路径；命令缺失、超时或解析失败暂停 Task。
4. TestReport、JUnit、ToolCall 和 EventLog 可由 API/控制台读取。
