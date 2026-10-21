# P0 Task 完成与取消决定 r1

> 日期：2026-10-14（Asia/Shanghai）
> 工作包：P0.3-02b。
> 修订：决定 `p0-task-control-r1`；契约 `p0-decisions-r1`。
> 权威依据：D01 v4.7.0 §2.1～2.2、D02 v4.7.0 §7/§11/§12.5、D03 v4.7.1 §2.3。
> 性质：本文件只记录决定与边界，不代表已实现或已验收。

本决定按 [D01 §2.1～2.2](../../design/01-domain-collaboration.md)、[D02 §7、§11、§12.5](../../design/02-execution-recovery.md) 和 [D03 §2.3](../../design/03-workspace-build-resources.md) 固定 P0 Task 控制的实现输入。

身份、摘要和当前动作权限继承 [身份与权限决定](identity-permissions-migrations.md)；资源事实与释放继承 [资源决定](resources-task-control.md)。旧 `p0-draft-r1`、实验协议、历史 InputSet 与历史完成记录保持原语义，不能凭本次 schema 校验自动迁移。

## 1. 状态、命令与可信事实

Task 状态完整保留 `draft、active、paused、waiting_input、completed、failed、cancelled`。`cancelled` 已存在于 D01 §2 的枚举；本次不新增 `cancel_requested` 或 `completing`。规划、实现、集成、验证和审查仍是展示阶段。`TaskControlFacts.state` 是权威 Task 的只读投影，不是第二份可更新的状态。

`TaskControlCommand` 复用 `identity_contracts.CommandEnvelope`，目标必须是指定项目下的 Task。完成使用外层动作 `task.command`，取消使用 `task.cancel`；请求 schema 固定为 `p0-task-control-r1`。请求体字段如下，全部参与身份决定定义的 UTF-8/JCS 摘要：

|命令|请求体与版本|含义|
|---|---|---|
|`complete_task`|`expected_control_revision`、必填 `expected_input_validity_revision`；业务版本使用信封 `expected_resource_revision`|不接收客户端自报的完成结果、人测通过、当前授权或执行器封闭证明|
|`cancel_task`|`expected_control_revision`、必填有界公开原因码 `cancel_reason`；业务版本使用信封 `expected_resource_revision`|取消请求不要求当前输入仍可验收；不携带完成专用输入版本，不附任意执行脚本|

命令模型重算并核对规范摘要。调用者、委托人、scope、target、动作、schema 与预期业务版本均继承身份信封；不得换 target 或控制字段后沿用原摘要。`command_id/idempotency_key` 仍遵循公共去重规则，不能作为新的物理执行身份。

`CurrentTaskAccess` 和 `TaskControlFacts` 只能由受信任应用适配层构建。前者绑定本条 command、真实 caller、scope、Task、动作、权限修订及授权决定身份，`command_allowed` 必须包含身份层的角色上界、当前权限、委托和资源归属判断；`report_read_allowed` 包含将返回报告的当前访问权。二者不得接受客户端字段，不得以缓存的历史成功、模型布尔值或这个纯函数的返回值建立权限。完成请求当前必须同时具有完成命令与完成报告读取权。

事实读取使用同次权威事务视图；执行器网络查询和停止在事务外先取得持久证据，再在短事务内核对适用版本。`required_work_items_accepted`、`required_acceptance_satisfied`、`evidence_current`、`required_waits_satisfied` 和 `operation_set_current` 分别是**完整集合**的权威合取投影，默认均为 false。它们不是由请求者勾选的验收选项：

- 必需工作项来自当前 Task 范围及依赖记录，全部为 accepted，交付、检查、候选和证据覆盖同一最终集成输入。
- `input_current` 需要影响分析完成且当前有效性版本匹配；`needs_review/superseded` 证据不能折算为 true。
- 必需检查及独立验收资产来自受控来源；`required_check_ids` 与证据引用必须完整覆盖，不能只取已通过的部分。
- 操作集合包含所有可能改变本次交付、工作区或完成依据的写意图，以及判定取消所需的全部 Task 自有 Operation；排队、已接受但回执丢失和 unknown 也要纳入。

