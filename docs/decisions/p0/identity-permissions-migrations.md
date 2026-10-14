# P0 身份、动作权限与迁移边界决定 r1

日期：2026-10-14（Asia/Shanghai）。工作包：P0.3-01a；契约修订：`p0-decisions-r1`。依据为 [D02 §1.3～1.4](../../design/02-execution-recovery.md)、[D05 §1.1](../../design/05-security-sync-operations.md)、[SDK-01](../../acceptance/p0/SDK-01.md) 和 [A02](../../acceptance/p0/A02.md)。本决定细化首链实现输入，不改变权威专题，也不把 P0 接缝扩写为产品授权、持久去重或跨版本恢复已经实现。

## 1. 身份与连续性

Hub 业务模块拥有业务身份与映射；DBOS 拥有工作流执行状态；执行器拥有实际尝试和具名步骤的本机账本。API/领域模块不复制 DBOS 调度状态，Hub 不以工作流逐步驱动远端计划。框架 run、tool-call、消息 ID 只做关联，不能单凭变化产生业务副作用。

|身份或映射|保持原身份|新建身份或修订的条件|
|---|---|---|
|Task|同一长期目标的各业务过程|独立目标才建立新 Task；完成不由新 Run 隐式撤销|
|AgentSession|同一会话的历史、等待和多个 Run|建立独立业务会话；框架 PydanticAI run_id 单独记录|
|run_id|同一有界 AgentRun 崩溃恢复|等待条件结束后的下一轮推进；同一 Session 至多一个有效 Run|
|WorkflowBinding / workflow_id|同业务对象、过程类型和推进修订的重放|新的推进修订或独立过程；历史绑定保留，不覆盖旧绑定|
|command_id / idempotency_key|同调用者、业务 scope、幂等键且摘要一致的重投|独立业务命令使用新键；同键异摘要返回冲突，不能覆盖原命令|
|operation_id|同一不可变执行意图的提交、同义请求、查询、恢复及接管|执行意图改变；本机恢复意图须独立授权并关联原 Operation，不改写原部署|
|attempt_id|对同一次实际尝试的查询、恢复和重复确认|核对并确认确需新实际尝试后建立；超时或旧 worker 消失不能单独满足|
|operation_id + step_id|同 Operation 同一具名步骤的重复交付|新 Operation 或新的具名步骤；DBOS 内部 step 序号不能替代 step_id|
|grant_id|重投或查询同一许可，保留原接受结果和窗口|原许可过期、原步骤确认未启动，再按当前授权为同 Operation/step 签发新许可|
|event_id|同一业务事实的重复投递|新的业务事实；接收回执与完成事实不能共用结论|
|reservation_id|同分配的交接重试、查询、恢复和 D03 允许的调整|原分配确认结束后的新分配|
|adjustment_id|同一次独立调整的重投、查询和核对|新调整使用新身份及调整摘要，保留 reservation_id 与初始 request_digest|
|Deployment / DeploymentPlan|提交、查询、许可与核对沿用固定计划和原 Operation|改变部署意图时创建新计划/操作并重新审批；监督窗口结束不结束部署|

命令作用域固定为 `(caller.kind, caller.subject_id, caller.delegator_id, project_id, resource_kind, resource_id, idempotency_key)`。Agent 的实际身份与委托人都参与身份，不借机器凭据或人类会话 ID 冒充另一个调用者。target、动作和请求 schema 进入摘要；同 scope/键换 target 或动作必须冲突。新键不保证创建新 Operation：领域模块仍按既有执行意图关联同义请求，不能因框架重建 Run 绕过此规则。

## 2. 规范请求与摘要配置

