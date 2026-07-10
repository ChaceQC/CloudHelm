# Development Plan API

> 来源：M4 `PROJECT_PLAN.md`、`docs/15-detailed-design/03-api-detail.md`
> 目的：记录 Planner Agent 产物的查询接口和边界。

## M4 已实现接口

```text
GET    /api/tasks/{task_id}/development-plans
GET    /api/development-plans/{plan_id}
```

## 响应字段

- `id`
- `task_id`
- `project_id`
- `technical_design_id`
- `summary`
- `steps_json`
- `risks_json`
- `status`
- `version`
- `created_by_agent_run_id`
- `created_at`
- `updated_at`

## 副作用与边界

- DevelopmentPlan 只由 Planner Agent 经 Orchestrator 写入，当前不提供外部创建接口。
- `steps_json` 是任务图和建议，不代表代码、工具或部署动作已经执行。
- 生成后会写入 `DevelopmentPlanCreated`，并创建 `ApprovalRequest(action=approve_development_plan)`。
- 计划审批通过后状态变为 `approved` 并写入 `DevelopmentPlanApproved`；拒绝或上游需求/设计返工后状态变为 `changes_requested` 并写入 `DevelopmentPlanChangesRequested`。
- Orchestrator 只复用关联当前最新版已批准 TechnicalDesign 的有效计划；旧设计对应计划或 `changes_requested` 计划不会阻止 Planner 重新生成。
- 后续 M5/M6 读取计划执行工具时，仍必须经过 Tool Gateway、Policy Engine 和必要审批。
