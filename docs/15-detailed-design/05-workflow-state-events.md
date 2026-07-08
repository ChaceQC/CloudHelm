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
```

## M4 事件落地状态

M4 新增以下真实事件：

```text
TaskPhaseChanged
AgentRunStarted
AgentRunCompleted
AgentRunFailed
DevelopmentPlanCreated
```

Requirement Agent 成功后写 `RequirementSpecCreated` 并进入 `Designing`；Architect Agent 成功后写 `TechnicalDesignCreated`，低风险进入 `Planning`，L2 及以上写 `ApprovalRequested` 并进入 `WaitingDesignApproval`；Planner Agent 成功后写 `DevelopmentPlanCreated`，并创建 `approve_development_plan` 审批请求。M4 不写代码、不执行工具、不部署远端环境。

Timeline API 从 `event_logs` 按时间升序读取；SSE 端点输出当前已有事件并
追加 heartbeat。M2 不做长连接实时推送，不使用内存事件队列模拟生产事件流。

## 1. 状态机总表

|状态|进入条件|执行者|主要动作|退出条件|
|---|---|---|---|---|
|Created|TaskCreated|Platform API|持久化任务，广播事件|auto_start 或用户启动|
|RequirementClarifying|任务开始|Requirement Agent|解析需求、生成验收标准|需求完整或需要用户澄清|
|Designing|需求通过|Architect Agent|生成 ADR、OpenAPI、DB schema|低风险自动通过或进入设计审批|
|WaitingDesignApproval|设计高风险或用户要求|Human|审批、拒绝、补充约束|approved / rejected|
|Planning|设计通过|Planner Agent|拆分任务图和风险|计划生成|
|Scaffolding|新项目/新模块|Scaffold Agent|生成骨架、配置、基础测试|骨架完成|
|Implementing|已有项目或脚手架完成|Coder Agent|修改代码、补测试|实现完成或失败|
|Testing|实现完成|Tester Agent|运行单元/集成/E2E 测试|测试通过或失败|
|Reviewing|测试通过|Reviewer Agent|需求符合度和代码审查|通过或要求修改|
|SecurityScanning|评审通过|Security Agent|Semgrep/Trivy/依赖扫描|通过或失败|
|PullRequestCreated|扫描通过|Git Tool|commit、push、create PR|PR 创建|
|WaitingMergeApproval|PR 创建|Human|审查 PR、审批合并/部署|approved / rejected|
|Deploying|合并审批通过|Release / Deploy Agent|读取 CI 制品、请求审批、调用 Deploy Tool 执行远端部署|健康或失败|
|Monitoring|部署健康|Monitoring + SRE|采集状态、日志、指标|健康完成或告警|
|Remediating|告警进入|SRE Agent|分析故障、提出 runbook|代码修复或运维审批|
|WaitingOpsApproval|需要运维动作|Human|审批重启/回滚/清缓存|approved / rejected|
|Done|验收通过且远端健康|Orchestrator|收尾总结|结束|

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
MergeApproved
  -> ReleaseDeployAgentStarted
  -> CITriggered
  -> CIBuildStarted
  -> CIBuildPassed
  -> ArtifactPublished
  -> DeploymentRequestedByAgent
  -> ApprovalRequested(L3)
  -> ApprovalApproved
  -> RemoteAgentDeployStarted
  -> ComposePulled
  -> ComposeUpCompleted
  -> HealthCheckStarted
  -> DeploymentHealthy
  -> MonitoringRegistered
```

### 部署失败处理

|失败点|处理|
|---|---|
|CI 失败|创建 ci_failure_fix 任务|
|镜像拉取失败|DeploymentFailed，提示 registry/凭据/网络|
|compose up 失败|保留远端日志，允许人工接管|
|健康检查失败|DeploymentUnhealthy，触发 SRE Agent 分析|
|Remote Agent 离线|Release / Deploy Agent 切换 SSH fallback 只读诊断，部署动作等待人工处理|

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

|动作|风险|MVP 执行策略|
|---|---|---|
|查看日志|L0|自动执行|
|查询指标|L0|自动执行|
|收集诊断|L0/L1|自动执行|
|重启 staging 服务|L3|审批后执行|
|回滚 staging|L3|审批后执行|
|生产回滚|L4|只生成建议，不自动执行|
|数据库修复|L4|只生成建议，不自动执行|

## 6. 远程人工接管流程细化

远程接管应是受控 session，而不是裸 SSH：

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
- 服务重启、回滚等动作执行前再次检查目标环境和版本。
## M5 实现同步：Tool Gateway 事件

Tool Gateway API 在同一数据库事务中写入以下事件：

|事件|触发条件|关键载荷|
|---|---|---|
|`ToolCallStarted`|收到有效工具调用并通过任务/AgentRun/幂等校验|`tool_call_id`、`tool_name`、`risk_level`|
|`ToolCallSucceeded`|低风险工具执行成功|`summary`、`tool_call_id`、`risk_level`|
|`ToolCallFailed`|参数、策略或执行失败并形成失败 ToolCall|`summary`、`error_code`、`tool_call_id`|
|`ApprovalRequested`|L3/L4 或工具声明要求审批|`approval_id`、`tool_call_id`、`tool_name`、`risk_level`|

M5 不实现审批通过后的自动恢复执行；审批决策仍由 Approval API 记录，后续里程碑再补高风险动作恢复语义。
