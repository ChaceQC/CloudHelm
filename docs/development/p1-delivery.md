# 归档 Release、环境配置与部署计划

当前源码为 `0.10.0`，DBOS 工作流应用为 `cloudhelm-hub/0.7.0`，新隔离库的线性业务迁移为
`0011_p1_archive_maintenance`（前驱 `0010_p1_archive_closeout`）。使用 [Hub 开发入口](p1-hub.md)
准备 WSL 锁定环境和独立数据库角色；`initialize` 不升级旧安装。

## 1. 当前支持范围

支持固定便签项目的 Linux amd64 归档交付编制：不可变 Release、环境绑定与配置修订、完整的有限步骤计划、
人类摘要批准、事务入队、查询及启动前复核。归档 SHA-256、OCI manifest digest、config digest/image ID
分别记录；计划以安装标识派生的命名空间及服务专属本地标签启动，固定 `pull: never`、禁止 build。

`reference-notes-archive-linux-amd64-r1` 是独立的交付配方。它消费现有构建的三个固定归档，保留原 BuildDefinition、
工具链、Compose/Descriptor/迁移及配置 schema 来源，另生成交付运行契约；原本地制品验证模板及其
`deployment_entry_enabled: false` 不改写、不当作远程部署开关。

工作流保留可靠暂存；P1.4-02 新增主动认证通道、目标持久账本、逐步骤许可及固定物理适配，见
[Remote Agent 说明](p1-remote-agent.md)。默认普通入口因缺少适用时钟证明保持关闭。
批准、预检、方法合成输入或单个真实数据库容器不表示完整部署成功；当前不提供产品安装包。

归档总时限与原结果补报的 `0.8.2` 修复见 [Remote Agent 说明](p1-remote-agent.md)，
P1 的逐项出口、缺失证据及 P2 入口裁决见 [出口核对](../acceptance/p1/exit-review.md)。

## 2. Release 的前提

`POST /api/projects/{project_id}/releases` 要求 `project.manage` 和 `Idempotency-Key`，请求包含：

|字段|来源与检查|
|---|---|
|`build_operation_id`|现有成功 BuildRun；内容核验和实际构建观察均仍适用|
|`variant_digest`|`modules.delivery.release_recipe.variant_digest(record)`；固定构建定义及交付配方，不允许运行配置更换编译变体|
|`verification_refs`|已登记、当前适用的独立验证证据；覆盖验收资产要求，禁止将 `protocol_validation` 来源用于产品 Release|
|`verification_configuration`|实际制品运行验证所用配置，只允许声明参数及不可变 secret 版本引用；随证据保存，不作为其它环境默认值|

独立 integration 来源按现有受控事实入口登记 `EvidenceMetadata`，主体仍是 Task 当前 Candidate。
其中至少一条通过证据的 `check_ids` 包含 `artifact_runtime`，`fact_digest` 必须等于
`runtime_verification_digest(record, artifacts, verification_configuration)`。该摘要固定原 BuildRun/Operation、
构建输入、三个实际归档及镜像身份、交付运行契约和测试配置；仅构建/加载成功不足以伪造运行验证。
证据的输入集、候选来源 commit、验收资产与当前适用链接须一致。所选人工测试仍按原政策核对，Agent 不提交人类结论。
受控来源负责实际运行方法与事实，公开 API 没有证据写入或“passed”开关。

未取得这些实际证据时，Release 创建返回具体阻塞原因；不得用本轮定向检查的合成输入充当产品证据。
Release 保存后不可修改，后续环境配置不改变其归档或镜像身份。

## 3. 环境、配置与计划

所有下列路径均以 `/api/projects/{project_id}` 为前缀，写命令要求 `Idempotency-Key`。

|方法与路径|用途|
|---|---|
|`POST /environments`|在已由维护入口登记的目标/安装上建立逻辑环境，返回 `binding_id`|
|`GET /environments/{binding_id}`|查询稳定绑定、命名空间、期望/配置修订、active Operation、最近观察及起始状态摘要|
|`POST /environments/{binding_id}/configurations`|创建配置，检查 `expected_config_revision`，不覆盖旧修订|
|`GET /environment-configurations/{config_id}`|查询独立配置修订|
|`POST /environments/{binding_id}/deployment-plans`|绑定 Release、配置及目标起始状态，创建不可变计划|
|`GET /deployment-plans/{plan_id}`|查询完整计划、批准、Operation 和明确的业务等待状态|
|`POST /deployment-plans/{plan_id}/approvals`|人类批准准确 `plan_digest` 和有效期限|
|`POST /deployment-plans/{plan_id}/preflight`|重新读取当前事实，不缓存先前的“可启动”结论|
|`POST /deployment-plans/{plan_id}/closeout`|当前有权人类核对原计划及执行器收尾回执，追加唯一收尾事实；不代表部署成功|
|`GET /releases/{release_id}`|查询完整不可变 Manifest|

