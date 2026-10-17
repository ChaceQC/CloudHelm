# P1.2 Git、独立工作区与受限构建

日期：2026-10-18（Asia/Shanghai）。本说明细化 [P1.2 计划](../../PROJECT_PLAN.md#p12-git工作区增量开发环境与受限构建)，消费 [D01](../design/01-domain-collaboration.md)、[D02](../design/02-execution-recovery.md)、[D03](../design/03-workspace-build-resources.md) 和 [P0 参照适用决定](../decisions/p0/reference-applicability.md)。这是本轮实施约定；实际支持与结果在独立验收记录中维护。

## 1. 本轮边界与所有权

本轮交付唯一 Git 来源、独立工作文件、固定候选、可重建增量环境和受限构建，使用已有便签参照验证两应用镜像与 PostgreSQL 依赖的完整制品集合。Hub 沿用真实身份、当前权限、Task 控制、命令去重和统一事务。受信任 Git 服务管理元数据，Runner 管理实际进程、隔离、冻结和停止事实。

物理候选不自动成为已验收的最终集成候选。P2 的合并队列、人类写权交接、完整验收消费者和预览不在本轮实现；P1.3 的共享宿主分配/调整协议与 P1.4 的 Release/远端部署亦不自动开放。使用者不能通过提交布尔值、任意宿主路径或自造资源引用绕过尚未成立的门禁。

状态归属保持 D01 不变：`projects` 管唯一来源；`workspaces` 管工作区及物理候选；`delivery` 管 BuildRun 业务结果；`artifacts` 只提供内容保存/核验及索引服务。Runner 记录物理事实，不复制 Task 或 BuildRun 业务状态。目录选择不改变领域权威。

## 2. 文件归属与实施顺序

|负责方|负责文件|首步及后续边界|
|---|---|---|
|Git 代理|`packages/contracts/p1/workspace_git.py`；`modules/workspaces/` 的 Git、路径和工作文件模块|首步仅精确对象/安全文件视图；后续才接候选冻结、受控修改和 Git 操作。`tables.py`、应用/查询/工作流归 Hub 代理|
|Runner 代理|`packages/contracts/p1/runner_contracts.py`；`services/dev-runner/`；专属 probe/check 方法|首步仅固定工具链和受限能力探针；通过后分别接环境/缓存/数据，再接构建/归档，每步单独取证|
|Hub 代理|来源表/应用；工作区/构建记录与命令；`modules/delivery/`、`modules/artifacts/`；线性迁移、必要身份/Task 接缝、API/worker|先结构，再显式工程授权/初始输入，再物理回执和域内工作流；不在同一步包办全部集成|
|工程授权代理|`modules/identity/policy.py`、`packages/contracts/p1/identity_requests.py` 和专属授权检查；必要时新增独立工程授权模块|只接入显式 `workspace.write`、`candidate.submit`、`operation.request`，保留旧绑定原动作；不改 Hub 结构、Task 输入或 API 路由|
|制品内容代理|`packages/contracts/p1/build_artifacts.py`、`modules/artifacts/` 和专属内容检查|独立核验 OCI 归档的成员、大小、摘要与平台并原子发布；不写 BuildRun 业务状态或 Runner 构建执行|
|主会话|计划/进度、设计裁决、实施/使用说明、根版本与必要 CI、OpenAPI 同步、最终 InputSet/集成方法及 Git|消费代理已交付接口与证据；代理负责实现未交回前不替写、不交叉修改|

本次接续的子代理按用户最新要求固定为 `gpt-6.1-sol / max`。每个后续任务另列输入、少量负责文件、产物和退出条件；异常终止后沿原任务继续。共同契约先完成定义后再由消费者接入，避免同时重写字段。

每个新切片轮换新代理，最多六个同时执行；已有小任务先交回，不因换人丢弃进度。代码编写可并行，真实重执行通过同一独占准入串行运行；并发代理数量不代表物理资源额度。

## 3. Git 来源和文件视图

`RegisteredGitSource` 包含项目、来源身份/修订、来源种类、目标分支、源码子目录、对象格式和访问模式。实际路径及认证由受控注册表解析；公共请求不直接选择宿主路径或发送长期凭据。每项目只有一个当前来源，更换来源需后续明确迁移，本轮拒绝原地覆盖。

新建来源支持受管 bare；便签参照从固定源 commit 的 `examples/standalone-project` 子树受控导入，保留原始来源和字节摘要。导入后新项目的受管 bare 是该项目唯一权威，原 CloudHelm 仓库只是种子来源。已有外部权威接入应记录实际访问能力；尚未支持的认证、LFS、submodule 或完整 Git 模式明确拒绝，不能静默换成另一个权威来源。

`WorkspaceBinding` 固定项目/Task/WorkItem/owner、来源身份/修订、精确 `base_commit`、工作区修订及写入代次。`WorkspaceFiles` 保存受控存储标识、清单摘要、文件数/字节数。`CandidateSnapshot` 保存独立候选 commit、父 commit、来源/工作区修订、冻结操作引用、清单摘要和固定位置引用。

Git 服务按参数数组调用系统 Git，使用受控环境，关闭 hooks、外部 diff、textconv、过滤器和系统/用户 Git 配置。服务不接受任意 Git 子命令、任意 refspec 或宿主 shell。默认工作视图没有 `.git` 文件/目录，元数据不挂入沙箱；首版可以拒绝所有符号链接、特殊文件及不支持的对象类型。安全读写使用受控目录 fd、`O_NOFOLLOW`、边界检查和原子发布，不能仅靠先 resolve 后按字符串重新打开。

Git commit 与 SHA-256 内容摘要分别保存。既有 `EngineeringRef` 继续按当前元数据契约求摘要，`SourceMetadata.commit` 保存 Git SHA；工作文件清单摘要独立保存，不把 SHA-1 当作 SHA-256。物理候选不能冒用现有 integration 的最终候选事实来源。

低层初始接口为 `inspect_commit(source, base_commit)` 和 `materialize(binding, operation_id)`；后续 `status/diff` 只接收有界受控路径，`capture_candidate(binding, frozen_handle)` 只接受实际 Runner 冻结作用域内取得的能力。低层函数不独自授予业务权限，应用适配须先解析已登记操作、核对当前门禁及实际开发限额。

## 4. 短事务、工程权限与 Task 输入

来源登记使用 `project.manage`。工作区修改、固定候选和构建申请分别使用 P0 已定义的 `workspace.write`、`candidate.submit`、`operation.request`。P1.1 现有授权不会因更新全局动作集合自动得到新动作；原角色/委托保持原列表，开发动作按既有 P0 角色上界显式授予，不能用 `task.command` 或所有者身份替代。

应用命令保持身份/项目策略 → Task/工作区 → 去重记录的既有锁序。当前权检查先于原结果返回；同键同摘要先返回持久结果，新转换才检查 expected version、控制/输入修订和工作区代次。命令意图、关联、事件与必要 DBOS 入队在同一 UoW 中提交。其他领域通过接收该 UoW 的内部方法参与，不嵌套调用另开事务的应用命令。

P1.2 新增受控初次工程 InputSet 绑定接口，消费已存在且可核验的来源/需求/验收/资源策略引用。不能复用 P1.1 完成 fixture 的合成 `task_inputs`，不能凭固定工作文件就生成已完成/已验收事实。后续候选和构建始终绑定准确输入，输入变化后的晚到结果可归档，但不能恢复普通推进。

外部 Git、文件和容器操作在事务提交后进行；新副作用前重新检查真实当前授权、Task/写入权、能力及开发限额。物理事实保存稳定操作身份、规范摘要及结果查询；未知结果先核对原操作。内容原子保存并核验后，事务只登记既存内容引用。事务失败留下的内容按保留策略管理，不声称文件与 PostgreSQL 原子提交。

新增迁移从 `0001_p1_1` 线性前进，旧迁移不修改。新版本先支持新隔离开发库；既有安装版本不匹配时继续拒绝，`initialize` 不冒充升级器。如实际需要已有库升级，单独拆出有明确版本/回滚边界的受控维护任务。SDK 版本不因新表自动变化。

接续顺序中，工程动作上界与请求契约作为独立小步先行：核对 P0 角色上界、旧记录动作列表与新请求验证；来源/工作区应用随后消费该接口。实际授予及撤权仍走当前项目策略事务，不能通过全局集合变化给既有角色增加权限。

## 5. Runner、限制与能力核验

Runner 只接受封闭的注册操作，`RunnerOperationSpec` 绑定原操作/摘要、项目/Task、执行器身份、工作区或候选、InputSet、修订/代次、工具链、策略、开发限额记录和 UTC 截止时间。公共调用者不能给出任意命令、挂载、Docker 选项或已授权/已预留断言。实际文件位置和限额必须从受控注册记录解析。

首个能力探针仅开放 `probe_capabilities`。`RunnerCapabilityReport` 分别记录 rootless UID 映射、PID/proc 隔离、CPU/内存/PID 父级硬限、存储硬限、网络隔离、停止事实及固定工具链身份，每项为 verified/unsupported/unverified。配置声明、目录存在、容器启动不等于能力已验证。

按 D03 优先验证 rootless BuildKit：固定镜像 digest，使用 `native` snapshotter，保留 process sandbox，外层 Docker 使用独立非 host 网络命名空间。所需 seccomp/proc 例外随方法记录；禁止 `--oci-worker-no-process-sandbox`、privileged、宿主 Docker socket、控制面数据库、长期凭据和任意宿主挂载。不能支持的组合明确拒绝。

本机受控开发组合只允许一个执行组，实际 CPU、内存、PID、时间与有界可写存储覆盖 Builder 及 RUN/辅助子进程。没有持久文件系统硬配额时，先验证有界 tmpfs 范围；无证据不能把逻辑字节计数当硬隔离。静态专用开发组合不冒充 P1.3 多 Runner 共享资源账本，普通自动执行和远端入口在前置未就绪时封闭。

原参照 Dockerfile 需要 pip/uv/npm 出站，不能假定断网可构建。依赖获取在下一小步选择可核验的受控网络或显式离线配方变体；变体固定完整工具链、下载物和构建参数，不更改历史参照或冒用其通过结论。无受控出站的沙箱不获得临时公网旁路。

本轮固定参照采用显式离线变体：可信获取端仅下载原锁中适用的已核验 wheel/tarball，沙箱完全断网。Python 的原普适 registry 锁与 flat wheelhouse 解析不兼容时，派生仅适用于 linux/amd64 的离线锁，并逐项比对原锁的适用 name/version 集合；派生配置、锁和配方独立求摘要，原参照保持原字节。npm 下载种子保存原始 tgz，私有 cacache 由断网执行器建立，不能将下载通过写成安装或构建通过。

## 6. 环境、候选、缓存与制品

环境区分可变开发、固定候选和制品验证。状态 preparing/ready/suspended/failed/disposed 记录实际工具链、运行源码修订、数据修订、入口、资源和活动；ready 需要进程和就绪证据，目录创建不算成功。

下载缓存、构建缓存、工作区可写依赖分别管理，缓存键至少含项目/信任域、工具链、OS/架构、锁文件及安装参数。共享缓存仅受控写入/只读发布，开发环境不能共同修改；锁变化使旧键失效。测试数据采用版本化初始化/迁移/重置，默认合成数据且与预览隔离；准备失败如实记录。

固定候选时阻止全部新写入，实际停止或冻结所有相关容器、watcher 和后台进程。受信任冻结句柄只在该作用域有效，未知写入者拒绝采集；候选独立保存、核验后只读提供，恢复开发不会改变它。P2 的人工接管与集成队列不通过这个句柄提前开放。

当前固定参照的 Runner 源码挂载只读，可写依赖/缓存/产物留在独立有界执行区；工作区源码修改只通过持有同一排他锁的受信任文件服务。候选采集同时持有该锁并核验实际容器挂载及已登记写入者；发现未知写入者或未受支持的可写 Runner 视图就拒绝。该受限组合不表示已经支持任意后台工具直接写源码。

构建输入固定源码/候选、锁、Dockerfile/实际配方、工具链与基础镜像、平台、参数、descriptor、Compose 源、参数化运行契约、配置 schema、迁移及独立验收资产引用。数据库依赖也属于制品集合。外部可变依赖须固定解析结果及适用限制；相同 commit 不等于同一构建输入。

构建归档在受限临时存储生成，由可信采集器核对大小、归档 SHA-256、OCI manifest/config digest、实际 image ID 与 linux/amd64 平台，再原子发布只读索引。BuildRun 只消费可信实物回执，不信任仓库脚本自报通过或镜像身份。最终镜像启动/就绪及独立 HTTP 关键检查绑定新输入，正式验收脚本不进入候选构建上下文且不能被其改写。

内容采集先独立支持单一 `linux/amd64` OCI image archive：逐层核对 descriptor 大小与 SHA-256，拒绝归档路径越界、重复成员、符号链接及不支持媒体类型，固定 archive/manifest/config/layer 身份。归档核验不等于镜像启动成功；Runner 的实际 load/inspect 回执另行核对 config/image ID，BuildRun 只有收齐对应输入和实物证据才可形成业务结果。

目标交付只消费已固定归档/镜像和运行契约；P1.2 不生成虚构的 Release、环境批准或部署成功，也不发送源码到目标临时构建。实际归档和源码保持不同权限及生命周期。

## 7. 验证与版本依据

本轮新增工程能力的开发源码版本为 `0.2.0`，DBOS 工作流应用版本单独固定为 `cloudhelm-hub/0.2.0`；业务线性迁移为 `0003_p1_2_builds`（经 `0001_p1_1`、`0002_p1_2` 线性前进），DBOS SDK 继续固定 `3.2.0`。软件、工作流与数据库版本分别核对，数值接近不表示合并管理。新隔离库验证适用于这些基线；旧 `0.1.0` 安装不由 `initialize` 自动升级，未发布 tag 或 Release。

验证按 Git 文件边界、Hub 当前权/事务/输入、Runner 实际限制、环境/缓存/数据和最终构建分组。每个小步只执行相关必要检查；最终新 InputSet 绑定源码、方法、依赖和环境，同一候选合并结果不能由三个代理的局部成功替代。

固定 InputSet 前的运行标记为 development_worktree；固定后若代码、方法或环境发生影响语义的修改，重新绑定新输入。失败、unknown、未执行和待人类确认均保留，不填写通过。旧 P0/P1.1 清单和历史结果不改写。

本说明不授予 s2413 安装、生产操作、外部发布、main 合并或人工验收。正常开发提交和 dev 推送按仓库工作流执行；P1.2 的实际完成范围及下一入口由最终证据决定。
