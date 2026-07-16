# 工作流状态与事件细化

> 来源：设计书 8.2、10 章、15 章  
> 目的：把核心业务流程拆成状态、事件、参与模块和失败恢复路径。

## M2 事件落地状态

M2 已把以下事件写入真实 PostgreSQL `event_logs`：

```text
ProjectCreated
TaskCreated
TaskPaused
TaskResumed
TaskCancelled
RequirementSpecCreated
RequirementSpecApproved
RequirementSpecChangesRequested
TechnicalDesignCreated
TechnicalDesignApproved
TechnicalDesignChangesRequested
AgentRunRecorded
ToolCallRecorded
ApprovalRequested
ApprovalApproved
ApprovalRejected
AgentRunCancelled
ToolCallCancelled
ApprovalExpired
```

## M4 事件落地状态

M4 新增以下真实事件：

```text
TaskPhaseChanged
AgentRunStarted
AgentRunCompleted
AgentRunFailed
DevelopmentPlanCreated
DevelopmentPlanApproved
DevelopmentPlanChangesRequested
AgentConversationCreated
AgentConversationStopped
SubagentSpawned
SubagentCompleted
SubagentStopped
```

其中 `SubagentSpawned/Completed/Stopped` 目前只由内部 conversation
service/policy 与测试路径产生，用于持久化 child 生命周期原语；生产编排尚未接入
真实 child AgentRun/provider 调度、wait-all、steer/queue、独立 thread API/UI
或 workspace/worktree scheduler。不得把这些事件描述为完整多 Agent 调度已上线。

Requirement Agent 成功后写 `RequirementSpecCreated` 并进入 `Designing`；Architect Agent 成功后写 `TechnicalDesignCreated`，低风险进入 `Planning`，L2 及以上写 `ApprovalRequested` 并进入 `WaitingDesignApproval`；Planner Agent 成功后写 `DevelopmentPlanCreated`，并创建 `approve_development_plan` 审批请求。计划审批通过写 `DevelopmentPlanApproved`；计划被拒绝或因需求/设计返工失效时写 `DevelopmentPlanChangesRequested`。M4 不写代码、不执行工具、不部署远端环境。

需求或设计被请求修改时必须产生真实回退：Requirement 回到 `RequirementClarifying`，TechnicalDesign 回到 `Designing`；下游旧设计、旧计划和匹配的待审批记录同时失效。设计/计划审批必须绑定当前最新版产物的 `created_by_agent_run_id`；M9 后设计审批进一步绑定 design id/version/content hash 和当前版本修改者 provenance，历史审批不能批准新产物，最后修改者或其 AgentRun 的人类发起者不能自批。任务暂停只切换运行状态并保留业务阶段；恢复时从最近一次 `TaskPaused.payload.from_status` 恢复暂停前状态，如果暂停期间待审批已经完成，则恢复到 `running`。

任务取消会级联关闭 active AgentRun、active root/child conversation、
active/waiting ToolCall 和 pending Approval。root conversation 写入
`AgentConversationStopped`，child conversation 写入 `SubagentStopped`，
并为两者设置 `status=cancelled`、`completed_at`；其他资源分别写入
`AgentRunCancelled`、`ToolCallCancelled`、`ApprovalExpired`。最后写入
`TaskCancelled`，其 payload 通过 `cancelled_agent_conversations` 记录本次关闭
的会话数量。

外部模型瞬时请求或无效结构化响应先执行有界重试；耗尽后写
`AgentRunFailed(recoverable=true)` 并暂停 Task，保留当前业务阶段。认证等
不可重试错误进入失败状态。

Requirement、Architect、Planner 的普通角色变化只增加同一 Task root
conversation 的 turn。首次模型步骤写 `AgentConversationCreated`；只有显式
spawn 才写 `SubagentSpawned` 并创建 child。child 完成写
`SubagentCompleted`，失败或取消写 `SubagentStopped`；父线程只收到
`<subagent_notification>`，不复制 child 的 encrypted reasoning 和工具历史。

每个模型步骤在 `AgentRunStarted` 后开启数据库 savepoint。成功时，业务产物、
`AgentRunCompleted`、root conversation turn 与产物事件共同释放 savepoint，
再由 Orchestrator 提交阶段迁移；任一晚期持久化错误会回滚 savepoint，只保留
`AgentRunStarted`，随后写 `AgentRunFailed`。因此不能出现“失败 AgentRun
同时留下成功产物或递增 conversation turn”的半提交状态。

Timeline API 先取最新一页事件，再按当前页时间升序返回；SSE 端点输出当前
已有事件并追加 heartbeat。控制台固定退避重连、按 event id 去重，并同步
刷新 Task Detail 与 Task Board。M2 不做长连接实时推送，不使用内存事件队列
模拟生产事件流。

