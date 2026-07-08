# Scaffold Agent

> 来源：[设计书 8.1](../../../云舵 CloudHelm 毕设设计书.md)

## 职责

根据模板创建项目骨架、模块目录、配置文件、CI 文件和基础测试。

## 允许工具

`scaffold.generate、repo write、sandbox exec`

## 主要输出

project skeleton、module files、CI config。

## 风险边界

仅能写 sandbox worktree。

## 与其他 Agent 的协作

- 输入来自上一阶段的结构化产物或平台事件。
- 输出必须被 Orchestrator 持久化，并可在控制台查看。
- 需要人工确认的结果必须生成 ApprovalRequest，而不是隐式继续执行。

## 验收点

1. 能生成结构化结果。
2. 能在失败时给出可恢复原因。
3. 工具调用符合角色权限。
4. 关键结果能进入 EventLog / Artifact / Spec Store。
