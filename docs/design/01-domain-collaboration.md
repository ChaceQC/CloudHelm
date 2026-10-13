# 01 领域模型与 Agent 协作

> 文档版本：v4.7.0
> 对齐总体设计：v4.7
> 修订日期：2026-10-13
> 状态：设计基线，待实现及专项验证。

[返回文档索引](README.md)。执行恢复遵循 [D02](02-execution-recovery.md)，费用预留遵循 [D03](03-workspace-build-resources.md)。

## 1. 状态所有权与事务边界

初期采用模块化单体，各领域与 DBOS 系统表位于同一 PostgreSQL 数据库的不同 schema，但只能通过所属领域服务修改其权威状态。DBOS 负责队列、检查点、持久等待和重放，不自行解释验收或部署业务规则；API 与 Agent 工具都调用相同的领域命令处理器。

|负责模块|权威对象与规则|其他模块可以做什么|
|---|---|---|
|identity|User、DeviceSession、RoleBinding、Policy、Approval；应急授权配置的签发与审计|查询当前授权，提交审批请求；目标端应急授权接受与使用按 D05，不得代替人类批准|
|projects/collaboration|Project、Task、WorkItem、Decision、ContractRevision、Message、WaitCondition、DependencyLink|提交带版本的分配、交付、变更和完成命令|
|agent-runtime|AgentMember、AgentSession、AgentRun、ContextPackage、ModelRequestRecord|调度请求、读取执行结果；不凭模型输出修改部署状态|
|workspaces/integration|Workspace 写入权/临时环境、IntegrationAttempt、MergeQueueEntry、AcceptanceSuiteRevision、HumanTestSession、VerificationReport、Review、相应 EvidenceRecord|提交候选和证据，获取精确版本结果；正式验收资产和可选人工测试遵循 D03|
|execution|Operation、ExecutionAttempt、ResourceReservation、StepExecution 索引|创建授权操作，查询执行器权威步骤账本，申请取消或核对|
|delivery|ReleaseCandidate、BuildRun、Release、EnvironmentConfigRevision、DeploymentPlan、Deployment、EnvironmentRevision|消费构建和执行证据，决定发布或部署状态转换；本机恢复事实核对后导入，不伪造普通许可|
|operations|ObservedState、DriftRecord、Incident、ProbePolicyRevision、通知与紧急修复关联|报告观测、通知确认和处置；变更期望状态须调用 delivery|
|workflow|WorkflowBinding、DBOS 接入与恢复门禁；队列/检查点归 DBOS|按业务身份提交和查询；业务工作流由所属领域定义|
|sync|Outbox、EventLog、DispatchEvent、游标|分发和重放业务事件，不产生独立业务结论|

BuildRun 保存构建业务结果，物理进程与步骤事实由执行器账本产生，execution 保存索引和回报投影；AgentRun 保存一次有界推进，外部副作用归 Operation。Runtime 自身的工具调用不能直接写入部署状态。每类 EvidenceRecord 由产生证据的领域写入，消费者领域应用适用性规则；共享引用结构不成为另一套业务状态所有者。

应用命令处理器先核对当前权限及持久命令去重结果；需要新业务转换时，在统一短事务内校验 expected_version，调用负责领域写入状态、业务事件和必要 Outbox；若需启动工作流，在该事务中通过 DBOSClient 的事务入队接口写入 DBOS 系统表及 WorkflowBinding。已提交命令的同摘要重投及已完成 Task 的固定查询结果按第 2.1 节返回，不因旧 expected_version 再次要求转换。DBOS 系统表只能由支持的 SDK 接口和迁移流程操作。跨事务长过程通过持久结果交接，接收方按事件 ID 去重并校验资源版本。等待网络、模型、Git 或容器时不得保持数据库事务与行锁。具体身份及事务规则归 D02。

工作流步骤重试调用领域命令时，使用稳定 command_id、输入摘要及领域去重记录；业务事务已提交而 DBOS 检查点未落盘时，返回既有命令结果，不能再次推进业务版本。DBOS 的执行状态通过适配层查询，UI 的业务阶段仍由所属领域与证据投影。

禁止通过“把所有状态改成失败”处理一次超时。调度租约到期、物理执行未知、业务需要核对分别记录。界面可汇总，但可展开查看各自原因。

