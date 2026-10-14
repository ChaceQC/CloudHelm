# P0 迁移与结果查询决定 r1

日期：2026-10-14（Asia/Shanghai）。工作包：P0.3-01b；契约修订：`p0-decisions-r1`。权威依据为 [D04 §9.1～9.2](../../design/04-release-deployment.md)，身份、摘要和权限沿用 [身份权限决定](identity-permissions-migrations.md)，步骤许可沿用 [时间与许可决定](time-preview-access.md)。本文件冻结首链实现选择，不修改 D04 的五类查询结果，也不声明真实迁移执行器、持久账本或故障恢复已经验证。

## 1. 首批支持范围

[首条参照链路](../../implementation/reference-chain.md) 固定 PostgreSQL **16.13**、Alembic **1.20.0**。只读核对的候选迁移为 [0001_create_notes](../../../examples/standalone-project/backend/migrations/versions/0001_create_notes.py) → [0002_add_updated_at_index](../../../examples/standalone-project/backend/migrations/versions/0002_add_updated_at_index.py)：前者根修订创建 notes 表，后者以前者为唯一父修订创建普通索引；两者没有 branch_labels 或 depends_on。原文件内的 downgrade 函数保留历史字节，产品入口不授予调用权。本轮没有修改或执行候选迁移。

|项目|本次决定|
|---|---|
|数据库与目标|一个经认证的 PostgreSQL 16.13 实例、一个目标业务 schema；实例 ID 是受控资源引用，不是含凭据的连接串|
|链与方向|完整制品只有单根、单 head、无分叉/合并/跨链依赖的线性 Alembic 链；单次只向一个准确目标 revision upgrade，起点必须为空基线或链上严格前驱|
|首链两条路径|新空目标 `null → 0002_add_updated_at_index`；已有便签基线 `0001_create_notes → 0002_add_updated_at_index`。其他项目/修订须先固定自身制品和适用证据，模型形状合法不开放执行|
|执行步骤|显式 `database_migrate`，在服务更新前执行；适配器仅以固定制品内的受审查入口传入准确目标 revision。开发参照的 `alembic upgrade head` 先在计划编译时解析成固定 head，执行时不再解析动态 head，也不借应用启动自动建表|
|事务与 DDL|`transactional_ddl` / `single_transaction`：本次升级跨越的全部 revision、Alembic version 更新和成功账本记录在同一 PostgreSQL 事务中提交；不能逐 revision 自动提交|
|允许的变更|当前只接受已审查的 `create_table` 和非 concurrent 的 `create_index`。迁移代码、环境入口和制品摘要共同固定；声明 change_kinds 不能替代源码/SQL 和事务能力核验|
|有界执行|单步骤最多 600 秒，锁等待最多 5 秒，单数据库语句最多 300 秒；与许可决定的 `database_migrate` 一致。这些是准入上限，不是已测性能承诺|
|显式拒绝|任意 shell/宿主脚本、未固定代码或不可核验账本、跨数据库、多目标、多 root/head、分支/合并/depends_on、自动 downgrade、破坏数据的 drop/重写、特殊非事务步骤，以及不能在上述边界内完成的长时任务|

普通 PostgreSQL 事务 DDL 包括本参照的建表与普通建索引。`CREATE INDEX CONCURRENTLY`、VACUUM、数据库创建、autocommit block、外部副作用、分批回填或长时间重写不进入首批模式；计划编译时拒绝，不能退化为 shell 或仅给警告后执行。扩大事务能力集合、步骤种类或时长须先给出新决定与独立证据。迁移脚本里存在的未批准 downgrade 路径不可作为失败处理。

## 2. 固定输入、锁与前后置条件

迁移请求固定 `step_id`、已批准 plan digest、控制修订、InputSet digest、数据库实例/schema、迁移制品与逐文件摘要、完整修订链、起始/目标 revision、事务模式、运行预算、备份/兼容证据和后置方法 digest。`MigrationPlan` 是公开请求体；[身份契约](../../../packages/contracts/p0/identity_contracts.py) 的固定 schema/JCS 流程对该请求体及命令上下文计算 `request_digest`，摘要另存 `MigrationBinding`，不把摘要本身纳入自己的哈希输入。secret 只经受控配置引用解析，秘密值及内容散列均不进入这些对象。