|配置|首链决定|
|---|---|
|协议 / 摘要配置|`p0-decisions-r1` / `cloudhelm-jcs-sha256-r1`，与旧 `p0-draft-r1` 和实验协议分开|
|请求 schema|路由绑定固定 schema 类和准确修订；客户端不能选择任意 schema 或用声明的修订跳过校验|
|处理顺序|UTF-8 原始 JSON → 拒绝重复键及非法数值 → 固定 schema 校验、物化声明默认值 → 解析并授权不可变引用 → JCS → SHA-256|
|摘要输入|协议/摘要/schema 修订、caller、scope、target、action、expected_resource_revision、规范化请求及统一 EngineeringRef 引用|
|引用|直接复用 EngineeringRef 的 kind/object_id/revision/authority/digest/digest_algorithm；命令允许 artifact、environment_config、input_set、deployment_plan、secret_version 五类。前四类必须带内容 digest 和 sha256 算法；secret_version 只允许版本化身份与 authority，digest/算法均为空，禁止秘密值及其内容散列|
|默认与空值|声明的默认值先物化；schema 允许的显式 null 保留。无默认值的可选成员保留缺省/null 区别，不能统一删 null；映射中的成员缺省也不补为 null|
|序列化|RFC 8785 JCS / UTF-8；对象键按规范排序，数组次序保留；Unicode 不擅自做 NFC/NFKC、大小写或空白归一|
|数值|有限数按 JCS；负零为零；整数限定 `[-9007199254740991, 9007199254740991]`；拒绝重复键、NaN、Infinity、溢出和非法 Unicode|
|精确小数|仅 schema 指定字段接受十进制字符串：禁止指数、正号及多余前导零；去小数尾零/末尾点，负零为 `0`；固定位数有业务意义时另存精度或固定 schema，不全局改写文本|
|摘要输出|`sha256:` + JCS UTF-8 字节的 SHA-256 小写十六进制；复用锁定 `rfc8785==0.1.4`，不新增依赖|

`command_id`、`idempotency_key` 是登记/关联字段，不进入请求摘要。传输时间戳、trace/span、HTTP 连接信息、重投次数、框架 run/tool-call/message ID、worker PID 和授权快照均在传输/审计层，不能混入规范请求。业务有效期、控制修订、真正影响范围的 AgentRun/Operation/输入版本等由该动作的固定请求 schema 明确定义，必须参与摘要；不能把业务期限或控制字段当作瞬态数据丢弃。命令核心模型不接收这些未声明的传输字段。

`request_digest()` 消费固定 `CommandIntent` 和已经校验的 `Contract` 请求体，物化 Pydantic schema 默认值；`parse_request()` 保留原 JSON 成员语义并拒绝重复键。高精度字段由自身 schema 调用 `canonical_decimal()`，引用解析由获授权的适配层先完成。通用 helper 不识别任意字符串是否为秘密，也不接受“已合法”的客户端声明作为证据；P1 每个请求 schema 必须采用公共字段允许清单，拒绝内联秘密及未知字段。`CommandEnvelope.request_digest` 由适配层重算并校对，不能信任客户端提供值。未绑定固定 schema、未解析引用或不能证明公共字段边界的路由保持关闭。

工程引用形状与秘密摘要约束由 [engineering_contracts.py](../../../packages/contracts/p0/engineering_contracts.py) 唯一维护；身份模块只校验上述五类的允许范围，不维护第二个引用类型。引用的 authority、准确版本及允许的摘要字段整体进入命令摘要。本轮是在尚未冻结的 `p0-decisions-r1` 内完成聚合对齐，不改写旧 `p0-draft-r1` 或实验输入。

更改算法、数值约定、默认值或引用规则须提升摘要配置或请求 schema 修订，并走 API/事件能力协商。旧身份和历史摘要不得按新配置重算覆盖；旧 SDK-01 与 A02 输入保持原字节，不追认兼容。

## 3. 去重顺序、保留与清理

接收方在同一受控应用事务内执行下列顺序，业务写入、事件、WorkflowBinding 与 DBOS 入队沿 SDK-01 的同库事务接缝交接：

