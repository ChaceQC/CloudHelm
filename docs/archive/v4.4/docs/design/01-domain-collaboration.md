# 01 领域模型与 Agent 协作

> 文档版本：v4.4.0
> 对齐总体设计：v4.4
> 修订日期：2026-10-07
> 状态：设计基线，待实现及专项验证。

[返回文档索引](README.md)。执行恢复遵循 [D02](02-execution-recovery.md)，费用预留遵循 [D03](03-workspace-build-resources.md)。

## 1. 状态所有权与事务边界

初期采用模块化单体，各领域与 DBOS 系统表位于同一 PostgreSQL 数据库的不同 schema，但只能通过所属领域服务修改其权威状态。DBOS 负责队列、检查点、持久等待和重放，不自行解释验收或部署业务规则；API 与 Agent 工具都调用相同的领域命令处理器。

|负责模块|权威对象与规则|其他模块可以做什么|
|---|---|---|
|identity|User、DeviceSession、RoleBinding、Policy、Approval|查询当前授权，提交审批请求；不得代替人类批准|
|projects/collaboration|Project、Task、WorkItem、Decision、ContractRevision、Message、WaitCondition、DependencyLink|提交带版本的分配、交付、变更和完成命令|
|agent-runtime|AgentMember、AgentSession、AgentRun、ContextPackage、ModelRequestRecord|调度请求、读取执行结果；不凭模型输出修改部署状态|
|workspaces/integration|Workspace、IntegrationAttempt、MergeQueueEntry、VerificationReport、Review、相应 EvidenceRecord|提交候选和证据，获取精确版本结果|
|execution|Operation、ExecutionAttempt、ResourceReservation、StepExecution 索引|创建授权操作，查询执行器权威步骤账本，申请取消或核对|
|delivery|ReleaseCandidate、BuildRun、Release、DeploymentPlan、Deployment、EnvironmentRevision|消费构建和执行证据，决定发布或部署状态转换|
|operations|ObservedState、DriftRecord、Incident|报告观测、提出处置；变更期望状态须调用 delivery|
|workflow|WorkflowBinding、DBOS 接入与恢复门禁；队列/检查点归 DBOS|按业务身份提交和查询；业务工作流由所属领域定义|
|sync|Outbox、EventLog、DispatchEvent、游标|分发和重放业务事件，不产生独立业务结论|

BuildRun 保存构建业务结果，物理进程与步骤事实由执行器账本产生，execution 保存索引和回报投影；AgentRun 保存一次有界推进，外部副作用归 Operation。Runtime 自身的工具调用不能直接写入部署状态。每类 EvidenceRecord 由产生证据的领域写入，消费者领域应用适用性规则；共享引用结构不成为另一套业务状态所有者。

同一领域命令在一个短事务内校验 expected_version、写入状态、业务事件及需要分发的 Outbox；若需启动工作流，在该事务中通过 DBOSClient 的事务入队接口写入 DBOS 系统表及 WorkflowBinding。DBOS 系统表只能由支持的 SDK 接口和迁移流程操作。跨领域长过程通过持久结果交接，接收方按事件 ID 去重并校验资源版本。等待网络、模型、Git 或容器时不得保持数据库事务与行锁。具体身份及事务规则归 D02。

工作流步骤重试调用领域命令时，使用稳定 command_id、输入摘要及领域去重记录；业务事务已提交而 DBOS 检查点未落盘时，返回既有命令结果，不能再次推进业务版本。DBOS 的执行状态通过适配层查询，UI 的业务阶段仍由所属领域与证据投影。

禁止通过“把所有状态改成失败”处理一次超时。调度租约到期、物理执行未知、业务需要核对分别记录。界面可汇总，但可展开查看各自原因。

## 2. 业务对象与状态

|对象|生命周期及转换依据|
|---|---|
|Task|draft、active、paused、waiting_input、completed、failed、cancelled；planning/implementing/integrating/verifying/reviewing 作为基于工作项与证据的展示阶段|
|WorkItem|pending、ready、running、blocked、submitted、accepted、failed、cancelled；只检查本工作项声明的依赖|
|AgentSession|idle、queued、running、waiting、paused、completed、failed；运行结果另存 AgentRun|
|AgentRun|queued、running、succeeded、failed、interrupted；succeeded 表示本次推进已提交，其 outcome 为 tool_requests、waiting_condition、submitted 或 continue_required，不表示 Task 完成|
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

