# modules/orchestrator

CloudHelm M4 Orchestrator 模块提供 Requirement / Architect / Planner 闭环的显式状态机。

## M4 状态

```text
Created -> RequirementClarifying -> Designing -> WaitingDesignApproval -> Planning
Designing -> Planning
```

## 边界

- 本模块只定义状态、允许迁移、审批判定和纯函数校验。
- 真实数据库写入、AgentRun、RequirementSpec、TechnicalDesign、DevelopmentPlan 和 EventLog 由 `modules/platform-api` service 层在同一事务中完成。
- M4 不进入 Scaffolding / Implementing，不调用 Repo、Sandbox、Git、Docker、SSH 或部署工具。

## 命令

```powershell
uv run pytest
```