执行锁身份固定为 `migration:{database_instance_id}`，粒度为整个实例，不按应用 schema 分开抢锁。Hub 保留该实例的迁移冲突门禁；目标执行器在同一启动临界区检查旧 attempt/grant 已封闭后登记实际尝试，并在用于本次迁移的连接上取得 PostgreSQL session advisory lock。锁键固定取 `UTF8("cloudhelm:migration-lock:v1" + U+0000 + database_instance_id)` 的 SHA-256 前 8 字节，按有符号大端整数解释；所有管理该实例的适配器使用相同算法。不得只用 CLI PID 或队列槽充当执行锁。连接断开可能释放数据库锁，但不自动释放 Hub 的冲突门禁或物理占用。

|检查点|必须满足的事实|
|---|---|
|编译计划|解析固定制品和全部迁移；核验唯一根/head、准确起点/终点、允许 DDL、单事务行为、数据库版本和显式迁移入口；无 shell、后台任务或事务外写入|
|启动前当前检查|当前身份/权限、计划批准/控制修订、输入和配置仍适用；目标实例及实际 schema/revision 与固定基线一致；无冲突执行；资源已预留；取得当前步骤许可并在首次接受窗口内启动|
|备份|已有数据必须提供与本实例和起始 revision 绑定的备份引用、时间、完整性及可恢复性证据。空目标仅在受控检查证明 schema/数据为空且无旧应用使用时允许 `empty_target_verified`；它不是生产数据库的备份豁免|
|兼容|空目标走 `fresh_install`；`0001 → 0002` 要有旧/新应用均兼容新增索引的固定证据，随后更新服务。首链拒绝要求停机或不兼容旧应用的迁移，不据此推导所有未来迁移都应先于服务更新|
|开始记录|首次 DDL 前，执行器持久记录原身份/摘要、attempt、数据库、锁、制品、授权/许可引用与 UTC 开始事实；数据库控制账本也关联相同身份。accepted 仅证明可靠接收|
|成功证据|从目标数据库重新读取 Alembic version，恰好一个实际 head 且等于目标；固定后置方法全部通过；数据库成功记录与 DDL/version 同事务提交，原执行器/物理步骤已停止并能核对|

后置方法固定为三个具名组，并与 `postconditions_digest` 绑定：`schema_integrity` 核对 notes 表的 id/title/body/created_at/updated_at、主键/空值/长度约束及 `ix_notes_updated_at`；`data_integrity` 核对固定输入的数据集合、行数与字段值未丢失或非预期改变（空目标也须实际观察）；`application_probe` 用受控只读会话执行与固定应用契约一致的便签列读取/排序查询，验证类型与结构兼容，不依赖尚未更新的服务已经启动。具体查询嵌入独立固定资产，不接受调用者 SQL。探测只返回有界结论与受控证据引用，不携带业务正文或秘密。后置资产由受控来源固定，候选不能替换断言；CLI 退出码、进程退出、服务存活或 DBOS 成功均不足以代替这三组结果和实际 revision。

本契约不凭布尔值证明事实。P1 适配层须认证数据库实例与执行器，核对制品/方法摘要、证据权限和原身份，确认读取窗口内锁与基线没有漂移，再构造查询对象；客户端不能提交“账本完整”或“检查通过”自行放行。没有实际 revision 的读取结果须保持 `database_revision_observed=false`，不能用空 tuple 假装空库。

## 3. 五类结果与账本完整性

`operation_id + step_id` 标识同一迁移意图；request digest、计划/目标/制品绑定保持不变。attempt 只标识获准的实际尝试，不因超时、断线、worker 重建或回执缺失自动增加。异 Operation、step、摘要、目标或制品的查询结果一律拒绝关联。业务日期使用 Asia/Shanghai，开始、查询、停止及检查记录用带时区的 UTC 时间戳。

执行器账本记录登记/开始事实、物理尝试、许可、停止及原结果引用，并保留身份墓碑；目标数据库在交付适配器控制的独立 schema 中保存迁移控制账本，不让应用运行角色或候选自行改写。其字段至少含原身份/摘要、attempt、目标与制品、起始/目标 revision、开始事实、提交事实和证据引用；成功事实与业务 DDL/Alembic version 在同一数据库事务中写入。已知失败仅在原事务结束后，核对 rollback/实际影响再另事务登记；不能把提交响应丢失写成 rollback 成功。这是 P1 的实现决定，当前参照只有实际 Alembic 修订，没有被追认成已具备该账本。

完整性须同时核对：受控安装及账本 lineage、原操作唯一登记/摘要、尝试序列无缺口、旧启动路径封闭、记录保留无删除、数据库实际 revision 与受控检查、原物理进程和锁的当前归属。恢复旧备份、身份墓碑丢失、数据库不可达、无法证明安装连续性或任一侧有缺口均使完整性不成立。默认禁止自动清理和身份复用，沿用身份决定的保留门禁。Alembic version 是 schema revision 依据，但不单独承担 Operation 去重账本。

