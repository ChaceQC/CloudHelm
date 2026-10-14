# P0-G02a 固定参照与首链适用决定 r1

日期：2026-10-15（Asia/Shanghai）。方法修订：`p0-reference-applicability-r1`。依据 [D04 §1.1～2、§3～8](../../design/04-release-deployment.md)、[D03 §4.2～4.4](../../design/03-workspace-build-resources.md)、[首链规格](../../implementation/reference-chain.md) 和 [P0-G02a](../../../PROJECT_PLAN.md)。本决定消费 `p0-decisions-r1`，不修改历史实验协议、参照候选或 InputSet，也不开放 P1。

结论：固定参照适合作为首链的源码、构建和独立方法输入；**原开发 Compose 拒绝直接进入产品部署入口**。P0 冻结本文件的保留、编译和拒绝边界；P1.2/P1.3 才实现受控编译，P1.4 才形成经批准的完整计划并取得实际交付证据。不能删除资源、只读、网络或超时字段后将旧解析器接受的另一个输入称为参照已支持。

## 1. 固定输入与来源

|对象|本次核验依据|适用范围|
|---|---|---|
|历史来源|本机历史 Git 仓库的 `3293a09c2501ee5bace398c6214dfcb7016c0824`，子树 `examples/sample-repo-python` / `b765b5f8ee988cd1d95f8a45dd6960597d047573`|只复用 FastAPI 存活/指标语义；React、PostgreSQL、Alembic 与便签业务是后续新增，不能归给该历史切片|
|当前固定参照|[reference InputSet r1](../../acceptance/reference/input-set-r1.json)，source commit `6dd8b605a5cc4b7b641cc0f9b4f2633614c6e757`，36 个源码、锁、需求和独立方法文件|核对工作树和该 commit 的各 blob 均符合原 SHA-256；没有重新冻结或替换原候选|
|InputSet 文件|SHA-256 `119053f06e8adb7f56a19b1c7622e5f9249f40697029a6a3c673f7ebc88e43d0`|方法先核对清单本身，清单改变即拒绝，不能用新清单掩盖旧输入变化|
|开发 Compose|[compose.yaml](../../../examples/standalone-project/compose.yaml)，SHA-256 `3a5fcea0d2885144e06e3040b25d0d2c8aa0679dec10f0406657622c483e8132`|三服务 `postgres/backend/frontend`；只作为历史本机参照建设入口|
|旧解析器|[compose_probe.py](../../../scripts/p0/compose_probe.py) 的 `parse_source`，SHA-256 `e3e64ab0b0ded0defc823103286191d415ee09b3d97f8c05a5f26ae744c101b5`|仍是 `cloudhelm.p0.experimental` 的有限实验；本次调用纯解析入口，不调用 Docker CLI 或旧探针的 main|
|历史运行证据|[validation-r1](../../acceptance/reference/validation-r1.md)、[Compose/Remote 接缝](../../acceptance/p0/compose-remote.md)|保留原输入和范围；旧文档中“参照尚不存在”等表述是当时事实，本决定补充当前适用性，不回写历史|

核验历史来源时只读取指定 Git 对象及固定入口，不执行历史代码。该子树有 14 个文件，应用显式 GET 路由只有 `/health`、`/metrics`，运行依赖只有 FastAPI、prometheus-client、Uvicorn；这组观察与固定树身份共同限定来源。历史仓库不可用、对象缺失、清单或任一文件摘要不符时，方法非零退出并保留失败，不能沿用本轮通过。

历史参照记录的 backend/frontend image ID 是当时的运行身份，不能直接填写未来归档 SHA-256 或 Registry manifest digest。本次没有查询当前镜像存续、执行镜像加载或证明可部署。

## 2. 分类含义与完整字段清单