Release、环境、配置和计划编制要求 `project.manage`；查询要求 `resource.read`。
批准要求当前设备会话的人类持有 `deployment.approve`。按照 D04，项目所有者可自批；新增
`deployment_approver` 角色只能在显式授予的 `resource.read` / `deployment.approve` 范围内行动。
developer/reviewer 的原动作上限和 Agent 委托不增加批准权限。

首次安装在进入运行前中断时，维护人员可按 [Remote Agent 收尾入口](p1-remote-agent.md#21-首次安装进入运行前的原身份收尾)
先永久封闭原 Operation 并上传停止/残留回执。查询状态 `closeout_pending` 表示 Hub 已收到回执，原绑定仍占用；
当前具有 `deployment.approve` 的已认证人类随后向 `/deployment-plans/{plan_id}/closeout` 提交 `Idempotency-Key` 和正文：

```json
{
  "plan_digest": "sha256:<原计划的64位摘要>",
  "receipt_digest": "sha256:<维护命令输出的64位回执摘要>"
}
```

准确摘要必须取自原计划与固定回执，示例中的占位值不能直接发送。成功返回 `closed / deployment_closed_retained`，
表示原身份已收尾且磁盘继续占账；原步骤 unknown 保留，不能显示为部署成功。同键返回原命令结果，新键返回同一收尾对象并保留新的命令回执，
不会重复领域事件；其他安装、错误摘要或后续运行步骤均不能利用此入口释放占用。后续新部署仍须重新固定计划、批准及当前时间/代次。

### 3.1 独立恢复副本的受限维护

源码 `0.10.0` 增加固定 `0008_p1_4_remote` 快照的维护升级，不改变 `initialize` 的新安装语义。
仅在已授权的独立恢复副本、旧控制面静止、新数据库访问凭据和固定快照/隔离证据下使用；具体边界见
[C08/C09 约定](../implementation/p1-current-delivery.md#21-本轮有限维护入口)。维护角色直接登录，凭据仍由
`CLOUDHELM_MIGRATOR_DATABASE_URL_FILE` 指向的私有文件提供，不放进命令参数。

```bash
python -B -m database.manage prepare-archive-closeout \
  --expected-installation-id ORIGINAL_HUB_INSTALLATION_ID \
  --operation-id ORIGINAL_OPERATION_ID \
  --snapshot-digest sha256:SNAPSHOT_DIGEST \
  --isolation-evidence-digest sha256:ISOLATION_EVIDENCE_DIGEST
```

命令先持久关闭普通推进，再沿线性迁移至 `0011_p1_archive_maintenance`，固定唯一来源和原 project/plan/binding。
同一输入可续接，来源或身份变化拒绝。成功状态仍为 `recovery_required`，不调用 DBOS.launch/migrate，
不自动恢复旧工作流、普通 API 或许可。升级成功不表示该副本取得普通运行资格。

在同一维护范围内，本机 CLI 可以为项目既有且当前具有 `deployment.approve` 的活跃用户签发当前会话，
以及认证接收原 C07 回执；只从当前 UID 所有、非符号链接、无 group/other 权限的文件读取凭据和请求：

```bash
python -B -m database.archive_closeout issue-session \
  --operation-id ORIGINAL_OPERATION_ID --user-id EXISTING_USER_ID \
  --credential-file /private/current-human-session
python -B -m database.archive_closeout receive-receipt \
  --operation-id ORIGINAL_OPERATION_ID --token-file /private/current-remote-token \
  --receipt-file /private/original-closeout-receipt.json
```

签发会话或接收回执不表示人类已确认收尾。准确计划和回执摘要经当前人类确认后，使用前述 JSON 正文的受限文件提交：

```bash
python -B -m database.archive_closeout close \
  --operation-id ORIGINAL_OPERATION_ID --bearer-file /private/current-human-session \
  --request-file /private/confirmed-closeout-request.json --idempotency-key CURRENT_REQUEST_KEY
```

此入口复用普通收尾的身份、权限、幂等、领域事实和唯一事件，不能执行其他交付命令或新步骤许可。
DeviceSession 沿用现有结构；维护库开放普通运行前须撤销或明确处理该维护会话。原 unknown 与完整磁盘占账继续保留，
下一次部署仍须当前目标/时间/代次和准确新摘要批准。任意旧库、损坏账本、迁移/服务已开始和完整 P4 恢复不在此入口支持范围。

配置的 `configuration` 使用现有 `ComposeEnvironmentConfig`：

```json
{
  "config_revision_id": "notes-test-config-1",
  "parameters": {"NGINX_WORKER_PROCESSES": "1"},
  "secret_refs": {
    "DATABASE_URL": "secret://test/database-url@v1",
    "POSTGRES_PASSWORD": "secret://test/postgres-password@v1"
  }
}
```

当前运行参数只支持 `NGINX_WORKER_PROCESSES` 的 `1` / `2`；参数与 secret 集合必须完全匹配。
资源需求单独使用 `ResourceVector`，CPU、内存、磁盘及 PID 必须为正且不超过已登记目标上限。
参数化不能改镜像、命令、服务、端口、卷和网络。秘密不会由 Hub 解析器读取，只保留 `secret://...@vN` 引用。

计划请求固定配置 ID、`expected_environment_revision`、`expected_state_digest` 和 `start_before`。
期限必须在未来 24 小时内。计划同时保存完整规范化规格、解析器修订、目标/安装/执行器及代次、实际服务向量、
数据库前置修订、配置/资源/secret 引用、停机范围、逐步骤输入/前后置摘要、最大时长、30 秒健康窗口及失败核对策略。
目标登记显式声明 `oci_config` / `oci_manifest` 镜像身份模式；实际服务向量分别保存 manifest、config 与 loaded image ID，不能混用 Docker 29 containerd 的身份。
五个步骤依次为归档准备、运行输入检查、数据库迁移、服务更新、健康验证；迁移仅允许固定制品内的
`alembic upgrade 0002_add_updated_at_index`，不开放任意宿主命令。未知结果沿原 Operation 查询，禁止自动回滚。

## 4. 可信事实、批准与启动边界

`modules.delivery.target_facts` 的 `TargetFactProducer` 只由受信 composition root 注入。
维护角色用 `collect_target_registration` / `register_target` 登记目标；受信采集器在事务外查询实际账本，
用 `collect_target_observation` / `register_observation` 写入不可变观察。API 角色不能写目标观察；公开请求不能提交
“目标为空”“状态已核对”或能力声明。P1.4-02 只接受受认证的目标账本事实，不以本机 Docker 或手写假成功替代。

编制、批准和预检都要求与绑定一致且最近 60 秒内的已核对观察。首次安装必须证明没有服务、数据库修订或未登记资源；
缺少历史 Release 不作为空目标证明。观察中的 secret 版本可用集合必须覆盖配置引用，执行器支持全部具名步骤。
观察时间不进入起始状态摘要；任何安全相关的服务/数据库/配置/环境修订变化要求重新制订并批准计划。

批准固定人类、计划/目标/配置/secret、策略/授权修订及期限；批准、命令结果、事件、Outbox、WorkflowBinding 和
DBOS 入队使用同一个数据库事务。重复请求返回原结果，异摘要同键拒绝，不新建 Operation。
预检重新核对原批准人权限与原设备凭据、当前策略、目标事实及期限，`grants_start_permission` 始终为 `false`。

创建配置/计划/批准不会推进期望环境修订。内部 `begin_deployment` 在 P1.4-02 取得目标执行权后、首次普通副作用前
再次复核，并以 CAS 登记唯一新期望修订和 active Operation；重复同一 Operation 不再递增。
执行未知时保留 active 绑定，没有公开的强制清除入口。A→B 已占执行权后，基于 A 的另一计划不能继续执行。
该登记不发出步骤许可，也不证明目标已经发生变化。

当前仅能根据已知归档字节做容量必要检查。计划明确要求目标在加载前核验镜像及临时解包的并存空间，并在配置总磁盘
硬限内执行；不以固定倍数猜测解包大小，也不宣称静态计划已完成真实资源准入。

## 5. 定向检查与支持限制

HTTP 快照入口沿用 [日常检查](checks.md)。本轮一次方法在隔离 PostgreSQL 中使用合成的构建/目标生产者输入，
验证真实持久化、同制品双配置、拒绝分支、授权、批准事务入队和原身份去重。实际方法及结果见
[P1.4-01 进度](../../PROJECT_PROGRESS.md#2026-10-25p14-01-release环境配置与部署计划)。
该结果不表示真实归档运行验证、Remote Agent、独立机器、许可时间协议或人类产品验收通过。
