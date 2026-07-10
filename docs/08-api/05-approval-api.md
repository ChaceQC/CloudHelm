# Approval API

> 来源：[设计书 12 章](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：给出该 API 分组的端点清单和实现注意点。

## M2 已实现接口

```text
POST   /api/tasks/{task_id}/approvals
GET    /api/approvals
GET    /api/approvals/{approval_id}
POST   /api/approvals/{approval_id}/approve
POST   /api/approvals/{approval_id}/reject
```

- `POST /api/tasks/{task_id}/approvals` 是内部联调用记录接口，状态默认为 `pending`。
- 通过和拒绝必须处于 `pending` 状态；重复决策返回状态冲突错误。
- 创建、通过、拒绝分别写入 `ApprovalRequested`、`ApprovalApproved`、`ApprovalRejected`。
- `GET /api/approvals` 支持 `task_id`、`status`、`limit`、严格非负十进制 `cursor`，按最新记录优先；控制台按当前任务在服务端过滤，避免分页后再做前端过滤导致记录缺失。
- 创建审批时，`requested_by_agent_run_id` 必须属于路径中的当前任务。
- L3/L4 真实操作已由 M5 Tool Gateway 与 Policy Engine 拦截；审批通过后的自动恢复执行仍属于后续里程碑。
- Task 取消时 pending Approval 自动变为 `expired` 并写 `ApprovalExpired`。

## M4 使用方式

M4 自动创建两类审批请求：

- `approve_technical_design`：Architect Agent 识别到 L2 及以上设计风险时创建。
- `approve_development_plan`：Planner Agent 生成 DevelopmentPlan 后创建，作为进入后续 M5/M6 工具执行前的人工确认。

设计和开发计划审批只对创建当前最新版产物的 AgentRun 有效；旧设计、旧计划或旧 AgentRun 的历史 Approval 不得复用于新产物，过期审批返回 `409 stale_approval`。

- 通过 `approve_technical_design` 会同步把当前 TechnicalDesign 标记为 `approved`；直接调用 TechnicalDesign approve API 时，也会同步关闭匹配的待审批记录。
- 拒绝 `approve_technical_design` 或对设计请求修改时，设计变为 `changes_requested`，任务回退到 `Designing`，基于该设计的旧 DevelopmentPlan 及其待审批记录同时失效。
- 通过 `approve_development_plan` 会把当前计划标记为 `approved`，任务从 `waiting_approval` 回到 `running`。
- 拒绝计划会把计划标记为 `changes_requested` 并保持 `Planning`，下一次 `run-next` 必须生成新计划。
- 需求请求修改时回退到 `RequirementClarifying`，旧 TechnicalDesign、DevelopmentPlan 及相关待审批记录一并失效。

审批本身不执行工具、不修改代码、不部署远端环境；后续推进仍需调用 Orchestration API 或进入后续里程碑。

## M5 Tool Gateway 使用方式

- Tool Gateway 遇到 L3/L4 或工具声明 `requires_approval=true` 时，在工具执行后的终态事务中创建 `approval_requests` 并关联已抢占的 ToolCall；handler 不执行。
- 关联 ToolCall 的 `status=waiting_approval`，`approval_id` 指向审批请求。
- M5 审批通过或拒绝仍只记录决策，不自动补执行高风险工具；补执行语义留到后续 Release / Deploy 和审批恢复流程。

## 实现注意点

- 请求和响应模型应写入 OpenAPI，并同步生成前端类型。
- 涉及任务状态、工具调用、审批和远端操作的接口必须写事件日志。
- 列表接口需要分页、过滤和按 project/environment/task 过滤。

## 设计书摘录

### 12.4 Approval API

```text
GET    /api/approvals
GET    /api/approvals/{approval_id}
POST   /api/approvals/{approval_id}/approve
POST   /api/approvals/{approval_id}/reject
```