`reuse`（可复用）表示固定语义或标准解析能力可以作为后续输入；不表示原文件已通过旧解析器或 P1 产品验收。`controlled_compile`（受控编译）表示由对应唯一来源、固定制品和明确参数规则生成新的运行契约/计划，取得新输入及证据后才可使用。`reject`（拒绝）表示原值/能力不进入首链目标运行声明，不能静默忽略或降级放行。

下表覆盖原 Compose 的全部映射字段；列表项的固定内容随原文件摘要校验。脚本逐个输出实际路径，复用表中相同规则的字段不会从清单中消失。未列出的字段、任一新增字段或源文件变化均需要新决定及输入，不能靠通配规则扩展支持。

|实际字段路径（`services.` 前缀按表中服务展开）|分类|固定决定与 P1 边界|
|---|---|---|
|`name`|受控编译|开发名称仅作来源；目标 Compose project 从受控 EnvironmentBinding/installation 身份生成并持久保存，不能用用户可改显示名接管资源|
|`services`；`services.postgres/backend/frontend`|可复用|保留恰好三个稳定 service key；Release 包含全部三个制品，不能漏掉数据库或隐式增加服务|
|`volumes`；`volumes.reference_db`|受控编译|空的命名卷声明仍需实际属主、安装命名空间、受控路径、配额、兼容及保留策略；不默认接管同名旧卷|
|`postgres.image`|可复用|保留现有 PostgreSQL 16.13 的固定 manifest digest；归档交付另固定 archive SHA-256、image/config digest 和 linux/amd64，不混用三类摘要|
|`backend.image`；`frontend.image`|受控编译|当前 `p0.2-r1` 标签是可变开发名；只能由 P1.2 的固定 BuildRun/制品身份替换，不能将标签当作不可变摘要|
|`backend.build`；`frontend.build`|受控编译|只在 P1.2 受限构建端消费；目标运行声明和 Remote Agent 一律拒绝 build、源码上传后临时构建及自动 pull|
|`backend.build.context`；`frontend.build.context`|受控编译|分别固定为 backend/frontend 候选目录，校验真实路径与完整上下文摘要；不包含仓库外内容或 `docs/acceptance/` 正式资产|
|`backend.build.args`；`frontend.build.args`|受控编译|显式构建参数进入 build_input/variant，不从 shell 或 dotenv 继承；未知参数拒绝|
|`backend.build.args.PYTHON_BASE_IMAGE`；`frontend.build.args.NODE_IMAGE/NGINX_IMAGE`|受控编译|固定三个已有 digest 及对应工具链；不能回退为 Dockerfile 中未附 digest 的默认标签；修改构建参数产生新变体和证据|
|`postgres.environment`；`backend.environment`|受控编译|原开发映射改由固定配置 schema、参数槽及 secret 版本引用绑定；不将开发值作为未声明的目标默认值|
|`postgres.environment.POSTGRES_DB`|受控编译|首链固定当前数据库逻辑名及目标实例/schema，不开放单字段改名；健康检查中的对应名称也属于同一运行契约，修改时重出契约和证据|
|`postgres.environment.POSTGRES_USER`|受控编译|固定运行、迁移和数据库管理角色边界；不能把示例初始化角色直接当作业务最小权限凭据|
|`postgres.environment.POSTGRES_HOST_AUTH_METHOD`|拒绝|原 `trust` 只属于合成数据的开发环境。目标必须具备受控数据库认证与角色证据；删掉该字段不能证明认证已建立|
|`backend.environment.DATABASE_URL`|受控编译|运行参数按配置 schema 和版本化 secret 引用解析；模型、公开计划和诊断不保存连接串或秘密值。迁移步骤的权限/引用单独绑定，不借应用运行身份取得迁移权|
|`postgres.volumes`|受控编译|当前短语法保留 `/var/lib/postgresql/data` 的持久化目的，编译为明确的受管 named-volume 长语法；未知卷、外部卷、bind 或无配额路径拒绝|
|`postgres.healthcheck`；`backend.healthcheck`|可复用|固定容器内健康语义；不是部署成功或完整业务验收。`pg_isready` 不证明迁移 head，backend `/ready` 仍须数据库/修订实际检查|
|上述两服务的 `healthcheck.test`|可复用|保留本候选固定的 CMD-SHELL/CMD 测试，不推广为可运行任意宿主 shell；固定镜像内执行且受预算限制|
|上述两服务的 `healthcheck.interval/timeout/retries`|可复用|保留各自 2 秒间隔、固定超时和 20 次重试；P1 另外固定服务健康观察窗口，不能将容器首次 healthy 当作业务持续健康|
|三服务的 `mem_limit`|受控编译|保留每个服务的硬上限，完整资源组申请、占账和内存硬限一致；单容器上限不能替代父组硬限|
|三服务的 `cpus`|受控编译|按精确毫核及明确 quota/period 固定，全部子组硬限合计不得超过父级占账；不用 shares 替代配额|
|`backend.dns_opt`|受控编译|首链只选择当前 `timeout:1`、`attempts:1` 的有界声明；目标 DNS 能力与实际故障边界须重新核验。不能删除它后继承旧 readiness 故障耗时证据|
|`backend.depends_on`；`backend.depends_on.postgres`；其 `condition`|受控编译|原 `service_healthy` 依赖编译为固定前后置及步骤顺序；数据库健康和迁移完成分别核对，不让 Compose 代行迁移|
|`frontend.depends_on`；`frontend.depends_on.backend`；其 `condition`|受控编译|原 `service_started` 只表示启动依赖，不提升为 readiness 或部署成功。计划必须另含应用健康检查|
|`backend.read_only`|受控编译|必须保留根文件系统只读；若适配器无法保证则拒绝，不能为了让旧解析器接受而删除|
|`backend.tmpfs`|受控编译|保留 `/tmp` 可写层用途，首链要求显式有界大小并计入组级内存；原无 size 的简写不能原样进入目标声明，不能以可写根盘替代|
|`frontend.ports`|受控编译|保留仅 loopback 接入和容器端口 80。实际宿主端口由受控配置/宿主冲突账本绑定；开发 58080 不自动成为目标授权，不扩为 0.0.0.0|

