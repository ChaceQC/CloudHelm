# 核心实体模型

> 来源：[设计书 11.1](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：说明平台核心实体及其业务含义。
## 建模原则

- Task 是一次用户目标或自动触发任务的主线。
- RequirementSpec、TechnicalDesign、AgentRun、ToolCall、ApprovalRequest、EventLog 共同描述开发闭环。
- Environment、RemoteTarget、Deployment、ServiceInstance、ProjectAlert、Incident、RemoteSession 描述远端业务项目运行与运维闭环。

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
|Environment|远端业务项目环境，例如 staging、demo、production|
|RemoteTarget|远端部署目标，例如云服务器、Linux 主机、K8s namespace|
|Deployment|业务项目一次远端部署记录|
|ServiceInstance|远端业务服务实例，例如 API、Worker、Frontend|
|ProjectMetric|远端业务项目指标快照或指标引用|
|ProjectAlert|远端业务项目告警|
|Incident|远端业务项目故障事件|
|RemoteSession|远程终端 / 远程接管会话|
