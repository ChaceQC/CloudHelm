# 01 领域模型与 Agent 协作

> 文档版本：v4.3.0
> 对齐总体设计：v4.3
> 修订日期：2026-10-07
> 状态：设计基线，待实现及专项验证。

[返回文档索引](README.md)。执行恢复遵循 [D02](02-execution-recovery.md)，费用预留遵循 [D03](03-workspace-build-resources.md)。

## 1. 状态所有权与事务边界

初期采用模块化单体，各领域与 DBOS 系统表位于同一 PostgreSQL 数据库的不同 schema，但只能通过所属领域服务修改其权威状态。DBOS 负责队列、检查点、持久等待和重放，不自行解释验收或部署业务规则；API 与 Agent 工具都调用相同的领域命令处理器。

|负责模块|权威对象与规则|其他模块可以做什么|
|---|---|---|
|identity|User、DeviceSession、RoleBinding、Policy、Approval|查询当前授权，提交审批请求；不得代替人类批准|
|projects/collaboration|Project、Task、WorkItem、Decision、ContractRevision、消息与依赖|提交带版本的分配、交付、变更和完成命令|
|agent-runtime|AgentMember、AgentSession、AgentRun、ContextPackage、ModelRequestRecord|调度请求、读取执行结果；不凭模型输出修改部署状态|
|workspaces/integration|Workspace、IntegrationAttempt、MergeQueueEntry、VerificationReport、Review|提交候选和证据，获取精确版本结果|
|execution|Operation、ExecutionAttempt、StepExecution、ResourceReservation|创建授权操作，查询事实，申请取消或核对|
|delivery|ReleaseCandidate、BuildRun、Release、DeploymentPlan、Deployment、EnvironmentRevision|消费构建和执行证据，决定发布或部署状态转换|
|operations|ObservedState、DriftRecord、Incident|报告观测、提出处置；变更期望状态须调用 delivery|
|workflow|WorkflowBinding、DBOS 接入及工作流定义；队列/检查点归 DBOS|按业务身份提交、查询、唤醒；不复制 DBOS 调度表和状态机|
|sync|Outbox、EventLog、DispatchEvent、游标|分发和重放业务事件，不产生独立业务结论|

BuildRun 保存构建业务结果，实际进程和步骤记录归 execution；AgentRun 保存推理尝试结果，工具副作用归 Operation。一个状态不能同时由这两侧任意写入。

同一领域命令在一个短事务内校验 expected_version、写入状态、业务事件及需要分发的 Outbox；若需启动工作流，在该事务中通过 DBOSClient 的事务入队接口写入 DBOS 系统表及 WorkflowBinding。DBOS 系统表只能由支持的 SDK 接口和迁移流程操作。跨领域长过程通过持久结果交接，接收方按事件 ID 去重并校验资源版本。等待网络、模型、Git 或容器时不得保持数据库事务与行锁。具体身份及事务规则归 D02。

工作流步骤重试调用领域命令时，使用稳定 command_id、输入摘要及领域去重记录；业务事务已提交而 DBOS 检查点未落盘时，返回既有命令结果，不能再次推进业务版本。DBOS 的执行状态通过适配层查询，UI 的业务阶段仍由所属领域与证据投影。

禁止通过“把所有状态改成失败”处理一次超时。调度租约到期、物理执行未知、业务需要核对分别记录。界面可汇总，但可展开查看各自原因。

## 2. 业务对象与状态

|对象|生命周期及转换依据|
|---|---|
|Task|draft、active、paused、waiting_input、completed、failed、cancelled；planning/implementing/integrating/verifying/reviewing 作为基于工作项与证据的展示阶段|
|WorkItem|pending、ready、running、blocked、submitted、accepted、failed、cancelled；只检查本工作项声明的依赖|
|AgentSession|idle、queued、running、waiting、paused、completed、failed；运行结果另存 AgentRun|
|AgentRun|queued、running、waiting_tool、succeeded、failed、interrupted；失联恢复不覆盖原尝试|
|ReleaseCandidate|created、policy_check、pending_approval（策略要求时）、building、verified、failed|
|Deployment|planned、pending_approval、queued、preflight、applying、verifying、needs_reconciliation、succeeded、failed、partially_applied、cancelled；细节归 D04|
|Incident|open、investigating、action_pending、mitigating、resolved、closed|

Task 生命周期与展示阶段分开：多个工作项并行时，阶段可同时标示实现和验证；阶段展示不阻止符合依赖的工作继续。paused 停止新调度，已有操作如何停止由 D02 确认，不能把它们直接标为已取消。

主要转换条件如下：

