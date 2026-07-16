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

- `POST /api/tasks/{task_id}/approvals` 是内部联调用记录接口，状态默认为 `pending`；
  它不得创建 M7 保留 action `approve_release_candidate`，提交该 action 返回
  `422 approval_action_reserved`。
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

## M7-2 资源审批扩展

M7-2 为 `approval_requests` 增加以下 nullable 字段，并保持 M1-M6 记录兼容：

- `resource_type`
- `resource_id`
- `request_hash`
- `expires_at`
- `consumed_at`

ReleaseCandidate 审批固定为：

```text
action=approve_release_candidate
risk_level=L2
resource_type=release_candidate
resource_id=<candidate UUID>
request_hash=<candidate request hash>
```

`approve_release_candidate` 当且仅当 `resource_type=release_candidate`，且
`risk_level=L2`。数据库 CHECK 实施双向约束；ApprovalDomainDecisionService 必须
同时按 action 与 resource type 分派。CandidateService 使用受控内部创建方法，
通用 Approval create endpoint 不能绕过 Candidate、resource/hash/expiry 原子事务。

CandidateService 固定把
`requested_by_agent_run_id` 设为
`PullRequestRecord.created_by_agent_run_id`；缺失时 Candidate 创建返回
`409 m6_pull_request_creator_required`。approve/reject 将 trim 后的 plain UUID
或 `agent-run:<UUID>` actor id 规范化为 UUID，与该实现 AgentRun 相同则返回
`403 approval_self_decision_forbidden`。

第一道审批决策用无锁 hint 找到 Candidate/Binding 后，固定按
`Task -> ProjectRepositoryBinding -> ReleaseCandidate -> Approval` 加锁并重验
身份、snapshot/request hash 与 expiry；不得使用
`Task -> Approval -> Candidate` 的反向锁序。

资源字段、request hash 和 expiry 必须成组出现。approve/reject 在同一短事务更新
Approval 与 Candidate，但不 push、不 dispatch CI、不创建外部副作用；
`consumed_at` 只在后续显式 publish 步骤原子消费。M7-2 不修改 Task status 或
current phase；完整 Orchestrator 状态推进在后续 M7 纵切接入。

同一 `resource_type/resource_id/action` 只允许一条审批记录。release candidate
被 rejected 后，重复 Candidate POST 返回原 Candidate/Approval；重新申请必须有新
PR record 或新 binding snapshot。

后续消费资源审批时必须在同一行锁事务重新校验：

```text
status=approved
consumed_at IS NULL
expires_at > 锁后有效消费时间
resource_type/resource_id/request_hash 与当前资源完全一致
```

approve/reject 必须先按规定顺序锁定 Task、领域资源和 Approval，再读取
`clock_timestamp()`，并取不早于资源与 Approval 已持久化审计时间的有效决策
时间。只有该时间 `< expires_at` 才可决策；数据库约束 approved/rejected 的
`decided_at < expires_at`，过期决策返回 `409 approval_expired`。

校验通过后才写锁后有效消费时间；数据库约束要求
`decided_at <= consumed_at < expires_at`。Approval approve HTTP 本身不写该字段。

binding、PR 或 request hash 漂移导致 pending Approval 失效时，系统固定写
`status=expired`、`decided_by=system:release_candidate_freshness` 和数据库
锁后有效决策时间，不伪装成用户 reject。

过期、request hash/snapshot 漂移、已消费或实现 AgentRun 自批返回稳定冲突/权限
错误。当前 `DecisionRequest.actor_id` 仍是受控入口传入的审计字符串，因此本切片的
AgentRun ID 比对属于领域门禁，不描述为不可伪造的身份认证边界。

M9 后 Approval 决策从 access token 派生 `decided_by_user_id`，按 permission、
system/project/environment scope、resource version 和服务端 provenance 校验。
AgentRun/ReleaseCandidate/Deployment 保存人类发起者引用；职责分离比较认证
user，不接受请求体 actor 参与授权。Approval 详情返回服务端计算的
`allowed_actions`，供 Desktop 正确禁用自己的审批按钮。

`approve_technical_design` 在 M9 还必须绑定当前
`technical_design_id + version + content_sha256`。服务端保存并重验
`last_modified_source/last_modified_by_user_id/last_modified_by_agent_run_id`；
content hash 使用 `technical-design-content.v1` stable canonical object；Agent
生成/重写时通过
`agent_runs.initiated_by_user_id` 解析人类发起者。审批人等于当前版本最后修改者
或 AgentRun 发起者时返回 `403 self_approval_forbidden`，版本/hash 漂移返回
`409 stale_approval`。

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
