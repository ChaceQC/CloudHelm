# P0.3 核心契约、复用与扩展边界 r1

日期：2026-10-14（Asia/Shanghai）。依据 D01 §5.1～5.2/§8～9、D02 §1.3/§8/§11～12、D04 §1～2/§8.5、D05 §2.2 和 D06 §2/§19.1。本文完成 P0.3-04 的跨域决定，不增加产品服务或授予实际执行权。对应源码在 [契约目录](../../../packages/contracts/p0/README.md)，本轮输入与验证范围由 [出口评审](../../acceptance/p0/exit-review.md) 绑定。

## 1. 修订与实现边界

本轮独立契约修订为 `p0-decisions-r1`，与软件版本、DBOS SDK、工作流应用版本和数据库迁移版本分开。历史 `runtime_contracts.py` 的 `p0-draft-r1`、`remote-plan.schema.json` 及旧 InputSet 不改写，也不通过改号宣称兼容。P1/P2 接入本轮契约时须显式选择修订，核对持久历史、旧客户端及各字段语义；未知修订拒绝，不能静默退回旧协议。

Pydantic 源码是本轮可执行的形状及跨字段校验，导出的 JSON Schema 是其结构快照。跨对象当前权限、真实来源、原子事务、持久唯一约束、时钟真实性和物理执行只能由后续真实实现核验；JSON Schema 通过不表示这些事实成立。`P0*Contracts` 只是用于发布 schema 的模型集合，不是新 API 请求、业务对象或第二套工作流。

所有引用/列表采用有界类型；本轮 Runtime 信封最多 12 个模型请求引用，以及各 8 个工具、等待、交付引用，工程 InputSet 最多 128 个引用，Release 最多 16 个服务。这些是本修订的单信封编码上限，沿用隔离输入量级并保证检查有界，不是产品并发、模型预算或容量承诺。更大信封须新修订并重新核验；P2 的单 Run 时间、金额及实际请求预算另按测量冻结。

## 2. Runtime、提交与等待

选用 [admitted-runtime](admitted-runtime.md) 的 PydanticAI 协议与 DBOS 公共 workflow/step、`DBOSClient.enqueue_in_transaction` 薄适配。默认未经裁剪的 DBOS/PydanticAI 包装不在支持范围；没有第二个持久引擎，也不操作 DBOS 内部表补齐能力。

`RuntimeInput` 固定 Task/Session/Run 身份、预期 Session 版本、Task 控制修订、输入有效性修订以及 ContextPackage、InputSet、已提交历史边界，待处理消息与延期结果可选且必须是对应类型的引用。引用由各业务领域解析；模型凭据及大对象在获准步骤的瞬态内存中按引用取得，不进入工作流参数或异常链。

`TurnResult` 保持 D01 的四种 outcome：`tool_requests`、`waiting_condition`、`submitted`、`continue_required`；前三种必须分别带工具、等待或交付引用，始终保存完整历史增量引用与实际请求身份，重复模型请求身份拒绝。Run 错误/中断由 Run 和可恢复历史边界记录，不另造 Task 终态。

`AcceptedReceipt` 只能表示 `accepted`，query_ref/wait_ref 都指向同一 Operation 的有权查询/等待资源。它是原 tool-call 的持久提交结果，不包含最终执行成功。调用等待工具时另建 `OperationWait`，固定 Session、原 Run、预期版本、WaitCondition 引用及真正依赖的 Operation 集合；一个无关长操作不自动成为所有工作项的屏障。早到或重复的最终事实按原操作身份归档，不能覆盖 accepted 回执。

|对象|固定映射与保持规则|后续实现门禁|
|---|---|---|
|Task|长期业务目标，可有多个过程，不能强制等同一个常驻 DBOS workflow|D01 完成/取消由所属领域唯一裁决|
|AgentSession|跨 Run 保持业务会话和历史；PydanticAI 自己的 run_id 另存关联|P1/P2 短事务及唯一约束保证同 Session 最多一个有效 AgentRun|
|AgentRun|初次创建新 Run/workflow；崩溃恢复保留原 Session/Run/workflow；等待续接保持 Session 并新建 Run/workflow|`RunContinuity` 检查本条身份关系，真实续接仍需当前控制/输入/权限和同事务入队|
|Operation|一个稳定外部意图；重投、查询、接管沿用原身份，新的本机恢复意图另建关联身份|同身份异摘要拒绝；未知结果先查原操作|
|Deployment|Hub 提交/授权/监督/核对流程引用同一计划及 Operation；目标唯一推进物理步骤|监督窗口结束不结束 Deployment、不释放占用|
|WorkflowBinding|业务类型/身份、过程类型、推进修订映射到 workflow_id|不保存可独立修改的调度状态；不把 DBOS SUCCESS 当业务成功|