AgentMember 定义项目内的角色能力、模型配置和工具上限；AgentSession 为成员在一个 Task 中的长期独立会话；AgentRun 为一次获准的有界推进。不同任务的会话默认隔离。协调、开发、验证、审查角色共用 PydanticAI 与同一 Runtime，通过角色策略、上下文和工具能力区分。

同一 Session 同时最多一个 queued/running 的有效 Run，通过唯一约束、session_version 和执行代次的条件更新实现。一个 Run 对应一次有界 DBOS 工作流，崩溃重放沿用原 Run；外部工具/人工/依赖等待结束后续接时创建新 Run，沿用 Session 和合法的消息历史。框架 run_id 单独记录，不能当作 CloudHelm Run 或 Operation 身份。

Run 遇到外部工具请求、人工/依赖等待、交付结果或推进预算边界时提交结果后结束。长工具仍执行时，Session/WorkItem 保存等待原因，Operation 独立推进。达到预算边界可登记 continue_required，由当前授权及预算决定是否入队下一 Run，不把不完整模型响应伪装成完成消息。过期 Run 无权提交新工具副作用和业务结果；已启动操作仍按 D02 核对。

协调 Agent 提出分配、依赖变化、拆分和返工建议，由领域服务应用。独立验证读取权威验收和实际代码，审查角色对候选只读。发布与运维角色解释风险或提出方案，确定性执行器完成获批变更。

团队规模依据独立可执行工作、沟通成本和资源预算决定。不得仅因角色列表中存在某角色就创建常驻会话。连续返工、循环等待或通信无新增证据时升级为明确待决问题；预算与无进展阈值须可配置并记录触发依据。

## 5. 消息、收件箱与等待

Message 正文不可变，保存 message_id、发送身份、接收范围、task_id、conversation_id、correlation_id、时间及结构化工程引用。类型包括 question/answer、change_proposal、blocker/unblock、review_feedback、handoff、decision_notice；消息不是批准或依赖成立的证据。

每个接收 Session 保存 InboxDelivery，按 message_id + recipient_session 唯一；queued、delivered、processed 分开。业务处理结果与 processed 在可覆盖的同一事务提交；外部副作用先形成 Operation 引用，processed 不表示该操作完成。

WaitCondition 归业务层，保存 wait_id、owner_session/work_item、condition_revision、关联回复/Operation/依赖引用、必要结果、期限、升级规则与 resolved/closed 状态。等待不绑定一个必须长期存活的 DBOS workflow_id，通知寻址稳定 Session/业务对象。

### 5.1 可靠交接与续接

1. Run 通过稳定命令身份，在一个短事务保存完整消息历史边界、待执行工具请求、必要 Operation、WaitCondition 和自身终态，并释放 Session 的有效 Run 引用。
2. 登记等待时检查已到达的回复和已完成结果；若条件已满足，同事务登记唯一推进请求并使用 D02 事务入队。外部操作执行也从该事务可靠交接，不能先执行再补记录。
3. 新消息、工具结果、批准或依赖变化事务更新权威业务记录，重新计算有关条件；条件满足且 Session 可运行时，创建唯一推进请求、新 Run 和 WorkflowBinding，并事务入队。跨事务/外部交接使用 Outbox 和稳定 event_id。
4. 推进请求按 session_id + continuation_revision 唯一。Session 已有有效 Run 时只合并待处理标记，不再创建第二个 Run；Run 在模型或工具安全边界读取消息，并在结束事务再次检查待处理条件。
5. 新 Run 加载 committed history 和匹配原 tool-call ID 的已确认结果，重新检查权限、Task 状态、依赖及预算。重复通知返回既有推进结果，不能重复分配工具副作用。
6. 超时由 DBOS 定时能力触发有界条件检查；回调按 wait_id + condition_revision 去重，已解决/被替代的等待不再生效。补偿检查只修复漏推进，不维护第二套领取、租约或重试调度器。

PydanticAI 的 DeferredToolRequests/DeferredToolResults 用于表示外部工具请求与续接结果；工具批次必须在所选版本支持的完整/部分结果策略下续接，P0 固定具体规则。初始策略等待本批次每项具有确定结果；unknown 操作保持等待核对，不能伪造失败让模型重做。普通业务消息可累计，撤权、暂停、取消和破坏性变更优先进入控制处理。

