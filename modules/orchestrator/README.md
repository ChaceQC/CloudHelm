# modules/orchestrator

CloudHelm Orchestrator `0.4.0` 提供 M4 需求设计闭环与 M6 本地开发闭环的显式
纯状态机。

## M4 状态

```text
Created -> RequirementClarifying -> Designing -> WaitingDesignApproval -> Planning
Designing -> Planning
```

## M6 状态

```text
Planning -> Scaffolding -> Implementing -> Testing -> Reviewing
  -> SecurityScanning -> ReadyForPR -> PullRequestCreated
```

测试、审查或安全门禁要求修改时可回到 `Implementing`。`PullRequestCreated`
只表示本地 branch、commit、format patch 和等价 PR record 已形成，不是 Task
终态；M7 从该阶段继续 CI 与远端部署。

## 边界

- 本模块只定义状态、允许迁移、审批判定和纯函数校验。
- 真实数据库写入、AgentRun、RequirementSpec、TechnicalDesign、
  DevelopmentPlan、Artifact、PullRequestRecord 和 EventLog 由
  `modules/platform-api` service 层完成。
- Orchestrator 不直接调用 Repo、Sandbox、Git、Docker、SSH 或部署工具；
  Platform API 的 M6 service 依据状态机，经 Tool Gateway 执行副作用。

## 命令

```powershell
uv run pytest
```