### 1.1 应用命令与统一事务上下文

“结束 Run”“接收工具结果”“接管工作区”“批准部署”等应用命令位于所属业务模块的 application 层。处理器创建 UnitOfWork，统一管理同一 SQLAlchemy Connection/Session 的提交与回滚；参与服务接收该事务上下文，在各自模块内校验和写入，不自行 commit、另开独立连接或用后台任务逃逸事务。处理器通过接口协调，不直接写其他模块的表，不建立另一个承载全部业务的公共编排模块。

命令信封至少包含 command_id、调用身份、资源范围、request_digest 和必要 expected_version。去重结果、业务更新、事件、WorkflowBinding 与事务入队共同提交；相同身份异输入拒绝，事务已成功但回执丢失时返回既有结果。异步 ORM 与 DBOS 接缝遵守 D02，不能把普通异步入队误当事务参与者。

例如结束 Run 时，历史边界、获当前业务推进资格允许的工具提交意图、必要 Operation/WaitCondition、Run 终态与后续推进同属一次事务；只需要提交回执的工具不必创建等待物理完成的条件。Task 已完成或取消后，结束原 Run 只归档已发生事实，不再创建普通执行意图或续接。执行器在事务提交后才接受实际执行。文件/制品先经受控接口原子保存并校验，事务只引用已存在内容；事务失败留下的无引用内容按保留策略清理，不能把文件写入说成数据库事务的一部分。

P0 验证参与模块任一写入或入队失败时整体回滚，以及提交后丢失回执时版本只推进一次。跨事务外部动作继续使用 Outbox、稳定身份与实际结果核对，UnitOfWork 不提供跨机器原子性。

## 2. 业务对象与状态

|对象|生命周期及转换依据|
|---|---|
|Task|draft、active、paused、waiting_input、completed、failed、cancelled；planning/implementing/integrating/verifying/reviewing 作为基于工作项与证据的展示阶段|
|WorkItem|pending、ready、running、blocked、submitted、accepted、failed、cancelled；只检查本工作项声明的依赖|
|AgentSession|idle、queued、running、waiting、paused、completed、failed；运行结果另存 AgentRun|
|AgentRun|queued、running、succeeded、failed、interrupted；succeeded 表示本次推进已提交，其 outcome 为 tool_requests、waiting_condition、submitted 或 continue_required，不表示 Task 完成|
|ReleaseCandidate|created、policy_check、pending_approval（策略要求时）、building、human_test_pending（用户开启时）、verified、failed|
|HumanTestSession|固定候选的可选人工测试，生命周期与人类结论分开；完整规则归 D03 第 2.3 节|
|Deployment|planned、pending_approval、queued、preflight、applying、verifying、needs_reconciliation、succeeded、failed、partially_applied、cancelled；细节归 D04|
|Incident|open、investigating、action_pending、mitigating、resolved、closed|

Task 生命周期与展示阶段分开：多个工作项并行时，阶段可同时标示实现和验证；阶段展示不阻止符合依赖的工作继续。paused 停止新调度，已有操作如何停止由 D02 确认，不能把它们直接标为已取消。

### 2.1 首条链路的 Task 完成边界

Task 的 `completed` 只表示本任务声明的开发交付和必需验收已经完成，并且最终集成版本有当前有效证据。本节是完成命令、唯一完成决定及范围归属的权威规则；执行器封闭、在途收尾和实时门禁归 D02 第 7.2、11 节，不增加 `completing` 状态或另一套调度流程。

完成前，所有必需 WorkItem 均须达到 `accepted`，其交付和验收证据须适用于同一个最终集成输入；必需验收条件均满足，集成结果及其验证证据仍有效。可选人测只有在 Task 完成前由交付策略明确将该轮人测纳入本次完成条件时，才构成完成门槛。解除人测 WaitCondition 不等于测试通过：`passed` 和按策略获准的 `skipped` 均可能解除等待，纳入门槛的人测只有在该策略修订明确允许跳过且已有获授权的人类跳过结论时，才可凭 `skipped` 满足完成条件；不得将跳过、过期、撤销或仅关闭等待投影为 `passed`。