1. 按当前认证主体、资源归属和该动作策略重新判权。读回既有结果也需要当前访问权；撤权不能借幂等重投泄露结果。
2. 以完整作用域和幂等键原子查询/登记。已有同摘要记录时返回原 command_id、适用 Operation/报告/结果引用，包含尚未完成的原操作；不再次执行业务版本检查或创建副作用。
3. 同键异摘要拒绝 `idempotency_digest_conflict`；查到不属于该作用域的记录拒绝 `idempotency_scope_mismatch`。
4. 只有新命令进入当前对象版本、来源状态、控制修订、有效输入、预算、审批、恢复与资源门禁；版本不符拒绝。之后才执行原子业务交接。
5. 未知结果沿原身份查询和核对。客户端丢回执、accepted、工作流成功或缓存命中都不能替代实际完成证据。

`check_command()` 只校验已提供的主体/范围/动作授权事实、角色上界、幂等摘要和新命令对象版本。它返回 `new` 或 `replay`，不会发放真实权限、执行事务、产生 Operation 或返回业务成功。`AuthorizationEnvelope` 只能由受信任适配层在当前判权后生成；permission/policy/resource 修订、decision_id 和实际审计 session 必须来自同次权威读取，不能接受客户端填写或复用缓存快照。Task 取消后残留控制权、审批独立性、预算/资源等领域门禁仍由对应模块判定。

|保留参数|本次决定值|含义与证据界限|
|---|---|---|
|`dedupe_ttl_seconds`|`null`|不按时间自动失效；不虚构已经测得的最大重投天数|
|`automatic_cleanup`|`false`|首链去重记录、摘要、结果引用和身份墓碑没有自动删除路径；这是实现配置决定，不是数据库运行观测|
|`full_history_ttl_seconds`|`null`|尚未授权按时间清理恢复所需历史；只保存允许的有界结果与引用，不能借保留策略持久化无界上下文|
|身份复用|禁止|即使允许清理大结果正文，身份/原摘要/结果引用墓碑仍需保留，历史清理不得让旧命令成为新命令|

启用清理前，数据库/执行负责人必须在新决定中固定命令可接受期、最大重投期及可信时钟偏差的实际值/来源，并证明保留窗口覆盖三者。还须确认记录已终结、无等待/恢复/去重/审计引用、实际尝试已停止、无 unknown 结果或占用；磁盘实际回收或受控转记遵循资源决定。清理只处理允许字段，不能清 DBOS 内部表替代公开保留接口。记录仍执行、等待、恢复引用存续或停止未知时，无论已过多久均拒绝清理。生产存储预算与可用公共清理接口尚未形成新证据时保持 `automatic_cleanup=false`。

## 4. 首链逐动作权限

以下“当前检查”均包括真实认证主体、资源归属、当前权限/策略与对象版本。角色是动作上界，不能仅凭角色放行；一个人有多个角色时逐动作选择实际获授身份。审计始终保留实际主体而不是让 Agent 代填人类。拒绝码是首链稳定分类，可附受控对象引用，不附秘密或底层异常全文。