外部模型增量输出同样使用 HTTP SSE Responses API；本阶段不实现模型
WebSocket 流程。

## 0.1 M7-M10 常驻工作流与 Desktop 同步目标（规划）

正式远端流程：

```text
API 命令/审批事务
  -> 业务状态 + EventLog + WorkflowJob
  -> commit
  -> durable dispatcher / worker 自动继续
  -> 到达 approval/input gate 后持久等待
```

M4/M6 当前 `run-next` 是已实现的逐步编排入口；M7/M8 目标中的同名入口只保留
调试、答辩演示和人工恢复用途。Desktop 退出后，已持久化且无需新审批的 CI、
部署、监控和 Agent 工作继续。

EventLog 后续增加单调 `sequence`、project/aggregate identity/version、
`schema_version` 和 user/device/session actor refs。Desktop 使用
snapshot + after_sequence + SSE live tail 补齐；SSE `id` 为 sequence，权限过滤
导致的空洞正常，游标过期返回 `event_cursor_reset_required`。

## 1. 状态机总表

|状态|进入条件|执行者|主要动作|退出条件|
|---|---|---|---|---|
|Created|TaskCreated|Platform API|持久化任务，广播事件|auto_start 或用户启动|
|RequirementClarifying|任务开始|Requirement Agent|解析需求、生成验收标准|需求完整或需要用户澄清|
|Designing|需求通过|Architect Agent|生成 ADR、OpenAPI、DB schema|低风险自动通过或进入设计审批|
|WaitingDesignApproval|设计高风险或用户要求|具备 `design.review` 且通过 SoD 的 Human|审批、拒绝、补充约束|approved / rejected|
|Planning|设计通过|Planner Agent|拆分任务图和风险|计划生成|
|Scaffolding|新项目/新模块|Scaffold Agent|生成骨架、配置、基础测试|骨架完成|
|Implementing|已有项目或脚手架完成|Coder Agent|修改代码、补测试|实现完成或失败|
|Testing|实现完成|Tester Agent|运行单元/集成/E2E 测试|测试通过或失败|
|Reviewing|测试通过|Reviewer Agent|需求符合度和代码审查|通过或要求修改|
|SecurityScanning|评审通过|Security Agent|Semgrep/Trivy/依赖扫描|通过或失败|
|PullRequestCreated|M6 质量门禁通过|Git Tool / Platform API|保存 branch、commit 和本地等价 PR record；由严格空对象的 candidate POST 原子创建第一道审批|请求 release candidate approval|
|WaitingMergeApproval|release candidate approval 已创建|具备 `release_candidate.decide` 且非实现/request owner 的 Human|审批 M6 精确 commit、受控 candidate ref 和 request hash|approved / rejected；此名称不表示 push 自动触发 CI|
|CIValidating|第一道审批通过并发布 candidate ref|Workflow Worker + Gitea Actions|对固定 workflow 发起唯一 `workflow_dispatch`，执行 test/security/build/artifact|CI passed / failed|
|ReleasePlanning|CI manifest、commit 和不可变 digest 已验证|Release / Deploy Agent|生成 ReleasePlan 和 SHA-256|请求 deployment approval|
|WaitingDeployApproval|第二道审批已创建|具备 `deployment.decide` 且非 requester 的 Human|审批 Environment、RemoteTarget、CIRun、digest、ReleasePlan 和 request hash|approved / rejected|
|Deploying|deployment approval 已消费且显式推进|Deploy Tool + Controller + Remote Agent|在 Linux staging/demo 执行受控 Compose operation|进入健康验证或失败|
|VerifyingDeployment|远端 operation 完成|Remote Agent + Orchestrator|复核 RepoDigests、服务状态和 `/health`|healthy / unhealthy|
|Monitoring|`MonitoringRegistered`|M8 Monitoring + SRE|接管集中日志、指标、告警和 incident|健康完成或告警|
|Remediating|M8 告警进入|SRE Agent|分析故障、提出 runbook|代码修复或增强版运维审批|
|WaitingOpsApproval|增强版需要运维动作|Human|审批 restart/rollback/清缓存|approved / rejected；非 M7|
|Done|M8 验收和监控闭环完成|Orchestrator|收尾总结|结束|

M7 只覆盖 Linux staging/demo Remote Agent；production、Kubernetes、
RemoteSession、restart 和 rollback 执行均为增强版。M7 健康成功停在
`Monitoring`，不直接进入 `Done`。

## 2. 事件驱动规则

每次状态迁移都应写入：

```json
{
  "event_type": "TaskPhaseChanged",
  "payload": {
    "task_id": "uuid",
    "from": "Testing",
    "to": "Reviewing",
    "reason": "test report passed",
    "actor_type": "orchestrator"
  }
}
```