长期人工/依赖等待不保留活跃 AgentRun 或常驻编排工作流。必要的 DBOS 定时等待有独立有界维护容量，不占模型或重执行槽；定时与记录保留仍纳入容量预算。短流程内部的受限等待可以使用 DBOS 原语，不能据此重新创建每个 Task 一个常驻流程。

暂停只积累消息和结果；恢复事务检查可运行条件并可靠入队。目标 Task 已结束时，由领域命令决定归档或关联新 Task，不能凭消息自动重开。动态等待关系和静态依赖图都检查循环；超时不等于同意。

## 6. 启动上下文与实际请求

|记录|粒度|不可变内容|
|---|---|---|
|ContextPackage|每个 AgentRun 启动时一份|InputSet、工作项/需求/验收修订、基线 commit、契约与决策引用、未决问题、起始消息边界、工具和权限/预算快照|
|ConversationEpoch|一个 Session 的一段上下文代次|模型配置、前缀、项目基线、工具包、冻结摘要及切换原因|
|ModelRequestRecord|每次实际模型请求一份|run_id、epoch_id、request_sequence、实际输入引用/摘要、历史边界、增量 ID、有效规则修订、提供方请求 ID及 usage|
|交付记录|每次工程交付一份|ContextPackage、产生交付的模型请求/操作、代码与产物、最终验证所用的有效输入版本|

一个 Run 对应多个 ModelRequestRecord。ContextPackage 不保存可变的“最新请求 ID”，不更新为后续输入快照。请求前先持久登记请求记录，响应和费用以关联结果记录追加；不要覆写已发送的请求表示。

模型调用使用 PydanticAI 与 DBOS 接缝中的模型步骤或受限模型子工作流，工作流编排逻辑只消费已记录结果。每次真实请求具有稳定的 request_record_id；DBOS 重放命中已有检查点时不计为新请求。若提供方已响应但本地检查点未保存，先按请求记录核对；无法确认时保留未知 usage，按 D03 预算及重试规则决定是否创建新的真实请求，不能自动重复整段 Agent 循环。ConversationEpoch、AgentRun 和 DBOS application_version 分别管理，彼此不能替代。

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

## 8. Agent Runtime 接口与复用边界

选定 PydanticAI 作为 Agent 协议运行时，复用其消息、工具 schema、结构化输出、流式事件和外部工具续接能力；DBOS 是唯一持久执行底座。首选官方 DBOS 接入能力，并在 P0 验证预算拦截、实时门禁、序列化和版本兼容，不能把接入选项存在等同于已满足平台规则。

|层|承担职责|输出边界|
|---|---|---|
|PydanticAI|模型消息、工具参数校验、结构化输出、流式协议|模型结果与已校验的工具请求|
|CloudHelm Runtime|上下文组装、角色策略、消息注入、请求记录、有界推进|持久历史、TurnResult、输入与请求引用|
|collaboration|分配、依赖、正式决策、验收与返工|幂等领域命令和业务事件|
|Tool Gateway|当前权限、路径、参数、限额、预算和路由|受限查询、领域命令或 Operation|
|DBOS|工作流、检查点、队列、可靠交接与定时|技术执行记录与恢复|
|Runner / Remote Agent|受限物理执行及账本|带身份、步骤、代次的事实回报|

Runtime 的逻辑入口 advance_session 接受 session_id、run_id、expected_session_version、ContextPackage/InputSet 引用、已提交历史边界、待处理消息和 DeferredToolResults 引用。不得在工作流参数中传入实际密钥或完整仓库；凭据在获准模型请求步骤内按引用解析。

TurnResult 固定 run_id、outcome、完整历史增量引用、实际请求集合、待执行工具请求/等待条件/交付结果及原因。outcome 分为 tool_requests、waiting_condition、submitted、continue_required；错误和中断以 Run 终态及可恢复历史边界记录。其落盘与后续推进按第 5 节事务交接。

外部副作用工具和长任务使用 ExternalToolset 或等价的延迟工具接口，将执行交给 Gateway/Operation；纯查询走受限查询步骤，协作变更走幂等领域命令。PydanticAI 的工具批准表示只承载交互，不构成 CloudHelm 人类审批记录。模型不得通过框架本地 workspace、shell 或 MCP 直连绕过 Gateway。