完成报告按 Task 唯一、不可变，冻结需求与验收修订、最终集成提交、InputSet 及其有效性版本、必需检查与证据引用、完成命令和提交时的业务版本/控制修订。人测另保存该轮是否属于完成门槛、对应策略修订以及真实结论与结论证据，明确区分 `passed/skipped`；未纳入门槛或没有结论的情形也如实记录，不补写通过或覆盖原结论。完成后另行选择的人测不追溯改变完成结论；其反馈如需修改，创建关联修复 Task，不改写或重新打开原 Task。

`complete_task` 携带通用命令身份、幂等键、规范化请求摘要，以及预期 Task 业务版本、控制修订和输入有效性版本。按下表从上到下处理；所有分支先检查调用者对当前 Task、命令及所返回报告的当前访问权限，历史成功不授予已被撤销的访问权。具体响应码由 P0 的 API schema 冻结，业务结果不得因编码选择而改变。

|请求情形（按判定顺序）|行为|
|---|---|
|同幂等键、同摘要重投|优先返回原命令结果及原报告引用（若原结果包含报告）；不重新验收，不因原提交已经推进业务版本、控制修订或输入有效性版本而改报版本冲突|
|同幂等键、不同摘要|返回幂等冲突，不能覆盖原命令或改写摘要后重试|
|新幂等键，Task 已为 `completed`|返回固定的“已完成”结果和唯一原报告引用；不重新验收、不创建第二份报告，不推进 Task 业务版本或控制修订|
|新幂等键，Task 为 `active`|核对下述全部完成门禁；满足后提交唯一完成决定|
|新幂等键，Task 为 `waiting_input`|纳入完成范围的必需输入及等待均已有有效结论，且其余完成门禁满足时允许提交；无需为完成额外启动模型 Run|
|新幂等键，Task 为 `draft、paused、failed、cancelled`|拒绝直接完成，保持原状态；不能借完成命令执行启动、恢复或重开|

上述判定在命令去重与 Task 条件事务中串行化；并发竞争后重新读取去重记录及当前状态，已经 completed 时按对应分支返回，仍需新业务转换时才校验预期版本。不得先做版本检查而跳过原命令结果或已完成结果。

对尚未完成且来源状态允许的新命令，先通过 D02 的受控查询/停止/封闭流程取得必要执行事实；证据未齐时返回阻塞对象，保持 Task 原状态，不在完成事务内等待远端。最终完成在一个短事务内执行：

1. 在短事务内核对预期业务版本、`control_revision`、无取消意图及当前输入有效性版本；逐项检查必需工作项、验收、集成与人测策略。影响分析尚未完成或证据为 `needs_review/superseded` 时不得采用旧结论。失败返回阻塞对象及原因，保持 Task 原状态，不生成完成报告。
2. 读取并核对所有仍可能修改本次交付范围、工作区或完成依据的写 Operation 的持久执行证据。每项必须已有已结束且影响已核对、已安全停止，或已在执行器启动锁与持久账本中可靠封闭为未启动的证据；完成检查使用核对后的最终输入，不能采用写入发生前的验证结果。仅收到提交回执、进程暂未被观察到、发出了停止请求或执行结果未知，均不满足门禁；未知写入阻止完成。
3. 所有新增相关执行意图、写入资格及输入失效登记，必须参与完成命令所检查的 Task/输入版本条件更新。完成事务再次核对执行意图集合及有效性版本，防止在事务外检查后又接受新写入；外部执行器查询、停止和封闭在事务外完成，不能在数据库事务内等待。
4. 同一短事务内保存按 Task 唯一的完成报告和原命令结果，提交 `completed`，各推进一次业务版本及 `control_revision`，记录事件并关闭本 Task 的普通推进资格。关闭范围包括新分配/领取、Run 与模型请求、普通工具意图、业务修改及等待续接；所需通知和后置核对按既有事务交接规则提交。

输入失效与完成决定在同一有效性版本上竞争：失效先提交，完成使用的旧版本必须失败并返回阻塞；完成先提交，后来变化追加影响事实并按范围创建关联 Task，不重写冻结报告。完成与取消在同一 Task 业务版本和控制修订上竞争，按第 2.2 节由先提交者决定；任何旧 Run、晚到回执或等待唤醒都不能越过获胜的控制修订。