|命令|前置条件|结果|
|---|---|---|
|start_task|目标、验收版本和授权存在，预算允许|Task active，登记初始工作项|
|claim_work_item|依赖有效、未暂停、无其他有效分配、资源可用|条件更新为 running，创建执行引用|
|submit_result|提交来自当前有效尝试，产物存在，输入版本明确|保存不可变交付记录，WorkItem submitted|
|accept_result|验收条件满足，证据与输入仍有效|WorkItem accepted；派生交付事件|
|request_rework|结果失败或输入失效，返工范围明确|保存旧结果，新修订或新工作项重新排队|
|complete_task|必需工作项及验收完成，项目最终合入版本有有效证据|冻结完成报告及提交；不要求 Release 已部署|
|change_requirements|用户授权、预期 Task 版本匹配|新增需求修订，计算影响并阻止失效结果被继续采用|

结果的历史完成状态和当前适用性分开。已 accepted 的历史交付不会被擦除，但输入变化后其有效性标为 needs_review 或 superseded。已 completed Task 的新功能或故障修复创建关联 Task，不改写原完成结论。

## 3. 工作项与分类依赖

WorkItem 至少具有 task_id、revision、目标、owner_session、基础 commit、需求/验收修订、可修改范围、输入引用、交付要求、依赖、预算及截止条件。共享目录的调度范围不替代执行器路径授权。

本基线采用显式拆分工作项表达不同阶段，不增加隐藏的“部分依赖满足即可执行”逻辑。例如分别创建接口契约、前端实现、后端实现、集成验证工作项。前后端实现只依赖已确认契约；集成验证依赖双方产物及测试环境。

|依赖类型|必需引用|满足证据|
|---|---|---|
|contract|contract_id、revision、兼容性要求|正式生效的契约修订|
|artifact|producer、精确产物版本、要求的交付质量|已登记且达到质量条件的产物；不能隐含要求整个 producer Task 完成|
|integration|候选提交及集成输入集合|输入齐备且版本明确|
|environment|环境身份、规格、有效期|当前就绪观测及未过期的环境租约|

每条依赖保存消费者、生产者或外部资源、失效规则和证据。ready 表示该工作项全部声明依赖满足且当前有效。资源不足使用 blocked/waiting_resource，回复等待使用 blocked/waiting_reply，原因单独存储。

新增或修改依赖在任务图版本条件更新下执行，检查环与重复分配。契约修订时，以显式消费者引用计算影响；无法证明兼容的变化按需复核。模型的“兼容”判断可以提供建议，但不能独自清除受影响标记。

## 4. 团队调度与收敛

AgentMember 定义项目内的角色能力、模型配置和工具上限；AgentSession 为成员在一个 Task 中的独立会话；AgentRun 为一次获准的推理及工具循环。不同任务的会话默认隔离。

同一 Session 同时最多一个有效 Run，通过唯一约束和带代次的条件更新实现。DBOS 工作流恢复不自动创建新 AgentRun；沿用当前业务执行引用，只有领域规则批准新的推理尝试才创建 Run。过期 Run 即使仍在接收模型输出，也无权提交新工具副作用和业务结果。其已启动工具必须按 D02 核对，不能因模型尝试结束而丢弃。

协调 Agent 提出分配、依赖变化、拆分和返工建议，由领域服务应用。独立验证读取权威验收和实际代码，审查角色对候选只读。发布与运维角色解释风险或提出方案，确定性执行器完成获批变更。

团队规模依据独立可执行工作、沟通成本和资源预算决定。不得仅因角色列表中存在某角色就创建常驻会话。连续返工、循环等待或通信无新增证据时升级为明确待决问题；预算与无进展阈值须可配置并记录触发依据。

## 5. 消息、收件箱与等待

Message 正文不可变，记录 message_id、发送身份、接收范围、task_id、conversation_id、correlation_id、created_at 和结构化工程引用。支持 question/answer、change_proposal、blocker/unblock、review_feedback、handoff、decision_notice。

每个接收 Session 独立保存 InboxDelivery，按 message_id + recipient_session 唯一。queued、delivered、processed 分开；processed 表示已提交处理结果，不表示同意或完成消息要求。

业务命令结果与消息处理确认在可覆盖的同一数据库事务提交；外部副作用先登记 Operation，再以 Operation 引用确认处理。不得在标记 processed 后才无记录地启动外部命令。重投使用消息 ID 去重，派生业务操作使用自己的稳定幂等键。

WaitCondition 保存等待对象、correlation_id、所需结果、截止时间、升级规则及目标 WorkflowBinding。登记等待与检查已到达回复在同一事务完成，避免回复先到而永久睡眠；其业务判定保留，休眠和唤醒机制交给 DBOS。

Message、InboxDelivery 和唤醒 Outbox 在同一业务事务登记；分发器用稳定 event_id、目标 workflow_id 和 topic 发送 DBOS 持久消息，使用所选 SDK 支持的幂等发送接口。消息载荷只包含工程引用。若消息发送完成但分发确认丢失，可重复发送，消费者仍以业务消息 ID 去重；DBOS 接收不直接把 InboxDelivery 标为 processed。