## 3. 工程引用、输入与证据

`EngineeringRef` 固定 kind/object_id/revision，可带外部 authority。需要内容固定的引用必须有 `sha256:` 摘要和 `digest_algorithm=sha256`；Git commit、镜像身份及归档摘要各在自身对象/修订中表达，不混用成同一标识。Task/Session/Run/Operation/WaitCondition 可以只有版本身份。`secret_version` 只允许资源及不可变版本引用，禁止在这个引用中附实际值或秘密值摘要。

`InputSet` 采用 `rfc8785-reference-set-r1`：每个引用去掉未出现的可选字段，经已锁定 RFC 8785 JCS 编码后按完整 UTF-8 字节排序，再组成 JSON 数组并计算 SHA-256。集合中同一 authority/kind/object_id 只能出现一次；输入顺序不改变摘要，输入修订/内容变化必改变集合。首次固定后不得在重放时重新采集当前工作区而沿用旧 InputSet。

`EvidenceRecord` 保存 subject、InputSet、方法/修订、环境、实际结果、UTC 观察时间和支持范围；`unknown`、`not_run` 均保持独立值。`DependencyLink` 固定生产者、消费者、要求质量与规则修订。`EvidenceApplicability` 另存有效性修订和 valid/needs_review/superseded 结论，不回写历史事实。输入失效必须先推进当前有效性版本，再异步传播；完成、接收结果、形成 Release 和部署启动不能消费尚待分析的旧结论。

本轮文件 InputSet 另使用 Git commit 与逐文件 SHA-256，记录实际源码/决定/方法。它是开发证据的固定输入，不冒充尚未实现的产品 InputSet 存储或 P2 独立验收服务。

## 4. Release、配置与完整计划

`ReleaseManifest` 固定精确来源/构建输入/BuildRun、完整服务制品集合、参数化运行契约、配置 schema、迁移、正式资产与验证、Compose/薄扩展、解析器和构建变体引用；同一 Release 内 service key 唯一。第三方数据库镜像属于完整服务制品，固定镜像不授权数据库目录升级或回退。

`EnvironmentConfigRevision` 单独固定环境、配置修订、实际参数集合、受控资源和 secret 版本引用，不能带明文秘密。`DeploymentPlanBinding` 固定 Release、环境配置、目标起始环境修订/实际状态摘要、解析结果、InputSet、解析器、目标/执行器/代次和批准引用；PlanStep/许可详见 [时间与许可](time-preview-access.md)。环境配置修订不等于目标环境状态修订，普通控制修订也不等于执行器代次。

配置记录的 `config_revision_id` 对应工程引用的 object_id 和许可的 `environment_config_revision_id`；工程引用 revision 使用该记录数字修订的十进制字符串。计划与首步许可使用相同的 `environment_execution_id`、`expected_environment_revision_id` 及实际状态摘要；`check_initial_plan_binding` 校验这些跨契约关系。后续步骤须在相同计划中按真实前序结果取得允许的中间状态修订，不能反复套用首步起始状态。资源契约的 `executor_instance_id`/`resource_generation` 分别映射相同执行器的 `executor_instance`/`generation`，字段名差异不产生新的权威身份。

同制品换运行时参数生成新的环境配置/计划并核对批准适用性，Release 不回写。编译进制品的参数变化生成新构建变体和证据。配置/secret 版本、Release 或批准摘要变化须重新解析及审批；不允许通过可变参数增加服务、替换镜像或改变未声明可变的拓扑/命令。

两阶段解析的来源仍归 D04 §1.1～1.2。现有 [Compose 专项](../../acceptance/p0/compose-remote.md) 只证明实验子集；参照开发 Compose 含 build 等字段，不能直接作为产品部署输入。P1.2/P1.3 必须从受限构建取得固定制品，补齐首链需要的运行字段及拒绝证据。目标侧禁止源码 build；首条交付采用受控归档，不自动 pull。

## 5. 本机应急身份与维护门禁