每次实际模型请求均先登记 ModelRequestRecord 和费用预留，再发送；校验修复、重试、压缩也遵守此入口。P0 必须验证官方接入能在真实请求前执行当前门禁、只对新请求计费、保存可恢复协议历史，并限制 SDK 内部重试。如果不能满足，记录接缝缺口并修订适配方案，不能默默引入第二套检查点或副作用重试链。

编排并发、模型请求并发和物理占用分别管理；框架自动并行工具只产生请求集合，不直接获得并行执行权限。Run 按最大模型请求数、总时长和费用设有界推进政策，具体值在 P0/P2 测量后固定。

本次设计参考了 PydanticAI 的 [Agent 逐节点推进](https://ai.pydantic.dev/agents/)、[外部工具与延迟结果](https://ai.pydantic.dev/deferred-tools/)和 [DBOS 集成](https://ai.pydantic.dev/durable_execution/dbos/)。所查文档推荐 DBOSDurability 接入，新代码不使用已弃用的 DBOSAgent 包装路径；接口名及弃用状态随 P0 锁定版本再次核验。本次仅核对文档，未执行 SDK 集成。

## 9. 工程引用、输入集合与证据适用性

使用共享结构统一引用，各领域继续保存各自对象，不增加新的通用业务状态机。初期用 PostgreSQL 表、唯一约束和正反向索引实现，无需图数据库。

|结构|最小语义|写入与使用责任|
|---|---|---|
|EngineeringRef|kind、object_id、revision、适用时 digest/digest_algorithm|对象所属领域产生；外部引用另带 authority，敏感值只用版本引用|
|InputSet|不可变 input_set_id、规范化引用集合及集合摘要|执行发起领域冻结；指向需求、契约、源码、构建、配置与环境条件|
|EvidenceRecord|subject_ref、input_set_ref、method/version、环境、结果、观察时间与适用范围|验证/构建/交付等生产领域写入不可变事实|
|DependencyLink|consumer_ref、producer_ref、required_quality、rule_id/rule_version|消费领域声明关系，协作领域维护工作项关系|
|适用性判断|evidence_ref、consumer/input_set、valid/needs_review/superseded、规则版本与理由|消费领域判定并记录，不改写历史证据|

摘要类型与作用域必须明确，Git commit、镜像身份、归档摘要不能混用。每次恢复和结果接收都核对实际输入集合；工作流重放不得重新采集不同输入仍沿用旧 InputSet。

|输入变化|影响规则|
|---|---|
|需求/契约修订|沿显式消费者引用传播；已证明兼容的范围可保持有效，其他标记 needs_review|
|集成提交变化|按源码证据的精确提交和范围判断，旧 SHA 报告不能直接证明新 SHA|
|基础镜像、构建参数、锁文件或架构变化|重新判断构建及制品证据，源码审查按自身范围另判|
|配置或 secret 版本变化|引用旧运行输入的未执行计划需要重新生成及审批|
|目标环境安全相关状态变化|重新核对部署起始条件；当前部署自身合法步骤按 D04 更新步骤前置状态|

影响传播有稳定变更身份和去重记录；变更事务先使受影响输入的有效性版本前进，尚未完成分析的消费者保持 needs_review。accept_result、complete_task、形成 Release 和启动部署必须检查当前输入/有效性版本，不能在异步分析尚未完成时使用旧缓存结论。

兼容判断必须来自版本化规则或正式复核证据；模型建议不能独自清除失效标记。删除和保留策略同时考虑 DependencyLink、InputSet、证据和活跃工作流引用，历史 accepted/succeeded 不因当前适用性变化被擦除。

## 10. 接口与验证边界

对外保留项目、任务、工作项、会话、消息、决策、上下文及报告资源；命令支持幂等键与 expected_version。协调工具走同一领域授权，不暴露直接更新状态表的能力。

本专题定义字段语义及转换条件。P0 冻结 Runtime 接口、执行映射、工程引用和首条链路命令；各领域的 OpenAPI、数据库约束与消息 schema 随 P1～P5 实现冻结并校验。P2 验证单 Agent 续接与证据链，P3 验证多 Agent 并发、收信、依赖、变更与返工，P4 扩大故障恢复覆盖，验收要求见 D06。
