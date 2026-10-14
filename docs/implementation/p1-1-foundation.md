# P1.1 Hub 身份、原子命令与 Task 基础

日期：2026-10-15（Asia/Shanghai）。本说明细化 [PROJECT_PLAN.md 的 P1.1](../../PROJECT_PLAN.md#p11-项目身份授权task命令和幂等基础)，不重新定义领域规则。权威输入为 [D01](../design/01-domain-collaboration.md)、[D02](../design/02-execution-recovery.md)、[D05](../design/05-security-sync-operations.md) 与 P0 的[身份决定](../decisions/p0/identity-permissions-migrations.md)、[Task 决定](../decisions/p0/task-control.md)、[迁移决定](../decisions/p0/migration-contract.md)。

## 1. 本轮行为边界

P1.1 建立真实 PostgreSQL 业务存储、认证与项目授权、原子命令交接、Task 控制，以及分别运行的 Hub API 和单个 DBOS worker。开发运行及定向验证在 WSL 隔离环境进行。s2413 的实际安装、TLS/机器身份、磁盘与执行配额由所属工作包取得独立证据；本说明不把此前的受控方案当成已生效配置。

Task 创建和启动能够保存声明范围、初始工作项与稳定推进身份。首个有界工作流检查当前授权、Task 控制和输入资格；P1.2/P2 尚未实现的构建或 Agent 运行能力须保存准确阻断，不生成模拟交付、模型输出、accepted 工作项或完成报告。P1.1 不调用收费模型，也不开放执行器或部署旁路。

完成成功必须消费所属模块提供的完整持久事实。HTTP 客户端不能提交 `required_work_items_accepted`、`evidence_current`、物理停止或人测通过等可信布尔值。普通 Task 缺少最终候选、固定输入、独立验收或必需工作项结论时，完成请求返回具体 409 阻断。

本轮正向完成与并发验证允许在专用隔离库装入受控合成事实，用于验证真实数据库、命令和报告事务；这些事实不构成产品开发、独立验收、人类结论或执行器停止证据。后续工程/执行器适配接入前，缺少来源的事实入口保持关闭。

## 2. 共享事务与职责

- 应用命令处理器持有唯一短事务，各领域服务消费相同 SQLAlchemy Connection，不自行提交。
- 当前认证、项目归属和逐动作权限先于命令结果回读。撤销、成员/委托变化与命令读取通过同一锁定顺序串行化。
- 去重作用域包含真实主体、委托人、项目、资源和幂等键；请求摘要显式复用 P0 的固定 schema/JCS 规则，不能相信客户端摘要或授权信封。
- 业务状态、命令结果、EventLog、必要 Outbox、WorkflowBinding 与 `DBOSClient.enqueue_in_transaction` 共用同一 PostgreSQL 事务。DBOS 只管理执行状态，不产生第二份权威 Task 状态。
- workflow 参数和返回结果只包含有界标识/引用，数据库认证材料和用户正文不进入检查点；原始 SDK 管理入口不映射到公共 API。
- 完成、取消、输入失效和相关写意图共用 Task 条件更新边界；已完成新键先返回唯一报告，同键返回原持久结果，均重新核对当前读取权限。
- 取消意图关闭普通推进；物理执行未知仍保持阻塞。受限查询、核对与归档沿原身份追加事实，不启动新意图、不改写唯一完成报告、不释放资源账本。

P0 历史契约和 InputSet 不原地改写。产品身份授权接口只检查当前访问，不调用会预先检查业务期望版本的 P0 `check_command()` 新命令分支；版本检查由领域命令在规定顺序内执行。

### 2.1 首次身份与项目引导

本轮选用受控本机维护 CLI 创建真实用户、项目归属与限时 DeviceSession。会话凭据使用 256-bit 随机 opaque bearer；数据库只保存摘要、期限及撤销状态，原材料仅交付到权限受限的本地文件，CLI 输出只含标识和结果分类。公共请求不接受自报 caller、角色、当前权限或委托成立字段，也不存在默认万能管理员。

首个项目由维护入口显式指定所有者并保存审计。现有项目所有者不能因此取得其他项目的创建或管理权；本轮不新增 `system project.create` 动作，不改变 P0 动作枚举。已有项目管理、成员与撤销、查询及 Task 命令通过当前逐动作授权。Desktop 登录体验和 OS 凭据存储在其工作包交付，此处不建立普通客户端秘密缓存。

已经可靠接受的原命令不因 DeviceSession 到期或注销而自动取消。worker 通过持久命令和审计恢复原真实主体，仍须重新检查用户启用、当前项目/角色/委托权限与 Task 门禁；会话只是该命令的审计来源，不充当长期 Task 的执行租约。新 HTTP 请求总是检查当前会话有效性；用户禁用、角色或委托撤销继续阻止新的业务副作用。显式 Task 取消仍通过自己的控制命令进行。

身份和业务写入统一锁序为：相关 User 按 ID 排序、HTTP DeviceSession、ProjectPolicy、业务聚合、命令去重槽。Task 可以先只读不可变项目归属定位身份锁，但取得授权锁后必须重读并锁定 Task。角色/委托变更同样锁定 ProjectPolicy；涉及额外用户时先锁 User，避免锁序反转。

### 2.2 DBOS 初始化与运行边界

固定使用 P0 已锁定的 DBOS 3.2.0。公开 `DBOS.migrate(system_database_url, schema=..., application_role=...)` 由独立维护入口执行；先取得本平台维护锁，并在无法取得时明确拒绝。不能依赖 SDK 内置锁的等待超时行为作为互斥证明。

运行 worker 采用 `run_migrations=False`，再核对业务维护记录中的 SDK、业务迁移和工作流应用基线；缺失或跨版本基线拒绝启动，不只依赖 SDK 的向前 schema 检查。业务 Alembic 不写 DBOS 内部表。API 与 worker 使用受限运行角色，维护权限不交给服务；公开初始化授权后按实际运行需要收窄权限。

API 的 DBOSClient 复用业务 Engine，关闭其 LISTEN/NOTIFY，不为每次 HTTP 请求建池。worker 保留 SDK 支持的 LISTEN/NOTIFY；该监听使用池外的独立连接，必须加到连接预算。具体池上限、数据库角色连接上限与最终模块接口在实现核对时记录，不能把配置值写成容量实测。

### 2.3 首批实现接口

业务 schema 固定 `cloudhelm`，系统 schema 固定 `dbos`；工作流应用名为 `cloudhelm-hub`。首个开发源码与工作流应用分别登记 `0.1.0`，数值相同不表示二者永远共用版本，也不产生已发布软件、tag 或 Release。业务首迁移拥有独立 Alembic revision。

|归属|接口或职责|
|---|---|
|`database/metadata.py`|唯一 `metadata: MetaData`；身份、项目、Task 和共享交接表导入同一对象|
|`database/uow.py`|`UnitOfWork(engine)` 提供 `connection` 与 context manager，只有外层提交/回滚|
|`database/commands.py`|`lock_and_get(connection, envelope)` 串行化完整作用域并读取原结果；`save_result(connection, envelope, result, status_code=..., authorization=...)` 保存已校验有界结果和同次授权审计引用|
|`modules/sync/`|在当前连接写不可变 `event_log` 和待交接 `outbox`；尚未投递不写成已送达，后续 Desktop 调度游标另行实现|
|`modules/workflow/`|版本常量、不可变绑定和公开同事务入队薄适配；不含领域业务过程|
|`modules/collaboration/`|`collaboration.task_initial.v1` 和 `collaboration.task_control.v1`；只接收稳定命令身份等有界引用，从业务存储重新取得当前门禁|

身份入口为 `authenticate_current(uow, bearer)`、`authorize_current(uow, actor, resource, action)` 和仅供受信任 worker 的 `actor_for_command(uow, command_id)`。前者把秘密材料解析为服务端内部身份；授权仅返回本次决策与审计关联，不能当作后续可复用许可。`resource` 来自领域权威行，公共 JSON 不得自行构造这些内部对象。

Task 的 `records.py` 仅供受信任适配登记已核验来源，保存不可变引用与本 Task 消费所需的有界元数据；不开放公共事实写入 API。事实投影通过 SQL 核对 Task 自身工作项、等待、输入有效性、完整证据及 Operation 关联，缺少任何必需登记即阻断。Operation 观测仅追加原身份的有来源回执，不建立可独立修改的执行状态机；冲突、未知或缺少覆盖证明不能因较晚时间戳而升级成已停止/成功。后续 integration/execution 仍拥有各自权威事实与真实适配。

登记引用时，受控来源的有界 UTF-8 元数据必须通过严格 schema/重复键检查，与登记对象逐字段相同，其实际字节 SHA-256 必须等于引用摘要。不能用无关文件的摘要给另一份通过结论背书。操作证据另绑定原 Operation、attempt、步骤集合、执行器/代次、输入及闭合声明摘要；新观测只有通过明确 `supersedes` 与核对证据链才能形成唯一 head，多头、断链或未知继续阻断。

命令唯一键对空委托人采用 PostgreSQL `NULLS NOT DISTINCT`；普通含 NULL 的唯一约束不能保证人类命令去重。并发作用域锁不替代最终持久唯一约束。授权后的领域拒绝可以保存原结果；技术失败必须使命令、领域写入与入队全部回滚。

初始开发池预算为每个 API 普通池 2、控制池 1，单 worker 业务普通池 2、控制池 1、DBOS 系统池 4、独立监听连接 1，全部连接池 `max_overflow=0`。两个 API 与单 worker 最多计 14 条应用连接，维护和诊断另计；配置连接、语句、锁及池等待上限。此为待实际核验的开发配置，取消/核对使用独立控制池，不当作 P6 容量结论。

## 3. 验证与证据计划

|对应子项|必要方法|结论边界|
|---|---|---|
|P1.1-01 数据库/服务|真实业务 Alembic 首迁移和公开 DBOS 同版初始化；运行角色 DDL/越权拒绝；有界连接池；两个 API 实例不产生 worker；单 worker 统一注册|证明本轮 WSL 配置和启动职责，不证明 s2413 部署、容量或多 worker 高可用|
|P1.1-01 身份/项目|缺失/过期/撤销认证、跨项目、角色动作上界、委托范围；已成功命令在撤权后也不得回读|证明当前动作授权和本轮身份来源，不能用角色名或前端隐藏代替|
|P1.1-02 原子命令|在业务写、事件、Outbox、绑定和事务入队处定向注入失败；全部回滚；提交后丢回执、同键重投和异摘要冲突|证明同一 PostgreSQL 事务，不能扩写为文件系统或远端 exactly-once|
|P1.1-03 完成|允许/拒绝来源；同键/新键；缺证据与 unknown 写阻断；唯一报告；并发完成、取消和输入失效|正向完成的合成事实仅证明控制协议，真实产品验收能力随 P2 接入|
|P1.1-03 取消与封闭|可靠取消意图、独立受限核对、未知物理执行不转终态；晚到事实不恢复普通推进；报告不可变|不把 DBOS 取消或停止请求当作物理停止，不涉及资源实际释放|
|最终集成|实际 HTTP 与 DBOS worker、结构/契约一致性、UTF-8/链接/差异检查、固定输入摘要和 dev 对应 CI|结论绑定最终源码、方法与环境；不重复未变化的历史接缝或收费实验|

实际结果、命令、UTC 时间、固定输入与限制写入 `docs/acceptance/p1/` 和 [PROJECT_PROGRESS.md](../../PROJECT_PROGRESS.md)。本表是待执行方法，不是通过记录。用户未提供人类产品验收结论，本轮不会代填。

最终验证按数据库基础、身份/HTTP、Task 事务与并发、API/worker 生命周期分组。每组消费同一隔离数据库夹具或明确独立的运行窗口，记录各自固定方法和真实结果；临时认证材料仅留在私有运行目录。Task 的正向完成输入明确标记为受控合成事实，实际事务、权限和 HTTP/worker 交接仍使用产品实现。候选源码固定后再绑定公开输入与最终结果，出现代码修正时更新相应输入，不继承已经失去适用性的通过结论。