Task 完成后，已在途 Run 只可归档原请求的历史、费用、工具结果和实际影响，不得新增普通工具意图、业务修改或等待续接。清理、结果接收、费用核对及停止/核对流程按自身受限权限继续；资源按 D03 的物理事实释放。独立归属的人测、Release、Deployment 和 Incident 继续由各自领域的生命周期、授权和证据决定；Task 完成不会隐含形成 Release、执行 Deployment 或关闭 Incident，也不授予这些独立流程权限。

主要转换条件如下：

|命令|前置条件|结果|
|---|---|---|
|start_task|Task 仍为 draft；目标、需求与验收修订、调用者权限、预算及资源范围明确；版本匹配|Task active，登记初始工作项并可靠创建初始 Run/推进请求；实际模型/执行准入仍按 D02、D03 的当前门禁处理|
|claim_work_item|Task active 且无取消意图；WorkItem ready；依赖与证据当前有效；领取者获准且无其他有效分配；资源准入可行|条件更新为 running，创建执行引用；领取本身不授权绕过后续副作用门禁|
|submit_result|提交来自当前有效尝试，产物存在，输入版本明确|保存不可变交付记录，WorkItem submitted|
|accept_result|验收条件满足，证据与输入仍有效|WorkItem accepted；派生交付事件|
|request_rework|结果失败或输入失效，返工范围明确|保存旧结果，新修订或新工作项重新排队|
|complete_task|按本节顺序处理当前权限、幂等重投与已完成结果；新完成只来自 active 或满足条件的 waiting_input，且全部版本、证据和写 Operation 门禁通过|同一短事务冻结唯一完成报告、提交 completed、推进业务版本和控制修订并关闭普通推进；不要求 Release 已形成或 Deployment 已执行|
|change_requirements|用户授权、预期 Task 版本匹配|新增需求修订，计算影响并阻止失效结果被继续采用|

结果的历史完成状态和当前适用性分开。已 accepted 的历史交付不会被擦除，但输入变化后其有效性标为 needs_review 或 superseded。已 completed Task 的新功能或故障修复创建关联 Task，不改写原完成结论。

可选人工测试以 HumanTestSession 和业务 WaitCondition 关联候选。用户结论与解除相应等待通过幂等应用命令同事务提交，自动化/Agent 身份不能提交人类通过或替人跳过；等待不占活跃 Run。解除等待按真实结论及本节的完成策略解释，不能等同于 `passed`；Task 已完成时可保存独立人测结论，但关闭的 Task 续接仍受控制修订约束。反馈返工按 Task 是否已完成选择工作项或关联修复 Task，不直接重开历史完成任务。人类测试通过只证明所记录范围，不代表正式环境已获批部署。

### 2.2 Task 取消命令与终态判定

保留 Task 现有状态枚举，不新增 `cancel_requested` 状态。取消意图由 `cancel_requested_at`、`cancel_requested_by`、`cancel_reason` 和递增的 `control_revision` 表达；界面根据取消意图及执行事实投影“取消处理中”。`cancel_task` 命令信封至少包含 `command_id`、`request_digest`、`expected_version` 和通用命令身份/范围。去重、权限与版本检查在应用事务中完成；成功登记取消意图时推进 Task 版本及控制修订。重复提交按原命令结果返回，不能以新命令或旧版本覆盖已生效的取消。

取消意图提交后，所有普通推进、任务/工作项准入、领取、模型请求、工具写入和等待唤醒均须检查当前 `control_revision` 并停止。尚未开始的普通工作不再启动；已开始的工作在安全边界停止或转入核对。独立的取消、查询、停止、结果接收及核对控制流程按 D02 第 7.1 节限定的控制权限继续运行；详细传播对象、执行机制与权限矩阵由 D02 定义，本节不另建传播规则。

取消范围按所有权判定：Task 所有的执行意图（例如该 Task 的代码修改、构建和测试）进入停止或核对流程；Task 只引用的共享结果及其 Operation 不因单一消费者取消而被停止；独立 Deployment 或业务实例继续按自身命令和授权处理，取消 Task 不授予生产停机、回滚或补偿权限。

只有同时满足下列条件，Task 才能进入 `cancelled`：