原 Compose **没有** `networks`、任何服务级 `networks`、`x-cloudhelm` 或其他 `x-*` 扩展，也没有 `restart`、显式 PID/磁盘额度。不存在的字段不能列为当前支持证据：

|缺失/隐含内容|冻结决定|
|---|---|
|隐式 default 网络|拒绝把 Docker 默认桥网络直接当受控隔离。P1 从固定运行契约生成显式项目内部网络，保持 `frontend → backend → postgres` 的必要服务名称解析；数据库和 backend 不发布宿主端口。受控代理仅经获准 loopback 入口访问 frontend，禁止 host 网络和默认外网出站|
|薄扩展与配置 schema|P1.2 建立与 Compose 同一固定输入集的版本化 ProjectDescriptor/配置 schema；运行字段仍唯一归 Compose，Descriptor 仅引用构建目标、独立验收、迁移/兼容、配置和策略。当前不存在扩展，不能伪造已通过旧 `x-cloudhelm` 参数/secret 槽验证|
|完整资源与宿主绑定|必须补齐所有同时存活进程、镜像/归档/临时空间/持久卷/日志、PID、类别槽、冲突键及共享宿主身份；未配置或没有证据的额度维持零可准入|
|重启策略与镜像内行为|无 Compose `restart` 时不擅自添加无限自动重试。backend 启动命令来自固定镜像，frontend 的 HEALTHCHECK 位于固定 Dockerfile/镜像；它们也属于运行契约，不能只看 YAML 就遗漏或随环境替换|

这里选择新的受控目标运行约束，不主张与开发环境无损等价。网络、认证、tmpfs 或其他行为改变必须形成新运行输入、适用性核验和差异报告；无法满足本决定时拒绝，不能由模型临时猜测配置。