等待工作流先检查权威收件箱，再通过 DBOS 持久接收等待通知，收到通知后重新读取业务条件；持久超时用于有界补偿检查，通知不是批准或依赖成立的证据。目标流程已结束时，由领域服务决定归档消息或创建获准的后续工作，不能重启已完成任务。等待保留在编排队列，释放模型调用与重执行容量；DBOS 等待本身可能仍占编排并发名额，队列容量按 D03 规划。

运行中在模型回合或工具安全边界读取新消息。普通消息可使用最多约 1～2 秒的初始批量窗口，具体值待实测；关键阻塞回复、权限撤销、取消和破坏性契约变化优先处理。暂停任务只累计消息。

等待关系也要检测循环，不能仅检测任务图的静态依赖环。超时与无回复不等于同意。通信范围不得超过接收者的项目和资源权限。

## 6. 启动上下文与实际请求

|记录|粒度|不可变内容|
|---|---|---|
|ContextPackage|每个 AgentRun 启动时一份|工作项/需求/验收修订、基线 commit、契约与决策引用、未决问题、起始消息边界、工具和权限/预算快照|
|ConversationEpoch|一个 Session 的一段上下文代次|模型配置、前缀、项目基线、工具包、冻结摘要及切换原因|
|ModelRequestRecord|每次实际模型请求一份|run_id、epoch_id、request_sequence、实际输入引用/摘要、历史边界、增量 ID、有效规则修订、提供方请求 ID及 usage|
|交付记录|每次工程交付一份|ContextPackage、产生交付的模型请求/操作、代码与产物、最终验证所用的有效输入版本|

一个 Run 对应多个 ModelRequestRecord。ContextPackage 不保存可变的“最新请求 ID”，不更新为后续输入快照。请求前先持久登记请求记录，响应和费用以关联结果记录追加；不要覆写已发送的请求表示。

模型调用位于 DBOS step 或专用模型子工作流中，工作流编排逻辑只消费已记录结果。每次真实请求具有稳定的 request_record_id；DBOS 重放命中已有检查点时不计为新请求。若提供方已响应但本地检查点未保存，先按请求记录核对；无法确认时保留未知 usage，按 D03 预算及重试规则决定是否创建新的真实请求，不能自动重复整段 Agent 循环。ConversationEpoch、AgentRun 和 DBOS application_version 分别管理，彼此不能替代。

权限与费用快照仅用于解释，Gateway 和预算服务检查当前值。输入组装前过滤敏感内容，验证当前有效约束是否已经送达。变更发生于请求期间时，结果标记需复核；不能将通知已投递当作代码已符合新约束。

权威需求、验收和契约保留原文引用；过程记录按需检索；摘要保存覆盖范围和来源。摘要缺失关键约束或来源不可访问时，停止声称可安全恢复，重新构造所需输入。

## 7. 缓存与会话协议

稳定内容依次包含平台协议、公共项目基线、角色与初始任务；历史与新消息按提供方格式追加。时间、剩余预算、队列位置和工作区瞬时状态放入必要的增量，不污染稳定前缀。

同一 Epoch 固定模型配置、模板和 ToolBundleRevision。规范化只作用于尚未发送的内容，已发送历史保留原表示。工具排序、schema 和模板采用确定性组装；实时授权仍由 Gateway 执行。

维护 committed history 和 pending delta。流中断不得把半截输出当作完整消息反复追加；保存 provider 要求的 tool-call ID 和协议返回项。工具副作用按 Operation 查询，不以新的模型 tool-call ID 推断可以重新执行同一业务动作。

契约补丁明确被替代的版本及作用范围。硬约束不能仅用低优先级尾部文本覆盖更高优先级旧规则；组装器应选择协议允许的权威指令表示，必要时切换 Epoch。撤权需要隐藏工具或移除敏感上下文时立即切换，不为缓存保留访问能力。

压缩依据上下文窗口、费用和无关历史触发，生成冻结摘要并开启新 Epoch。原样保留当前验收、有效约束、关键证据和未决问题引用。压缩本身的请求和缓存损失计入成本。

提供方能力配置记录核验日期、适用模型、自动/显式缓存、最小长度、期限、usage 映射和价格语义。显式缓存资源按权限范围管理；失效可回退完整请求，访问撤销后的外部物理删除能力必须如实描述。

usage 缺失记 unknown，不能记零。只有 total_input 包含 cached_input 的已核验语义才直接计算聚合命中率，同时报告统计覆盖率。跨模型、账号、租户或提供方不假定缓存共享，不为保温发送无意义请求。

## 8. 接口与验证边界

对外保留项目、任务、工作项、会话、消息、决策、上下文及报告资源；命令支持幂等键与 expected_version。协调工具走同一领域授权，不暴露直接更新状态表的能力。

本专题定义字段语义及转换条件，完整 OpenAPI、数据库约束与消息 schema 在 P0/P1 实现交付中生成并校验。领域与协作验收覆盖并发调度、依赖解锁、收信、上下文追溯和恢复行为，验收要求见 D06。