本轮选择 Linux Unix socket `/run/cloudhelm/emergency/admin.sock`；目录 root:cloudhelm-emergency、0710，socket 同属主/组、0660。配置与独立信任根置于 root 专用的 `/etc/cloudhelm/emergency/`，目录 0700、认证材料 0600。组只决定可接触接口，授权还必须同时验证 `SO_PEERCRED` 的固定 UID 与安装时登记的 Ed25519 挑战签名身份，禁止仅凭组成员、Hub RBAC、Desktop 会话或 Agent 身份启用。

`EmergencyAccessProfile` 固定安装/执行器身份、部署所有者、管理员映射、认证材料版本引用、动作/资源范围、策略和期限。P0 配置上限选择最长 24 小时离线授权窗、单次最长 900 秒；实际安装可更短，由所有者与目标管理员明确确认。它们是待 P4 验证的拒绝边界，不是已实现承诺；没有可信绝对期限依据时，离线新动作拒绝，不能借普通许可映射失信自动取得应急权。目标已知撤销立即拒绝，失联记录撤销待送达及原最迟失效时间，不能自签延长。

本修订的 `enabled` 只能为 `false`，当前不生成任何配置、socket、认证材料或可执行入口。P4 完成身份、时限、重启、撤销与交还验收后，须以显式新契约/应用修订才能启用。初始允许动作范围仅受控重启和恢复到本地已有、身份可信且与当前数据库/配置兼容的制品，保持当前配置及 secret 版本；任意 shell、未知下载、授权修改、凭据轮换、数据库回退和任意迁移不支持。

`MaintenanceGate` 在本地事务中先关闭相同绑定及冲突共享资源的普通准入，再核对旧执行；已接受的旧 grant、更高 generation、重启或换 Hub incarnation 均不能绕过。物理未停止或结果未知时不启动冲突恢复、不释放占用；恢复采用新的关联 Operation。授权到期只阻止新动作，不能自动解除门禁。

`MaintenanceHandback` 绑定同一 maintenance_id、恢复结果摘要、范围、期望代次、当前 Hub incarnation、两个独立确认及核对证据，未知冲突数必须为零。真实交还依 D04 §8.5：Hub 先持久记待交还决定，执行器事务核对并解除，回执丢失查原记录；Hub 确认解除前不恢复准入。结构校验不能验证签名主体或代替双边事务。

## 6. 首批扩展边界与后续冻结

P0 首链选择归档制品交付、受控系统 Git/Docker/Compose、单个 DBOS worker、模型文本及用户函数工具，不启用外部扩展连接。各适配器的首次实现范围如下；选择提供方不表示已开通连接、拥有权限或已测得容量。

|类别|P0 首批决定及数量|权限、版本和容量边界|负责人/启用前复核|
|---|---|---|---|
|Registry|P5 首批限定 GHCR 一家，OCI 镜像；P0/P1 归档首链启用数 0|仅项目绑定的仓库与不可变 digest；Hub 推送、目标拉取身份分离；实际 API/客户端版本、权限及配额在接入前固定，缺失拒绝|交付/适配器负责人，P5.4-01|
|外部 CI|P5 首批限定 GitHub Actions 一家；已有本仓库 CI 不等于产品 CI adapter|仅固定 repository/workflow/revision，读取检查与触发分别授权；提供方 API 版本、并发/等待/结果去重上限在实现前固定|CI/交付负责人，P5.4-01～02|
|通知|P5 首批一个通用 HTTPS webhook 通道类型；具体接收端未配置|受控域名/目标和版本化消息，不发送秘密；发送、渠道接收、人工确认与升级各自记录，重试/超时/配额随连接冻结|运维/通知负责人，P5.2-01～02|
|观测|首链一个平台 HTTP 业务探测实现、独立外部 Hub 存活探测来源；外部观测 adapter 启用数 0|受控 endpoint 与有界响应，独立记录覆盖/恢复窗口；不能以容器 running 或通知送达关闭 Incident|运维/观测负责人，P5.1、P5.4-01～02|

任意新增提供方、更多客户端/系统、跨平台制品、多 worker、跨版本恢复或运行中资源调整均按对应工作包单列适配和验收。新版本/配额尚无证据时保持待锁定，禁止以通用类别名宣称全部兼容。P3.4 首轮前由研究负责人冻结独立实验包和判定职责；P0 只登记责任与门禁，未运行研究实验。
