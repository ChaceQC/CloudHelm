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
- L3/L4 真实操作拦截由后续 Tool Gateway 与 Policy Engine 实现；M2 只记录审批数据流。

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
