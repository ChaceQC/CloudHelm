# 核心实体模型

> 来源：[设计书 11.1](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：说明平台核心实体及其业务含义。
## 建模原则

- Task 是一次用户目标或自动触发任务的主线。
- RequirementSpec、TechnicalDesign、DevelopmentPlan、AgentConversation、
  AgentRun、ToolCall、Artifact、PullRequestRecord、ApprovalRequest、EventLog
  共同描述当前 M6 开发闭环。
- ProjectRepositoryBinding、ReleaseCandidate、CIRun、WorkflowJob、Environment、
  RemoteTarget、Deployment、ServiceInstance 共同描述 M7 的 CI 与远端
  staging/demo 部署闭环。
- M7 的 RemoteTarget 固定为运行 Remote Agent 的 Linux 主机；production、
  Kubernetes target、RemoteSession、ProjectMetric、ProjectAlert 和 Incident
  保留为 M8 或增强版实体，不计入 M7 完成范围。

## 设计书摘录

### 11.1 核心实体

|实体|说明|
|---|---|
|Project|接入的平台项目或仓库|
|Task|一次用户目标或自动触发任务|
|RequirementSpec|开发者目标、功能需求、约束和验收标准|
|TechnicalDesign|Agent 生成的技术方案、ADR、API 设计和数据库设计|
|AcceptanceCriteria|可执行或可检查的验收标准|
|TaskStep|任务拆解后的步骤|
|AgentRun|某个 Agent 的一次运行|
|ToolCall|一次工具调用|
|ApprovalRequest|审批请求|
|EventLog|事件溯源记录|
|Artifact|产物，例如 patch、测试报告、扫描报告|
|SandboxSession|沙箱会话|
|PullRequestRecord|PR 记录|
|PolicyDecision|权限策略判断结果|
|ProjectRepositoryBinding|Project 与受控 Gitea repository/profile、固定 workflow 和 credential 引用的绑定|
|ReleaseCandidate|M6 PullRequestRecord 的精确 commit、受控 candidate ref 和第一道审批记录|
|CIRun|由唯一 `workflow_dispatch` 触发的真实 CI run/job、commit 与不可变制品身份|
|WorkflowJob|PostgreSQL 中保存 claim、lease、heartbeat、retry 和恢复状态的异步业务任务|
|Environment|M7 远端业务项目环境，只允许 staging、demo；production 属于增强版|
|RemoteTarget|M7 运行 Remote Agent 的 Linux 目标，保存 agent endpoint、credential 引用、TLS 指纹、capabilities 和心跳；Kubernetes target 属于增强版|
|RemoteAgentCredential|M7-1 machine credential 元数据，保存 key/scope/lifecycle、secret ref 和 fingerprint，不保存 secret|
|RemoteAgentReplayNonce|M7-1 已认证 nonce hash，用数据库唯一约束防止顺序/并发 replay|
|Deployment|业务项目一次远端部署记录，绑定第二道审批、ReleasePlan、CI digest 和远端 operation|
|ServiceInstance|远端业务服务实例，例如 API、Worker、Frontend|
|ProjectMetric|M8 远端业务项目指标快照或指标引用|
|ProjectAlert|M8 远端业务项目告警|
|Incident|M8 远端业务项目故障事件|
|RemoteSession|增强版远程终端 / 远程接管会话，M7 不创建|
