# Planner Agent

> 来源：[设计书 8.1](../../../云舵 CloudHelm 毕设设计书.md)

## 职责

理解开发目标、拆解步骤、评估风险、生成迭代计划和任务图。

## 允许工具

`只读 repo、issue、spec、日志、指标`

## 主要输出

development_plan、task_graph、risk_assessment。

## 风险边界

不得直接修改文件或远端环境。

## 与其他 Agent 的协作

- 输入来自上一阶段的结构化产物或平台事件。
- 输出必须被 Orchestrator 持久化，并可在控制台查看。
- 需要人工确认的结果必须生成 ApprovalRequest，而不是隐式继续执行。

## 验收点

1. 能生成结构化结果。
2. 能在失败时给出可恢复原因。
3. 工具调用符合角色权限。
4. 关键结果能进入 EventLog / Artifact / Spec Store。
