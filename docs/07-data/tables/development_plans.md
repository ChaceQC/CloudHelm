# development_plans

## 业务含义

保存 Planner Agent 针对最新 TechnicalDesign 生成的版本化开发任务图。M6 只能
执行当前最新版且已审批的计划。

## 关键字段

- `task_id`、`project_id`
- `technical_design_id`
- `summary`
- `steps_json`
- `risks_json`
- `status`
- `version`
- `created_by_agent_run_id`
- `created_at`、`updated_at`

## 约束与使用

- 新计划按 Task 递增 `version`。
- 需求或设计返工时，旧计划和相关待审批记录级联失效。
- M6 start 校验最新 Requirement、TechnicalDesign、DevelopmentPlan 引用链与审批
  状态；工具执行还必须匹配该计划对应的 execution recipe。