1. 取消意图已可靠提交，所有普通推进入口均受当前控制修订约束。
2. 当前 Run 已结束，或已在业务层失去继续推进该 Task 的资格；历史和请求记录已持久保存，且不存在可继续普通推进的入口。
3. 每个 Task 所有的 Operation 均已确认未开始、已停止，或已完成且其实际影响已记录并归档。
4. 不存在仍可能继续产生影响的未知物理执行；结果未知且执行账本不足以排除物理执行时，保持取消处理中并继续核对。
5. 必要结果和已发生影响已归档；资源预留依据执行器等物理事实保留、核对或释放，具体资源规则归 D03 第 4 节。

未知费用或模型 usage 可继续留在费用账本中，不单独阻止 Task 进入取消终态；未知物理执行则阻止终态。取消不证明操作失败或无影响。晚到回报可以补充原 Operation 事实和不可变证据，但不能复活 Task、自动创建新 Run，或解除已关闭依赖。已完成 Task 与取消命令同时竞争时，`complete_task` 与 `cancel_task` 在同一 Task 版本和 `control_revision` 上执行条件事务更新；先成功提交者决定业务结果。完成先提交时取消返回既有完成结论且不改写历史；取消先提交时完成命令被拒绝，不能将 Task 改回 `completed`。

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

Run 遇到延迟工具交接、人工/依赖等待、交付结果或推进预算边界时提交结果后结束。长工具按第 5.2 节先提交操作并取得回执，只有真正依赖结果时才保存等待原因；Operation 独立推进，同一 Session 可继续不依赖结果的合法工作。达到预算边界可登记 continue_required，由当前授权及预算决定是否入队下一 Run，不把不完整模型响应伪装成完成消息。过期 Run 无权提交新工具副作用和业务结果；已启动操作仍按 D02 核对。

协调 Agent 提出分配、依赖变化、拆分和返工建议，由领域服务应用。独立验证读取权威验收和实际代码，审查角色对候选只读。发布与运维角色解释风险或提出方案，确定性执行器完成获批变更。

团队规模依据独立可执行工作、沟通成本和资源预算决定。不得仅因角色列表中存在某角色就创建常驻会话。连续返工、循环等待或通信无新增证据时升级为明确待决问题；预算与无进展阈值须可配置并记录触发依据。

## 5. 消息、收件箱与等待

Message 正文不可变，保存 message_id、发送身份、接收范围、task_id、conversation_id、correlation_id、时间及结构化工程引用。类型包括 question/answer、change_proposal、blocker/unblock、review_feedback、handoff、decision_notice；消息不是批准或依赖成立的证据。

每个接收 Session 保存 InboxDelivery，按 message_id + recipient_session 唯一；queued、delivered、processed 分开。业务处理结果与 processed 在可覆盖的同一事务提交；外部副作用先形成 Operation 引用，processed 不表示该操作完成。

WaitCondition 归业务层，保存 wait_id、owner_session/work_item、condition_revision、关联回复/Operation/依赖引用、必要结果、期限、升级规则与 resolved/closed 状态。等待不绑定一个必须长期存活的 DBOS workflow_id，通知寻址稳定 Session/业务对象。

### 5.1 可靠交接与续接

1. Run 通过第 1.1 节应用命令，在一个短事务保存完整消息历史边界、自身终态并释放 Session 的有效 Run 引用；仅当所属 Task 当前仍有普通推进资格时，才可同时提交工具请求、必要 Operation 和 WaitCondition。已完成 Task 的在途 Run 只保存原请求事实。提交工具回执与等待最终结果按第 5.2 节分别处理。
2. 登记等待时检查已到达的回复和已完成结果；若条件已满足且所属业务对象当前有推进资格，同事务登记唯一推进请求并使用 D02 事务入队。外部操作执行也从该事务可靠交接，不能先执行再补记录。
3. 新消息、工具结果、批准或依赖变化事务更新权威业务记录，重新计算有关条件；条件满足、Session 可运行且 Task 的当前业务版本/控制修订仍允许普通推进时，创建唯一推进请求、新 Run 和 WorkflowBinding，并事务入队。完成与等待唤醒竞争遵循 D02 第 7.2 节；晚到结果只归档，不能重开已关闭的续接。跨事务/外部交接使用 Outbox 和稳定 event_id。
4. 推进请求按 session_id + continuation_revision 唯一。Session 已有有效 Run 时只合并待处理标记，不再创建第二个 Run；Run 在模型或工具安全边界读取消息，并在结束事务再次检查待处理条件。
5. 新 Run 加载 committed history 和匹配原 tool-call ID 的已确认结果，重新检查权限、Task 状态、依赖及预算。重复通知返回既有推进结果，不能重复分配工具副作用。
6. 超时由 DBOS 定时能力触发有界条件检查；回调按 wait_id + condition_revision 去重，已解决/被替代的等待不再生效。补偿检查只修复漏推进，不维护第二套领取、租约或重试调度器。

