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
- L3/L4 真实操作拦截由后续 Tool Gateway 与 Policy Engine 实现；M4 只记录审批数据流和设计/计划审查请求。

## M4 使用方式

M4 自动创建两类审批请求：

- `approve_technical_design`：Architect Agent 识别到 L2 及以上设计风险时创建。
- `approve_development_plan`：Planner Agent 生成 DevelopmentPlan 后创建，作为进入后续 M5/M6 工具执行前的人工确认。

审批本身不执行工具、不修改代码、不部署远端环境；后续推进仍需调用 Orchestration API 或进入后续里程碑。

## M5 Tool Gateway 使用方式

- Tool Gateway 遇到 L3/L4 或工具声明 `requires_approval=true` 时，在同一事务内创建 `approval_requests`。
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