目标事件 envelope 在 payload 外保存 `sequence/project_id/aggregate_type/
aggregate_id/aggregate_version/schema_version/actor_user_id/actor_device_id/
actor_session_id`；payload 内的 `actor_type` 仅作业务说明，不能替代认证身份。

控制台不应只依赖当前状态字段，而应能通过 timeline 回放关键事件。

## 3. 开发到 PR 流程细化

```text
TaskCreated
  -> RequirementSpecCreated
  -> AcceptanceCriteriaGenerated
  -> TechnicalDesignProposed
  -> DesignApproved
  -> DevelopmentPlanCreated
  -> WorktreePrepared
  -> CodePatchGenerated
  -> TestRunStarted
  -> TestRunPassed
  -> ReviewCompleted
  -> SecurityScanCompleted
  -> BranchCreated
  -> CommitCreated
  -> PullRequestCreated
```

### 失败恢复

|失败点|恢复路径|
|---|---|
|需求不完整|RequirementClarifying 等待用户补充|
|设计被拒绝|回到 Designing，附带用户意见|
|脚手架生成失败|重试或人工接管 sandbox|
|测试失败|回到 Implementing，带测试失败摘要|
|评审不通过|回到 Implementing，带 review comments|
|安全扫描失败|回到 Implementing 或生成风险说明等待用户决策|
|PR 创建失败|重试 Git Tool 或生成本地 PR record|

## 4. PR 到部署流程细化

```text
PullRequestCreated
  -> POST /api/tasks/{task_id}/release-candidate
  -> WorkflowJobQueued(release_candidate_reconcile)
  -> ReleaseCandidateApprovalRequested
  -> ReleaseCandidateApproved
  -> ReleaseCandidatePublished
  -> CIRunTriggered(workflow_dispatch)
  -> CIRunStarted
  -> CIRunPassed
  -> CIArtifactPublished
  -> ReleaseDeployAgentStarted
  -> ReleasePlanCreated
  -> DeploymentApprovalRequested(L3)
  -> DeploymentApprovalApproved
  -> DeploymentRequested
  -> RemoteAgentDeployStarted
  -> ComposePulled
  -> ImageDigestVerified
  -> ComposeUpCompleted
  -> HealthCheckStarted
  -> DeploymentHealthy
  -> MonitoringRegistered
```

Candidate POST 在同一事务创建 Candidate、L2 Approval 与无外部副作用的
`release_candidate_reconcile` WorkflowJob。
`ReleaseCandidateApprovalRequested`/`WorkflowJobQueued` payload 至少保存
candidate id、approval id、reconcile job id、PR record id、binding snapshot hash
和 candidate request hash，但不得保存 clone URL、profile 内容或 credential ref。

WorkflowJob 运行事件固定为：

```text
WorkflowJobQueued
  | WorkflowJobDispatchDeferred
  -> WorkflowJobStarted
     | WorkflowJobSucceeded
     | WorkflowJobFailed
     | WorkflowJobRetryScheduled
     | WorkflowJobExecutionDeferred
     | WorkflowJobCancelRequested
        | WorkflowJobCancelled
        | WorkflowJobSucceeded
        | WorkflowJobFailed
        | WorkflowJobRecoveryRequired
     | WorkflowJobCancelled
     | WorkflowJobRecoveryRequired
```

broker publish 暂时失败只写脱敏的 `WorkflowJobDispatchDeferred`，Candidate 创建
事务仍成功；durable dispatcher 后续补投。worker claim 后若 Task 恰好暂停，
本次尚未开始的 attempt 会撤销并回 pending，写
`WorkflowJobExecutionDeferred(error_code=workflow_job_task_paused)`，不得复用
只表示 broker publish 失败的 `WorkflowJobDispatchDeferred`。

两道审批彼此独立：第一道审批前不发布 candidate ref、不触发 CI；第二道审批前
不产生 Remote Agent 副作用。Gitea workflow 不监听 push，`CIRunTriggered`
只允许来自固定 workflow/ref/inputs 的唯一 `workflow_dispatch`。CI 只生成
test/security/build/artifact，不执行 SSH、Compose 上线、Remote Agent 调用或
服务重启。CI manifest、ReleasePlan 与 Deployment 必须绑定同一精确 commit 和
不可变 OCI index/platform manifest digest。

`MonitoringRegistered` 只表示 M7 已把健康 Deployment、ServiceInstance 和
远端目标交接给 M8；此事件之后 Task 进入 `Monitoring`，不表示监控/SRE 已完成。

### 部署失败处理