## 3. 不能剥离的资源、隔离与网络约束

|固定服务|声明内存硬限|声明 CPU 硬限|
|---|---:|---:|
|postgres|256 MiB|500m|
|backend|512 MiB|750m|
|frontend|128 MiB|250m|
|声明合计|896 MiB|1500m|

896 MiB/1500m 只是源文件中三个容器上限的合计，**不是完整 ResourceRequest、s2413 可分配容量或容量验收**。构建器、迁移进程、受控代理、镜像加载及并存缓冲等开销另计；tmpfs 消耗必须仍在相应内存边界内。没有父组/PID/存储硬限和配额证据时，即使三个容器数值落在设计预算内，也不能准入。

按用户本轮选择，Hub、开发 Runner 和当前交付验证暂时都使用 s2413，一份真实共享宿主预算不能按三个角色重复计算。消费 [资源决定](resources-task-control.md) 的 HostResourcePool/ResourceRequest、稳定 AllocationIdentity、组级硬限与 reserved/active/releasing/orphaned 占账；停止未知、旧磁盘或迁移结果未知均继续占账。数据库卷、归档/镜像及构建残留只有实际回收或连续转记为有界保留后才释放；退出 Compose 或释放队列槽不成立。正式独立目标与另机验收仍由 P1.4 取得，本机/同机结果不代替它。

必须同时保留：backend 只读根和有界 tmpfs、数据库持久卷归属与写入配额、三个服务及全部子进程的父级硬限、明确内部网络、受控 loopback 端口、DNS 故障边界、已获授权的 secret 解析及容器内固定命令。特权、设备、Docker socket、任意宿主 bind、host 网络、外部共享卷/网络、include/extends/profiles/env_file、隐式插值或未知字段继续拒绝。不能通过环境参数改变这些边界；配置展开后必须再次检查。

## 4. 固定制品到运行声明的实现归属

|入口|必须交付的具体结果|退出前必须证明|
|---|---|---|
|P1.2-01～02 受限构建|固定 SOURCE_COMMIT、两个构建上下文、锁/基础镜像/构建参数、工具链和独立资产引用；生成两个应用制品及数据库依赖制品的完整集合，记录 BuildRun、linux/amd64 变体、归档 SHA-256 和 image/config digest|候选不能改独立验收入口；构建不能读取共享 Git 元数据、控制面数据库、长期凭据或 Docker socket；实际制品可核对，不能拿开发标签或旧 image ID 充作新构建结果|
|P1.2 运行契约/薄扩展|固定参数位置/类型/范围、配置 schema、上述不变运行约束及完整迁移引用；将源码 build 与目标 runtime 分离|不能从 Dockerfile 默认值、shell 或未批准文件补参数；前端当前采用同源 `/api/notes`，编译进制品的前端地址等变化必须形成新构建变体|
|P1.3-01～02 两阶段解析与资源|先校验源字段及唯一归属，再以固定制品编译受限运行契约；环境绑定后生成规范化 deployment_spec 和摘要，落实共享池、组限、路径/卷/端口归属|逐项拒绝源表中的不支持/缺失项；配置展开后复查镜像/服务集合/网络/卷/只读/资源。导入报告保留差异及拒绝位置，无法无损映射的配置由有权用户确认，不能静默删字段；目标禁止 build/pull|
|P1.4-01 完整计划|消费 ReleaseManifest、EnvironmentConfigRevision、DeploymentPlanBinding、全部有序 PlanStep、所需迁移/资源/许可引用和批准摘要|不是旧 `make_plan()` 的服务字典。所有跨对象身份、依赖、前后置、起始状态和当前证据齐全，缺项拒绝；人类批准由有权人类作出|
|P1.4-02 实际执行|目标受控加载固定归档，核对获准 image ID、平台、专属标签及运行容器实际身份；按每步新许可执行并查询原结果|标签被改写是漂移，归档 digest 不等于 image ID。实际加载必须属于有权、有副作用边界的步骤，不能藏在只读检查中；三端身份/可信时间、迁移和独立机器证据分别取得|

