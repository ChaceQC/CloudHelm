# Requirement Agent

> 来源：[设计书 8.1](../../../云舵 CloudHelm 毕设设计书.md)

## 职责

解析开发者输入的目标、需求文档、Issue、截图或接口说明，提取用户故事、约束和验收标准。

## 允许工具

`requirement.parse、spec.update、repo read`

## 主要输出

requirement_spec、clarification_questions、acceptance_criteria。

## 风险边界

不得写代码、提交 Git 或触发部署。

## 与其他 Agent 的协作

- 输入来自上一阶段的结构化产物或平台事件。
- 输出必须被 Orchestrator 持久化，并可在控制台查看。
- 需要人工确认的结果必须生成 ApprovalRequest，而不是隐式继续执行。

## 验收点

1. 能生成结构化结果。
2. 能在失败时给出可恢复原因。
3. 工具调用符合角色权限。
4. 关键结果能进入 EventLog / Artifact / Spec Store。