|失败点|处理|
|---|---|
|CI 失败|Task 暂停在 CIValidating，保存 run/job/report 和可重试动作；不生成 ReleasePlan|
|镜像拉取失败|DeploymentFailed，提示 registry/凭据/网络|
|digest 复核失败|DeploymentFailed，记录 registry/RepoDigests/平台证据，禁止 up|
|compose up 失败|保留 Remote Agent operation 和受限日志，不开放交互终端|
|健康检查失败|DeploymentUnhealthy，保存 rollback candidate/request；M7 不执行 restart/rollback，M8 再触发 SRE 分析|
|Remote Agent 离线|部署动作等待人工处理；SSH fallback 仅在独立审批后执行固定只读诊断|
|worker hard crash|lease 过期后查询 Gitea run/Remote operation；状态不明则 recovery_required|

## 5. 告警到 Runbook 流程细化

```text
ProjectAlertFired
  -> IncidentCreated
  -> SREAgentStarted
  -> MetricsQueried
  -> LogsSearched
  -> RecentDeploymentsLoaded
  -> IncidentAnalysisGenerated
  -> RunbookProposed
  -> ApprovalRequested(if L3/L4)
  -> RunbookExecuted or FixTaskCreated
  -> RecoveryMonitored
```

### Runbook 分类

|动作|风险|阶段|执行策略|
|---|---|---|---|
|查看受限日志|L0|M7|Remote Agent 按时间/行数/字节上限直读并脱敏|
|查询集中指标|L0|M8|通过 Monitoring Collector 查询|
|收集固定诊断|L0/L1|M7|只执行固定 profile|
|重启 staging 服务|L3|增强版|M7 不执行；后续实现必须独立审批|
|回滚 staging|L3|增强版|M7 只生成 rollback candidate/request；后续执行创建新 Deployment 和独立审批|
|生产回滚|L4|增强版|只生成建议，不自动执行|
|数据库修复|L4|增强版|只生成建议，不自动执行|

## 6. 远程人工接管流程细化（增强版，非 M7）

远程接管保留为增强版受控 session 设计，而不是裸 SSH；M7 不创建
RemoteSession、不开放终端 WebSocket：

```text
TakeoverRequested
  -> PermissionChecked
  -> RemoteSessionCreated
  -> TerminalWebSocketOpened
  -> CommandAuditStarted
  -> UserCommandsRecorded
  -> RemoteSessionClosed
  -> TakeoverSummaryGenerated
```

接管限制：

- 默认进入项目工作目录。
- 禁止直接进入生产数据库。
- 所有命令输入输出写入 audit log 或摘要。
- 接管结束后必须生成 summary。
- 临时修复需要转化为 runbook 或修复 PR。

## 7. Orchestrator 幂等要求

- 每个外部副作用动作必须带 idempotency key。
- 重试工具调用不得重复创建多个 PR 或重复部署同一版本。
- 等待审批的 workflow 恢复时应重新读取 approval 状态。
- M7 rollback request 只保存 candidate/plan；增强版 restart/rollback 执行前
  必须重新检查目标环境、版本并创建独立审批。
## M5 实现同步：Tool Gateway 事件

Tool Gateway API 先在独立短事务中创建 `pending` ToolCall 并原子抢占幂等键，抢占成功后才执行工具；执行结果、审批和终态事件在后续事务中提交。这样数据库事务不会跨越文件、Git 或 Sandbox 外部调用，同时并发请求不会重复执行副作用。事件包括：

|事件|触发条件|关键载荷|
|---|---|---|
|`ToolCallStarted`|收到有效工具调用并通过任务/AgentRun/幂等校验|`tool_call_id`、`tool_name`、`risk_level`|
|`ToolCallSucceeded`|低风险工具执行成功|`summary`、`tool_call_id`、`risk_level`|
|`ToolCallFailed`|参数、策略或执行失败并形成失败 ToolCall|`summary`、`error_code`、`tool_call_id`|
|`ToolCallRejected`|claim 前 subagent 上下文无效，或幂等重放时权限/recipe 指纹漂移|可选 `tool_call_id`、`agent_run_id`、`tool_name`、`error_code`、`rejection_stage`、参数/幂等键哈希和策略指纹；不保存原始参数/原因|
|`ApprovalRequested`|L3/L4 或工具声明要求审批|`approval_id`、`tool_call_id`、`tool_name`、`risk_level`|

M5 不实现审批通过后的自动恢复执行；M7 计划为 deployment approval 补充单次
消费，并由服务端 durable WorkflowJob 自动恢复。`run-next` 只用于调试/人工恢复，
Approval API 事务本身仍不直接执行远端副作用。

控制台 `EventSource` 监听列表和 `packages/shared-contracts/schemas/events/task-event.schema.json`
必须覆盖上述 M2-M5 已实现事件，不能只监听 M2 初始事件而漏掉 Agent、
DevelopmentPlan 或 ToolCall 状态变化。