PydanticAI 的 DeferredToolRequests/DeferredToolResults 表示延迟工具请求与协议结果。同一协议批次必须取得各工具定义所要求的完整结果后才能续接，不默认依赖框架的部分结果能力；submit_operation 的确定结果是可靠提交回执，await_operation 的结果才是最终执行结果。unknown 不作为等待成功/失败结果，不伪造终态让模型重做。普通业务消息可累计，撤权、暂停、取消和破坏性变更优先进入控制处理。

长期人工/依赖等待不保留活跃 AgentRun 或常驻编排工作流。必要的 DBOS 定时等待有独立有界维护容量，不占模型或重执行槽；定时与记录保留仍纳入容量预算。短流程内部的受限等待可以使用 DBOS 原语，不能据此重新创建每个 Task 一个常驻流程。

暂停只积累消息和结果；恢复事务检查可运行条件并可靠入队。目标 Task 已结束时，由领域命令决定归档或关联新 Task，不能凭消息自动重开。动态等待关系和静态依赖图都检查循环；超时不等于同意。

### 5.2 长工具提交与按需等待

长工具暴露提交与等待两个逻辑动作，名称可随工具类型细化，但语义固定：

|动作|返回与持久边界|后续约束|
|---|---|---|
|submit_operation|通过 Gateway 校验并在应用事务中创建/复用 Operation、输入引用与执行入队；提交后返回 operation_id、输入摘要、accepted 状态及查询/等待引用|accepted 仅表示可靠接收；不证明已准入物理资源、完成或生成产物|
|await_operation|先按当前权限查询；有确定结果则返回证据引用，否则在当前业务推进资格允许时原子登记 WaitCondition 并结束 Run|完成事件按当前 Task 状态及控制修订可靠续接；unknown 保持核对，暂停不自动唤醒，已完成/取消不重开续接|
|query_operation|有界状态查询，带观察时间|用于展示与诊断，不以高频模型轮询代替持久等待|

提交回执绑定原 tool-call ID，不在物理执行结束后覆盖成另一份工具返回。若提交工具本身走延迟接口，先结束 Run，再以完整提交回执续接新的 Run；该交接不等待物理 Operation 完成。等待工具使用自己的调用身份，最终结果仍引用同一 Operation。P0 固定 SDK 消息顺序、批次上限、回执丢失去重及早到结果处理。

Runtime 按工具类别约束批次，短查询、长任务提交和等待屏障分别组织；无依赖的外部任务不强制共享最终完成屏障。若模型仍提出混合批次，按当前工具 schema 返回明确校验/拆分要求，不偷偷截断协议历史。已接收的旧式最终结果批次只能按其原语义完成或显式迁移，不用提交回执替换预期产物。

具有产物依赖的下游命令必须提供有效 EngineeringRef/EvidenceRecord，Gateway 与领域服务共同校验归属、输入和质量；operation_id 或模型自述不构成依赖满足。单 Session 仍最多一个有效 Run，其他工作项按任务图继续，不重复创建同义操作。重复无新增信息查询进入无进展/预算控制；取消与费用核对仍归 D02/D03。

人工接管按 D03 第 2.2 节阻止相关写入；交还产生新的工作区版本和变更通知，按第 9 节重判依赖及证据，必要时切换 Epoch。不能在 UI 标为“人工接管”后仍允许旧 Run 写文件。

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

外部副作用工具和长任务将执行交给 Gateway/Operation，按第 5.2 节区分可靠提交回执与等待最终结果；需要中断续接时使用 ExternalToolset 或等价延迟接口。纯查询走受限查询步骤，协作变更走幂等领域命令。PydanticAI 的工具批准只承载交互，不构成 CloudHelm 人类审批或本机应急授权。模型不得通过框架本地 workspace、shell 或 MCP 直连绕过 Gateway。