原 Compose 不包含产品创建 Release、批准计划、资源预留或迁移控制账本的实现。当前 P0.3 模型只核对形状/关联，编译器、持久账本、真实制品加载、安全停止和步骤结果来源仍由上述工作包实现。不得填合成的“已注册/已配置/已批准/已迁移”对象通过这些入口。

## 5. 完整 PlanStep、配置与资源绑定

以下字段直接引用 [delivery_contracts.py](../../../packages/contracts/p0/delivery_contracts.py)、[permit_contracts.py](../../../packages/contracts/p0/permit_contracts.py)、[resource_contracts.py](../../../packages/contracts/p0/resource_contracts.py) 和 [工程引用](../../../packages/contracts/p0/engineering_contracts.py)，不新建平行协议。

1. `ReleaseManifest` 固定 source_ref、build_input_ref、build_run_ref、完整 services、runtime_contract_ref、configuration_schema_ref、migration_refs、verification_refs、acceptance_assets_ref、descriptor_ref、compose_ref、parser_revision、variant_ref。第三方数据库也在 services 中；数据库镜像身份不能授权现有数据目录升级/回退。
2. `EnvironmentConfigRevision` 固定 config_revision_id/environment_id/revision、parameter_set_ref、非空 resource_binding_refs 和仅带版本引用的 secret_refs。实际秘密及其值摘要不进 EngineeringRef；环境配置修订不能替代环境执行状态修订。
3. `DeploymentPlanBinding` 固定 plan_id/plan_digest、operation_id、Release/配置、environment_execution_id、expected_environment_revision_id/expected_observed_state_digest、normalized_spec_ref、input_set_ref、parser_revision、target_installation_id、executor_instance/generation 和 approval_ref。配置 object_id/revision 的映射遵循 [核心边界 §4](core-boundaries.md#4-release配置与完整计划)。
4. 每个 `PlanStep` 固定 step_id、kind/type_revision、input_ref/input_digest、preconditions_digest/postconditions_digest、max_runtime_seconds、stop_mode、result_query_ref、on_failure/compensation_step_id。完整编译器还要验证引用存在、有限无环顺序、补偿目标与已批准输入；一组独立 PlanStep 校验通过不能替代整计划关系校验。
5. `AllocationIdentity` 的 reservation_id/operation_id/resource_group_id/resource_group_digest/host_resource_pool_id/executor_instance_id/hub_incarnation/resource_generation/cpu_period_us/conflict_keys 必须来自同一受控分配。executor_instance_id/resource_generation 分别映射计划及许可的 executor_instance/generation；资源、配置和计划不能各造一份“同名”身份。
6. `PermitBinding` 逐步绑定相同 operation_id/plan_digest/step_id/input_digest、执行器/Hub/代次、environment_execution_id/environment_config_revision_id、当前 expected_environment_revision_id、control_revision/authorization_revision、predecessor_results_digest 和 actual_state_digest。首步核对起始状态，后续步骤消费真实中间状态；原许可不能因新参数、重投或重启获得第二次启动权。

首链选择有界、显式的 `artifact_prepare → runtime_input_check → database_migrate → service_update → health_verify` 依赖；具体实例表按目标真实前置条件编译，最大时长/停止方式沿用 [PlanStep 决定 §4](time-preview-access.md#4-有限-planstep-与运行边界)。`artifact_prepare` 只承担已冻结的准备边界，`runtime_input_check` 保持只读，应用更新前迁移到准确的 `0002_add_updated_at_index`，不能在执行时重新解释动态 head。

其中数据库实例及其认证、受管卷和资源必须已具真实前置证据。原 `depends_on` 不提供这些事实；空数据库 schema 也不表示宿主没有未登记资源。首次目标尚无数据库或固定镜像尚未受控加载时，编译/启动保持拒绝，P1.3/P1.4 必须先明确并取得受控资源/制品准备的实际证据及步骤边界，再建立相应 InputSet/完整计划；不允许将启动数据库、创建角色或 load 藏进只读检查，也不能越过 [迁移决定](migration-contract.md) 的前置条件。已有数据库路径先核对实际 revision/备份/兼容，再迁移、更新应用并观察健康。

迁移的实际 revision、两侧原身份账本、三组固定后置及物理停止证据单独裁决；`pg_isready`、`service_started`、CLI 0、HTTP 202、容器 healthy 和 DBOS 成功均不代替它。失败默认 `stop_and_reconcile`；首链不自动选择补偿，数据库 downgrade/回滚和任意 shell 始终关闭。未知先查询原 Operation，不能用新计划、重试或新资源身份绕过冲突。

## 6. 核验方法与本轮证据

[reference_applicability.py](../../../scripts/p0/reference_applicability.py) 只读固定公共文件和指定本地 Git 对象：先核验历史/当前字节，再对未修改的 Compose 调用原 `parse_source()`。随后对同一字节做字段清点，输出 JSON；不会构造删字段后的可部署对象，不调用 Compose CLI、数据库、SSH、容器或收费模型。JSON 不输出环境变量值、连接串或秘密。

开发命令（WSL Ubuntu-24.04，已有 uv/.venv；`--no-sync` 防止安装或升级依赖，`-B` 不写 bytecode）：

```powershell
wsl.exe -d Ubuntu-24.04 --cd /mnt/e/Project/CloudHelm -- /usr/bin/env PYTHONUTF8=1 /home/cloudhelm/.local/bin/uv run --locked --offline --no-sync python -B -m scripts.p0.reference_applicability --historical-repository "/mnt/d/graduation project"
```

方法固定预期拒绝 `$.services.postgres.mem_limit: unknown or unsupported field`，必须实际观察到此拒绝才通过；这只是原输入遇到的第一个拒绝位置，不表示删除 mem_limit 后其他字段就支持。JSON 的 `result=passed` 只表示字节、历史来源、字段分类及该真实拒绝核验通过；`product_deployment_supported=false`、`compiled_runtime_spec_created=false`、`contract_instances_created=false` 必须保持其明确范围。

本轮开发运行：`2026-10-14T17:16:42Z～2026-10-14T17:16:45Z`，上述命令退出 0，JSON `result=passed`。Python 3.12.13、PyYAML 6.0.3、Pydantic 2.14.1、rfc8785 0.1.4，内核 `6.18.33.2-microsoft-standard-WSL2`；实测 uv 0.11.29，沿用已有环境，未同步依赖。方法 SHA-256 为 `b01b5d4eab55b4fcb39b4d7c55686966b65f405cebe5272549fc122328562023`。

实际结果：36 个参照输入同时匹配工作树和 source commit；历史 commit/14 文件子树、两个路由及依赖边界相符；旧解析器对原字节实际返回上述 mem_limit 拒绝。共清点 **52 个映射字段**，其中可复用 15、受控编译 36、拒绝 1；该数量含容器映射和嵌套字段，不是 52 个功能/测试场景。三个服务内存/CPU 声明合计 896 MiB/1500m，同时输出完整资源请求未成立、网络/扩展缺失和产品部署仍未支持。仅检查了现有契约字段形状，没有构造 Release、资源、许可或批准实例。

主会话随后固定本方法/决定及相关输入的源码 commit、新 InputSet 和最终集成结果；本段开发运行不冒充该后续冻结输入的最终通过。文档回填未改变已运行的方法或固定参照，不重复执行无变化的运行核验。

P0-G02a 的退出范围为本决定及可复核方法。实际运行声明、共享宿主硬配额、认证网络/数据库、归档与完整计划、原生预览和独立机器交付仍按各自 P1/P2 门禁关闭；本文件不单独裁决 P0 统一出口。