|动作|主体|资源范围|当前检查与时机|审计主体与关联|拒绝原因/码|
|---|---|---|---|---|---|
|`resource.read`|获授所有者/开发者/审查者/批准者；委托 Agent|明确项目及固定对象|每次读取检查归属、访问范围、适用版本；附件/日志仍按敏感数据规则|实际用户或 Agent+委托人、session、对象修订|越界或撤权 `permission_denied`；主体/target 不符 `authorization_binding_mismatch`|
|`project.manage`|项目所有者|项目配置、成员职责|每条管理命令入场及写入事务内检查管理权/配置版本|实际所有者、session、项目和命令|非所有者/过期授权/对象变化；`role_action_denied` / `resource_revision_conflict`|
|`task.command`|获授权所有者/开发者；委托 Agent|指定 Task、Session、输入|每次命令及实际后续副作用前重查 Task 资格、控制修订、输入与委托；完成走唯一报告门禁|实际用户或 Agent+委托人、Task/Session/Run/command|已关闭推进、输入失效、委托撤销；`task_not_eligible` / `input_not_current` / `delegation_not_current`|
|`task.cancel`|具有该 Task 取消权的人类或委托 Agent|指定 Task 和控制修订|取消事务内单独检查取消权及当前控制修订；与部署批准分离|实际请求者、委托人、Task、取消命令与修订|无取消权/修订冲突 `cancel_not_authorized` / `control_revision_conflict`|
|`workspace.write`|获授开发者；委托 Agent|指定项目/工作区/Task/InputSet|入场和每项写入前检查写入权、交接状态、路径和当前输入；工具参数合法不代替授权|实际开发者或 Agent+委托人、工作区、Task/输入与操作|写权已交接/越界/输入过期 `workspace_write_denied` / `input_not_current`|
|`candidate.submit`|获授开发者；委托 Agent|固定候选、工作区、InputSet|提交事务核对候选字节/摘要、写收尾、输入及提交权|实际提交者、候选摘要、Task/Run、InputSet|候选或输入变化/在途写未收尾 `candidate_not_current` / `writes_unsettled`|
|`review.submit`|指定人类审查者|审查任务、候选与 InputSet 固定摘要|读取及提交事务重查审查分配、候选、证据适用性|实际审查者、审查任务、摘要与结论|未分配/候选变化/证据失效 `review_not_assigned` / `evidence_not_applicable`；Agent 一律 `role_action_denied`|
|`human_test.enter`|指定人类测试者|HumanTestSession、轮次、候选、InputSet、预览环境|兑换和每次访问检查指定身份/期限/撤销/版本/环境存在|实际测试者、轮次、候选、受限访问 session|未指定/过期/撤销/回收 `test_not_assigned` / `preview_access_denied`|
|`human_test.pass`|指定人类测试者|同轮次、候选、InputSet|反馈事务内重查权限、会话开放、轮次及当前版本|实际测试者、反馈和 UTC 提交时间|反馈关闭/对象不符 `feedback_closed` / `test_binding_mismatch`；Agent 不可代填|
|`human_test.request_changes`|指定人类测试者|同轮次与固定候选|反馈事务内同上；修改意见不直接重开已完成 Task|实际测试者、意见引用、轮次与时间|轮次已变/反馈关闭 `test_binding_mismatch` / `feedback_closed`|
|`human_test.skip`|策略授权的指定人类测试者|特定轮次及人测策略修订|反馈事务核对明确跳过权与适用策略；不能由 Agent 推测“不需要”|实际人类授权者、策略修订、跳过结论与时间|未获跳过权/策略变更 `human_skip_not_authorized` / `policy_not_current`|
|`deployment.approve`|指定人类批准者；个人流程允许所有者自批|固定计划摘要/起始状态/目标环境/候选制品/配置修订|批准事务检查资格与摘要；签发每项许可及实际执行前重查仍有效且目标未漂移|实际批准者、批准记录、计划/目标/影响|团队或重要环境缺独立批准者 `independent_approval_required`；计划变化/过期/撤销 `approval_not_current`；开发者、Agent、机器无此动作|
|`operation.request`|动作资源范围内获授所有者/开发者；委托 Agent|原 Task、输入、工具能力与具体目标|Gateway 每次调用、命令事务和后续副作用前核对委托、Task、预算/资源及所需批准|实际请求者、Agent/委托人、Task/Session/command/Operation|委托越界/取消/预算或审批不足 `delegation_not_current` / `task_not_eligible` / `operation_gate_denied`|
|`operation.query`|获授人类/委托 Agent；绑定执行器|原 Operation 与其结果范围|每次查询重查访问权；取消后不因此新建意图|实际查询者，委托关系或 machine identity，原 Operation|撤权/范围不符 `permission_denied` / `authorization_binding_mismatch`|
|`operation.stop`|拥有该操作受限安全停止权的人类/委托 Agent|原 Operation、协议允许的安全边界|每次请求检查剩余控制权、可停止类别和本机事实；不将请求写成已停止|实际请求者、原 Operation/attempt、停止请求|无剩余控制权/协议不可安全停止 `stop_not_authorized` / `stop_not_supported`|
|`operation.reconcile`|拥有原操作核对权的人类/委托 Agent|原 Operation、后置条件和可信证据|每次核对检查范围和证据来源；核对不自启补偿/迁移/重试|实际核对者、原 attempt、证据引用|证据不足/试图新增副作用 `reconciliation_required` / `new_intent_requires_authorization`|
|`fact.archive`|获授人类/委托 Agent；绑定执行器报告事实|原 Task/Operation 与固定结果引用|入库时校验事实来源/重复事件/当前归档权限；完成后不恢复普通推进|实际提供者、event_id、Task/Operation/attempt|来源不符/重写已知事实 `fact_binding_mismatch` / `fact_conflict`|
|`step.execute`|绑定 machine identity 的执行器|本机 Operation/step/input digest/资源/代次/期限|接收许可、启动前及每个新副作用前核对许可、批准、撤销、计划、时间与本机事实|machine identity 与 grant、批准者、Operation/attempt 分列|无许可/过期/撤销/错机器或摘要/资源越界/缺人批 `step_permit_denied`|
|`emergency.execute`|预配置本机应急管理员|独立 Profile 固定 installation/executor/资源/动作/期限|P4 开放前一律拒绝；以后本机认证及逐动作检查 OS 身份、Profile 完整性、可信时间/撤销和原执行已收束|实际本机人类、installation/executor、Profile ID/revision、动作|当前 `emergency_not_enabled_before_p4`；不得继承 Hub 会话/Agent/机器权限|
|`emergency.handover`|同一预授权本机应急管理员|本机维护门禁与核对后的目标状态|P4 开放前一律拒绝；以后核对原执行、在线重连事实和明确交还授权|实际本机人类、Profile、核对记录和交还记录|当前 `emergency_not_enabled_before_p4`；重启或加代次不能替代交还|