单个投影上限为 64 个必需检查、128 个证据引用和 128 个 Operation。超出时拒绝构造该投影，返回受控的范围过大原因并保留原 Task；不得截断集合、分批通过后推断整体通过。费用账本不复制到该受限集合，仅投影是否存在未知 usage，不因待核对模型请求的数量限制取消。这些是本 P0 契约的有界输入限制，不是产品容量或吞吐承诺。

## 2. 完成裁决顺序与短事务

完成来源、唯一报告、版本门禁和竞争裁决的权威规则见 [D01 §2.1](../../design/01-domain-collaboration.md#21-首条链路的-task-完成边界)。下表只固定该规则在 `p0-task-control-r1` 中的分支及业务码；所有分支先执行本次当前授权，再在持久去重与 Task 条件更新的同一串行化边界中裁决。

|顺序与请求|固定行为|业务结果|
|---|---|---|
|当前访问已撤销或绑定不符|不返回既有命令结果或报告|`permission_denied` / `authorization_binding_mismatch`|
|同调用者/scope/幂等键、同摘要|返回原 command 和原持久结果引用；原结果含报告时返回同一原报告；原拒绝也原样返回|`replay / original_command_result`，不重新验收或检查旧预期版本|
|同键异摘要，或错误的作用域记录|拒绝，不覆盖原记录|`idempotency_digest_conflict` / `idempotency_scope_mismatch`|
|新键，当前已 completed|返回唯一原报告；不再做新转换版本/验收检查|`already_completed / task_already_completed`|
|新键，当前 active|核对全部新完成门禁|只在事实满足时给出内部 `completion_eligible`|
|新键，当前 waiting_input|当前必需输入与等待已有有效结论，且其余门禁满足|允许完成；无需额外启动模型 Run|
|新键，当前 draft/paused/failed/cancelled|拒绝直接完成，不顺带启动、恢复或重开|`completion_source_not_allowed`|

不得在上述分支前调用会先校验新转换版本的通用业务入口；本模块承接身份层的当前判权投影，专门保留 D01 的“新键命中 completed 先返回报告”语义。竞争后重读去重与当前 Task，再按此顺序判断。原结果或报告缺失时返回 `idempotency_result_missing` / `legacy_completion_report_missing`，保留历史，不尝试“补跑一次完成”来生成替代报告。

新转换沿用 D01 §2.1 的全部当前版本、控制、输入、工作项、验收、等待及证据门禁。对应失败码固定为 `resource_revision_conflict`、`control_revision_conflict`、`input_validity_revision_conflict`、`task_progress_closed`、`input_not_current`、`required_work_items_unaccepted`、`required_acceptance_unsatisfied`、`required_waits_unresolved` 或 `evidence_not_applicable`。达到公共修订类型上限时拒绝 `revision_exhausted`，不能回绕。

P1 应用命令处理器负责以下**一次短事务**，`decide_completion()` 不执行这些动作：

1. 核对同次当前授权、持久幂等、来源、全部版本及输入适用性，重新读取相关写意图集合。所有新相关意图、写入资格变化和输入失效登记均参与相同 Task/输入条件更新，不能只在提交完成前查询一次。
2. 将按 Task 唯一且不可变的完成报告、原命令结果、业务事件及所需受控交接一并保存；数据库唯一约束与条件更新共同保证不会产生第二份报告。
3. 提交 completed，业务版本与 `control_revision` 各增加一次；关闭新分配/领取、新 Run、新模型请求、普通工具意图、业务修改以及等待续接。
4. 并发冲突后重新读取并判定。完成先提交，后来取消返回既有完成报告；取消先提交，旧完成请求因取消意图和控制修订被拒绝。输入失效先提交则旧完成失败；完成先提交则后来影响归档并按范围创建关联 Task。

外部网络、模型、Git、容器、停止和封闭均不得在该事务内等待。事务失败也不能自动撤销已生效的执行器封闭。`completion_eligible / ready_for_atomic_completion` 只是纯函数对所给事实的判定，不是客户端成功回执、完成报告或状态更新；P1 不得直接把它返回为“Task 已完成”。

本决定冻结业务码的 HTTP 适配语义：新完成实际提交与新键读取既有报告为 200；同键重投返回原持久响应；当前权限失败为 403；请求 schema/字段/摘要验证失败为 422；幂等、来源、版本、缺失证据及各门禁阻塞为 409，并给出稳定业务码及获准读取的阻塞对象。取消意图可靠提交可返回 202，但只表示已登记请求。当前没有这些业务 HTTP 路由，JSON Schema 收集的是命令、报告与纯裁决形状。

## 3. 写 Operation、封闭与完成后的入口

执行关闭及收尾的权威规则见 [D02 §7.2](../../design/02-execution-recovery.md#72-task-完成关闭与在途执行收尾)；本节冻结执行模块交给 Task 的事实投影、证据字段及拒绝码。

`OperationClosureFact` 是执行模块提供的事实投影，不改变 D02 的 Operation 生命周期。`operation_ref` 沿用统一 `EngineeringRef`；执行证据必须绑定原 Operation、attempt、step、执行器与代次、影响范围、启动锁和当前控制修订。`closure` 的三个可收尾值具有下列证据含义：

|投影|所需真实证据|
|---|---|
|`ended_reconciled`|整项执行已经结束，全部步骤/进程及实际影响已核对并归档；最终候选和输入已经包含这些影响|
|`safely_stopped`|按该工具允许的安全边界确认完整执行组停止，实际影响已核对并纳入当前输入；发出停止请求不成立|
|`closed_unstarted`|在与正常启动相同的冲突资源锁和持久账本中，确认原意图未启动并封闭；覆盖迟到、重复投递与重启后恢复，证明不会再启动|

三个投影都必须有 `closure_evidence_ref` 和 `effects_recorded=true`；未启动的“无影响”也需要确认及归档。`running`、`stop_requested`、`unknown`、缺证据或尚未核对影响均阻断相关写操作。accepted、租约过期、取消了 DBOS 流程、没有观察到进程，均不能填写前三个值。`operation_set_current=false` 返回 `operation_set_not_current`；相关写入未收尾返回 `writes_unsettled` 和 `blocking_operation_ids`。

纯函数只验证这些字段和引用的完整性，不能验证远端事实为真、引用覆盖正确 Operation、锁互斥或磁盘实际回收。执行器失联、账本缺损、回执丢失或范围不符时保留 unknown，沿原身份查询。共享或独立 owner 的写入若影响本次完成依据，仍可阻塞完成；Task 只能按该 owner 的授权核对，不能因为引用了它就获得停止权。

完成后，Hub 每次领取/新副作用及执行器接受/实际启动前都检查当前业务资格、控制修订和持久封闭记录。`check_ordinary_progress_closure()` 只提供关闭及修订保护；调用点仍须检查该动作的允许来源、当前授权、输入、预算、资源、恢复和计划门禁。所有七类普通入口都必须接入，不能只在 UI 或 Task 主工作流检查。

旧 Run、Operation 回执、等待结果仅在 `fact.archive`、`operation.query/stop/reconcile` 等独立受限权限下追加原身份的历史、费用和实际影响。它们不重开 WaitCondition、不创建普通工具请求或新 Run、不修改冻结报告。取消主 DBOS workflow 不取消独立清理与核对控制流程，也不能依赖原 Run 的 finally 保证收尾。资源仍按 D03 的物理证据另行释放。

## 4. 唯一报告与真实人测

完成报告及人测门槛沿用 D01 §2.1，人测资源与结论适用范围见 D03 §2.3；本节只固定报告及人测事实的契约形状。

`TaskCompletionReport` 冻结 Task、报告身份、完整原完成命令、提交时业务版本/控制修订、UTC 提交时间与 `CompletionBasis`。后者保存需求、独立验收资产、最终候选、完整 Git 集成提交、InputSet 及有效性版本、必需检查身份和适用证据引用。全部工程引用直接复用 `engineering_contracts.EngineeringRef`，不另造一份引用协议。源码引用必须使用完整的 40 或 64 位提交身份，不能使用可漂移分支名。

报告模型要求提交后的两个修订分别等于原命令预期值加一；不可变模型和引用上限只是结构约束。全库一 Task 一报告、唯一约束冲突后的重读、原命令响应保存、事务不变量和报告内容真实性仍须 P1 数据库实现与并发验证。

`HumanTestCompletionFact` 与 HumanTestSession 生命周期分离，记录 `is_completion_gate`、对应 `policy_ref`、策略是否当前、是否允许跳过、轮次身份、真实结论、实际人类主体、UTC 时间、结论证据及最终输入适用性。是否属于门槛本身必须来自当前策略，旧的“可选”策略不能移除后来已生效的必需门槛。无结论必须保持 null；未选择人测时保留“不属于门槛/没有结论”，不能补写 passed。

- 纳入门槛的 passed 需要该轮真实且获授权的人类结论、当前策略以及对最终输入有效的证据。
- skipped 除相同要求外，还须当前策略明确允许、有人类明确跳过原因；报告保留 skipped，不能改成 passed。
- changes_requested、仅解除等待、过期、撤销、失联或没有结论均不能满足必需人测。未纳入门槛的独立人测保留真实记录，不追溯扩大完成条件。
- Agent/执行器身份不能提交人类结论；`authorized_human_conclusion` 必须由已存人类反馈命令、授权与审计记录核实，客户端不能声称为 true。

失败分别返回 `human_test_not_current`、`human_skip_not_authorized_by_policy`、`human_test_gate_unresolved`；非法结论形状直接拒绝。结论证据本身还须按 D03 覆盖被测制品、配置、数据基线、范围、测试者和时间。自动浏览器成功、固定脚本中的合成人类身份或这个模型构造成功都不是人测验收。

Task 完成后另行选择的人测、Release、Deployment 和 Incident 按自身权限与生命周期继续；反馈要修改代码时创建关联修复 Task。既有完成不代表发布、正式环境批准、部署完成或事故恢复。

## 5. 取消登记、传播与终态

取消归属与终态判定见 [D01 §2.2](../../design/01-domain-collaboration.md#22-task-取消命令与终态判定)，执行传播及受限控制见 [D02 §7.1](../../design/02-execution-recovery.md#71-task-取消传播与受限控制)。以下固定 `CancellationIntent`、传播分类与纯函数拒绝结果，不另定义生命周期。

`CancellationIntent` 持久保留原 `command_id`、`cancel_requested_at`、`cancel_requested_by`、公开 `cancel_reason` 与登记后的 `control_revision`。时间由服务端 UTC 时钟提供，实际主体来自本次认证/委托，不能由 Agent 代填另一个人。取消请求同样先判当前权限，再查完整 scope/幂等键；重复提交返回原结果，同键异摘要拒绝。新取消意图与普通推进条件更新竞争，成功登记时 Task 业务版本及控制修订各增加一次；新键也不得覆盖已生效的取消事实。

登记取消意图立即关闭本 Task 普通新分配、领取、Run/模型、工具写入和等待唤醒；已开始的动作按安全点停止或核对。界面据取消字段与实际执行状态显示“取消处理中”，不新增状态枚举。`cancellation_route()` 只分类已核实 owner/consumer 的控制去向，不执行取消、不产生权限：

|真实归属/对象|传播及保留边界|
|---|---|
|本 Task 的 WorkItem、Session、未启动工作|关闭本 Task 普通推进；保存所有权、取消主体及修订。其他 Task 的 WorkItem 不传播；WorkItem 不能建模为共享多 owner|
|本 Task 的 Run、Operation|沿原身份安全停止或核对，保留历史、请求、步骤、结果及影响；取消请求本身不证明已停止|
|共享 Operation/结果|只解除本 Task 的订阅，不中止 owner 或其他消费者仍在使用的执行|
|本 Task 的 WaitCondition|关闭或抑制自动续接；晚到事实只归档原对象，不重开已关闭依赖|
|ResourceReservation|继续计实际占用；只有 D03 要求的物理停止/封闭及磁盘回收或连续转记证据才能释放|
|独立 HumanTestSession、Release、Deployment、Incident、清理/核对|按各自生命周期、计划、许可与动作权限继续；取消 Task 不授予生产停机、迁移、回滚、配置修改或补偿权限|

人测记录独立，不代表其临时环境的每个 Operation 都拥有相同 owner；环境构建、启动和清理由实际执行意图归属决定。控制流程要有明确 Task/Operation/step/资源范围，不能借“取消收尾”提交新的普通业务修改。独立停止、核对和归档使用受控流程及自身权限，不依赖被取消父流程的 finally。

`cancellation_readiness()` 只核对 D01 已有 cancelled 终态的前置：取消意图已提交；所有普通入口已被控制修订封闭；当前 Run 已结束或失去普通推进权，历史与请求记录已保存；完整操作集合当前；本 Task 所有的每个 Operation 已确认未启动封闭、安全停止或结束并记录实际影响。未知物理执行返回 `cancellation_physical_execution_unsettled` 及原 Operation 身份；缺取消意图、未封闭 Run/历史或不完整操作集合分别明确阻断。真正进入 cancelled 仍由同版本/控制条件事务执行，本纯函数不改变状态。

`unknown_model_usage_present` 仅表示费用/usage 账本中仍有待核对记录，完整原请求身份与账目继续由费用账本持有，不补零、不释放预留、不伪造结算。它不单独阻止取消终态，也不被当成未知物理写操作；若模型已经触发真实工具，那个 Operation 必须单独列入物理核对。共享或独立对象未结束也不单凭消费者取消阻止其 Task 收尾。已有 completed 不可转取消；已有 cancelled 的只读返回不补造历史物理证据。

## 6. 交付、兼容与仍关闭的门禁

契约位于 [task_control_contracts.py](../../../packages/contracts/p0/task_control_contracts.py)，聚合入口为 `P0TaskControlContracts`。源码包含有界不可变声明及少量纯函数，声明规模按单一 Task 控制领域集中维护；没有新依赖、数据库表、假业务服务、第二份调度器或另一套生命周期。

[check_decision_task.py](../../../scripts/p0/check_decision_task.py) 导出 `run_checks() -> dict[str, bool]`，失败抛异常。固定正反例只检查：权限与幂等顺序、来源/当前版本、最终输入与证据、未知写/停止请求/缺封闭证据、人测 passed/skipped 与策略、普通推进关闭、取消归属及未知费用区别、报告不可变与聚合 schema。全部主体、引用、摘要形状和执行事实均为合成输入，不是独立正式验收资产。

```powershell
wsl.exe -d Ubuntu-24.04 --cd /mnt/e/Project/CloudHelm -- /home/cloudhelm/.local/bin/uv run --locked --offline python scripts/p0/check_decision_task.py
```

实际命令结果只在 [PROJECT_PROGRESS.md](../../../PROJECT_PROGRESS.md) 及统一出口记录维护；本模块窄检查不代替集成候选验证。D02 §12.5 的旧 completed 缺报告、封闭能力或人测差异时保留缺失事实和已关闭资格，不重新打开 Task、不伪造报告或过去的人类结论。新命令缺必需能力继续拒绝；旧在途写意图按原身份核对后，才可使用新门禁。

|待实现或未证明的内容|责任角色|受影响入口及复核点|
|---|---|---|
|当前身份/委托/报告访问、完整事实投影和逐动作权限|身份与 Task 领域负责人|P1.1 完成/取消应用命令；同次权威读取和重投撤权验证前不连接产品入口|
|持久幂等、全库唯一报告、版本/控制/输入及写意图同事务竞争|Task 与数据库负责人|P1.1 验证同键/新键/异摘要、来源拒绝、重复并发完成、完成与取消/输入失效竞争；P3.3 扩展多 Agent 和等待唤醒竞争|
|执行器共享启动锁、持久未启动封闭、整组停止、回执丢失/重启/旧消息覆盖|执行器与恢复负责人|P1.1/P1.3 的新完成和物理释放门禁；P4 扩展故障及恢复，证据缺失保持 writes_unsettled|
|新 Run、模型、普通工具、业务写入、等待续接在 Hub/执行器的实际关闭|工作流、Gateway 和执行器负责人|P1.1/P1.5/P2.1；逐入口核对后才能声称完成/取消后的实时门禁有效|
|最终集成候选、独立验收资产、证据适用性与真实人类反馈|工程集成、验收和指定人类测试者|P2.2/P2.4/P2.5；没有真实人类结论时维持 null 或未验收，不由本脚本填写|
|Task owner/consumer 真实归属、独立对象权限及资源留账|Task、交付、资源与安全负责人|P1 基本归属链和 P2/P3 扩展；共享/独立对象不得误停，物理资源按资源决定另验|
|旧记录能力盘点、报告缺失与在途写兼容核对|数据库、领域与恢复负责人|首次采用新业务 API/执行器前逐项复核 D02 §12.5；不改写历史 InputSet 或追认旧通过结论|

本次决定和类型检查允许继续 P0 集成及出口评审，不构成 P0 整体退出、P1 开放、产品功能完成、真实部署或人工验收通过的证据。