|D04 结果|所需证据和后续动作|
|---|---|
|`not_started`|两侧完整账本、数据库实际基线和明确未开始证明共同成立；原进程不存在或已确认停止、锁空闲、数据库未执行。查无记录本身不成立；可进入下一节的原身份重试资格检查|
|`running`|原 attempt 已登记；执行器账本、原操作持有的执行锁、物理进程和数据库可观察运行事实相互一致。仅续查，不能创建第二个尝试|
|`succeeded`|账本/物理事实可核对，实际唯一 head 等于目标，三组固定后置检查全部通过，迁移进程已停止。锁仍由原操作持有时可以核对成功，但资源仍按实际释放证据单独处理|
|`failed_known`|原尝试已停止，失败原因、实际 revision、已发生影响和检查结果均能确定并有引用；未运行的后置项如实为 `not_run`，不填通过。保留原失败，不自动重跑/降级/回滚|
|`unknown`|无法确认真实影响或账本完整性，包括丢回执、记录缺失、无法观察目标/进程/锁。保留原操作和冲突门禁；未知不是失败、成功或未启动|

查询适配器要先收集并核对事实，再产生一份新的查询快照。输入为 `unknown` 的纯校验函数始终返回 `unknown`，即使所填目标 head 相等也不升级结果；只有原身份下新的完整证据支持新的 `succeeded` 等快照，才可解析未知。伪称 `succeeded` 但 head 不匹配、后置缺失或停止未证实的对象拒绝通过。回执丢失时先查询原执行器账本、目标迁移账本和数据库状态；目标已经成功时读取并归档原成功，不因本地末条记录不完整重发 upgrade。

## 4. 取消、超时与重试授权

600 秒总预算计入迁移步骤本身；数据库连接内设置 5 秒 lock_timeout 与 300 秒 statement_timeout，使用剩余总预算限制下一条语句。到期、取消、撤权或许可失信后不启动下一条 DDL，也不开放下一步骤；受控执行器只向已绑定数据库/进程启动时间的原 backend 提出安全取消请求，等待事务回滚或已发生的提交收束，然后查询实际 revision/账本/影响。不能因杀掉 CLI、cancel 请求成功或数据库连接消失就记为已回滚。物理停止或提交未知时保持 `unknown` 和冲突占用，禁止并发新迁移；不以期限届满强制释放。

仅 `not_started` 可以沿原 Operation/step/request digest 申请新的实际尝试。申请时在启动临界区重新读取当前权限、批准、控制修订、固定输入、基线/备份/兼容前提、资源和无冲突事实，并形成唯一 `observation_id` 的当前查询快照；重试 gate 必须引用这份快照，不能取用旧的未启动结果。先持久封闭原 attempt 的全部旧 grant 路径，再取得新的有效许可。`check_migration_retry()` 只核对这些受信任输入，不生成 attempt、不续期 grant、不授权真实执行。调用方须在同一启动锁下校验并登记，不能先释放锁再执行。

已知失败即使数据库已完整 rollback，也不能重命名为 `not_started`。首批模式不开放自动失败重试；有权人类决定修复或恢复后，按新的执行意图、固定实际基线、兼容/备份证据重新生成并审批计划，保留对原失败 Operation 的关联。计划、项目配置、制品摘要或起始数据库状态改变都必须重新解析审批，不能原地改原请求摘要。未知时先核对原操作，不能为绕过阻塞而创建新 Operation。自动 downgrade 和数据库补偿始终关闭；人工备份恢复或向前修复是独立授权流程，不由本纯契约发起。

Task 取消不自动取消 Deployment；需要停止迁移时由有权入口针对原 Operation 发出停止请求。停止确认与结果核对必须由仍可运行的受控 control 路径承接，不依赖已取消的 DBOS 业务流程执行 finally。此决定不引入新的 Task、Deployment 或迁移生命周期。

## 5. 三类 schema 的权威与恢复边界