首链另有两个内部边界：步骤许可只能由 Hub 授权链在当前计划/批准/资源/时间检查后签发，审查者或 Agent 的结论不能签发许可；DBOS 管理查询、fork、rewind、强制恢复和历史删除仅向独立授权运维入口开放并单独审计。以上均未作为通用角色的可调用动作加入核心信封，未知 action 在 schema 层拒绝；应用路由不得将它们映射为 `task.command` 等较宽动作。

## 5. 迁移归属与后续接入

三类迁移独立版本化：Hub 业务 schema 由应用 Alembic 线性修订管理；同数据库内 DBOS 系统 schema 由锁定 DBOS SDK 的受支持公开迁移机制管理，不由业务 Alembic 直接改写；用户应用/Release 的目标数据库迁移由交付模块固定计划、Remote Agent 执行并查询数据库实际修订及后置条件。三者版本不能互相代替，DBOS application_version 与执行协议另行管理。首批模式、稳定查询身份、前后置检查、未知结果阻塞及回滚边界以 [migration-contract.md](migration-contract.md) 为 P0.3-01b 的具体决定。

实现负责人及入口：身份/安全负责人在 P1 接入真实认证、委托/权限当前读取与审计；数据库/命令负责人在 P1 以本决定复核同事务唯一登记和清理默认关闭；各领域负责人建立固定公共请求 schema、引用授权和动作门禁；迁移负责人承接 P0.3-01b；应急负责人待 P4 独立验证后才可提议开放。没有真实来源的 AuthorizationEnvelope、未验证的路由 schema 或未知原执行都不能以合成检查放行。

本切片提供 [identity_contracts.py](../../../packages/contracts/p0/identity_contracts.py) 与 [固定窄检查](../../../scripts/p0/check_decision_identity.py)。实际执行结果由 PROJECT_PROGRESS.md 和统一出口证据记录；此处仅定义检查范围：规范化/摘要稳定与变化、同键异摘要、当前权限先于去重、新命令版本冲突、成功重投及 Agent/人类边界。没有新增数据库、模型请求、容器、迁移或产品服务。