每次实际模型请求均先登记 ModelRequestRecord 和费用预留，再发送；校验修复、重试、压缩也遵守此入口。P0 必须验证官方接入能在真实请求前执行当前门禁、只对新请求计费、保存可恢复协议历史，并限制 SDK 内部重试。如果不能满足，记录接缝缺口并修订适配方案，不能默默引入第二套检查点或副作用重试链。

编排并发、模型请求并发和物理占用分别管理；框架自动并行工具只产生请求集合，不直接获得并行执行权限。Run 按最大模型请求数、总时长和费用设有界推进政策，具体值在 P0/P2 测量后固定。

运行时依据继承自 v4.4 对 PydanticAI [Agent 逐节点推进](https://ai.pydantic.dev/agents/)、[外部工具与延迟结果](https://ai.pydantic.dev/deferred-tools/)和 [DBOS 集成](https://ai.pydantic.dev/durable_execution/dbos/)的核对。当时推荐 DBOSDurability 接入并避免已弃用的 DBOSAgent 包装；本次未重新核验上游接口，接口名、弃用状态及新增提交/等待接缝须在 P0 锁定版本后验证，不表示已执行 SDK 集成。

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
|需求/契约/正式验收修订|沿显式消费者引用传播；已证明兼容的范围可保持有效，其他标记 needs_review；正式验收资产规则归 D03 第 6.1 节|
|人工修改及写入权交还|固定新工作区版本，旧 Run 写入无效；按差异和精确候选重新判断证据|
|集成提交变化|按源码证据的精确提交和范围判断，旧 SHA 报告不能直接证明新 SHA|
|基础镜像、构建参数、锁文件或架构变化|重新判断构建及制品证据，源码审查按自身范围另判|
|配置或 secret 版本变化|引用旧运行输入的未执行计划需要重新生成及审批|
|目标环境安全相关状态变化|重新核对部署起始条件；当前部署自身合法步骤按 D04 更新步骤前置状态|

影响传播有稳定变更身份和去重记录；变更事务先使受影响输入的有效性版本前进，尚未完成分析的消费者保持 needs_review。accept_result、complete_task、形成 Release 和启动部署必须检查当前输入/有效性版本，不能在异步分析尚未完成时使用旧缓存结论。

兼容判断必须来自版本化规则或正式复核证据；模型建议不能独自清除失效标记。删除和保留策略同时考虑 DependencyLink、InputSet、证据和活跃工作流引用，历史 accepted/succeeded 不因当前适用性变化被擦除。

## 10. 接口与验证边界

对外保留项目、任务、工作项、会话、消息、决策、上下文及报告资源；命令支持幂等键与 expected_version。协调工具走同一领域授权，不暴露直接更新状态表的能力。

本专题定义字段语义及转换条件。P0 冻结 UnitOfWork、提交/等待工具、Runtime、执行映射和首条链路命令；OpenAPI、数据库约束与消息 schema 随 P1～P5 冻结。P2 验证单 Agent、正式验收和人工交还，P3 验证多 Agent 批次/依赖/收信/返工，P4 扩大恢复覆盖；验收见 D06。

首条链路接口验收至少覆盖：`start_task` 对目标、需求/验收修订、授权、预算和资源范围的校验；`claim_work_item` 对 Task 活跃/未取消、依赖有效、唯一有效分配及资源准入的原子校验；`complete_task` 对 §2.1 来源状态、全部版本、必需交付/验收、集成证据、人测真实结论及未知写 Operation 的校验。新业务转换拒绝过期 `expected_version`；同身份同摘要重投优先返回既有结果，异摘要复用身份被拒绝，新键命中 completed 返回原报告且不推进版本，以上返回均检查当前权限。完成回执丢失后分别覆盖这三种重投，并验证完成与输入失效、取消、等待唤醒竞争时只有合法结果生效。

完成或取消后验证普通准入、Run 续接、模型请求、工具写入和等待唤醒均被当前推进资格拦截；已接受写操作回执未知时不得完成，执行器封闭后旧消息不得启动。取消终态另以未开始、已停止、已完成、有已知影响和未知物理执行覆盖；晚到事实只能归档；共享结果引用、独立人测/Release/Deployment/业务实例和资源释放均按各自所有权与权威证据处理。D02 负责完成/取消传播及受限控制权限的详细接口验收，D03 第 4 节负责资源证据与释放验收。以上是待实现验收要求，不表示已完成测试。