|边界|本次冻结的支持及执行入口|备份/恢复要求、终态与完整性|
|---|---|---|
|Hub 业务 schema|PostgreSQL 16.13、Alembic 1.20.0；由 Hub 业务工程维护单根单 head 线性修订，受控平台维护入口执行。当前无产品迁移链，不能虚构产品 head 或宣称升级完成；P1 首迁移固定后才加入具体业务版本/schema 矩阵|备份同库的业务与 DBOS 一致基线及所需外部引用，恢复时关闭写入/推进；以业务实际 revision、完整性与领域探测证明，保留平台维护账本的实例/lineage/原身份。不能用交付项目的 notes 后置项验收 Hub|
|DBOS 系统 schema|固定 SDK **3.2.0** 与 PostgreSQL 16.13 的现有接缝组合；只消费 SDK 公开支持的初始化/升级流程。当前可选择同版初始化，不开放任何跨 SDK/系统 schema 版本升级；没有可验证的官方兼容路径就显式拒绝，不由业务 Alembic 写 DBOS 内部表|与同库业务数据形成一致备份；恢复后先保持恢复门禁，核对公开 SDK 结果、工作流身份/检查点连续性及已有业务交接。系统 schema 版本、SDK 和 application_version 分别记录；缺少可受支持核验的记录即 unknown，不靠直接改查内部表拼结果|
|交付项目 schema|本文件 §1 的 PostgreSQL 16.13 / Alembic 1.20.0 首批模式；ProjectDescriptor/Manifest 固定输入，交付模块编译/审批，Remote Agent 消费固定计划。业务应用 schema、Alembic version 与目标控制账本分别按本文件职责维护|按本目标数据库的已验证备份恢复方法；实际目标 revision、三组后置、兼容性和原物理步骤共同定论。两侧账本/安装 lineage 完整性按 §3 核对；不是 Hub 或 DBOS 的迁移流程|

三类都禁止用另一类的版本或通过结论代替自己。Hub/DBOS 恢复不能凭数据库 restore 命令退出码开放推进：旧备份与较新远端执行事实先按原身份核对，再经 D02/P4 恢复门禁。交付项目的数据恢复不能自动回滚 Hub 业务或 DBOS 状态。没有备份可恢复性证据的已有数据变更保持关闭；本契约不会声称已测 RPO/RTO。

## 6. 交付物、检查与仍关闭的入口

[migration_contracts.py](../../../packages/contracts/p0/migration_contracts.py) 提供有界、冻结且拒绝额外字段的纯模型：`MigrationPlan`、`MigrationBinding`、`MigrationRevision`、`MigrationPostcheck`、`MigrationQueryResult`、`MigrationRetryGate`，由 `P0MigrationContracts` 聚合生成 schema。`check_migration_query()` 校验五类结果；`migration_succeeded()` 只接受经检查的成功；`check_migration_retry()` 仅检查可信未启动情况下的新尝试资格。模型最多 64 条修订、每条 8 类变更声明、64 个实际 head、3 组后置结果，不接收连接串、命令文本、SQL、日志正文或任意字典。集中声明式字段和纯判断同文件维护，避免拆出假的数据库/调度实现。

[固定窄检查](../../../scripts/p0/check_decision_migrations.py) 的输入是合成对象，包含五类结果、未知不升级、head/后置缺失、账本缺口、异身份/摘要、非事务/shell/downgrade/破坏变更/分叉拒绝，以及重试门禁。执行入口为 WSL Ubuntu-24.04 的 `/mnt/e/Project/CloudHelm`：`uv run --locked --offline python scripts/p0/check_decision_migrations.py`。检查结果由 PROJECT_PROGRESS.md 和统一出口证据记录；合成检查不构成真实 PostgreSQL 迁移或部署通过。

|仍关闭的入口|责任角色与复核点|
|---|---|
|真实交付迁移和成功查询|数据库/交付/执行器负责人在 P1.3/P1.4 固定实现及 InputSet，核对单事务 DDL/version/成功账本原子提交、唯一锁、真实 revision、受控后置方法和身份/许可链；当前未验证|
|有数据目标、旧/新应用兼容和安全停止|数据库/独立验收负责人在实际目标验证备份恢复、基线/数据保全、600/300/5 秒边界及 backend 定位，绑定明确环境；参照已有 CRUD 结果不替代上述组合，当前未验证|
|回执丢失、取消竞争、锁冲突和人工恢复|交付/执行器负责人于 P4 扩展故障证据；P1 最低查询与原身份核对先建立，未知持续保留，无自动回退；当前未验证|
|Hub 产品迁移与 DBOS 升级/恢复|Hub 数据库及 Runtime 负责人在 P1 固定真实业务修订与同版初始化入口，P4 绑定一致备份/公开 SDK 支持的升级恢复流程；跨版本升级维持拒绝，不能用本文字段或旧接缝代验收|

当前已决定支持集合、身份、锁、查询判据、固定前后置、停止边界与重试条件；未闭合的是上述真实实现和环境证据。P0 统一出口由主会话按 D06 评审，不由这一切片单独放行 P1。
