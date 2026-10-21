# 首条参照交付链路规格 r2

修订日期：2026-10-15（Asia/Shanghai）。依据总体 v4.7、D06 v4.7.1 §2.1 和 PROJECT_PLAN.md P0.2/G01/G02。r2 明确 s2413 同机准备与固定参照的编译/拒绝边界，不修改原参照源码、需求、独立资产或历史 InputSet。表中的产品动作仍由 P1～P6 实施和验收；本规格不构成部署批准、人测结论或 P0 统一放行。

## 1. 来源与固定资产

历史来源为本机历史 CloudHelm Git 仓库的 `examples/sample-repo-python`，初始 commit `3293a09c2501ee5bace398c6214dfcb7016c0824`，子树 `b765b5f8ee988cd1d95f8a45dd6960597d047573`。本轮重新通过 `git cat-file` / `git ls-tree` / `git show` 读取该提交与入口源码：只有 FastAPI 存活/指标切片，没有 React、PostgreSQL 和 Alembic。复用存活检查的独立语义；新增便签完整组合，不把新实现写成历史来源已有能力。

|输入|固定来源与修订|责任/证据|
|---|---|---|
|原始需求|[reference-requirements-r1](reference-requirements-r1.md)，REF-01～08 及 JSON 契约|主会话依授权范围固定；人类产品批准另行记录|
|参照源码|[examples/standalone-project](../../examples/standalone-project/README.md)，前端/后端/迁移/构建与本机 Compose|独立开发小任务建设，当前 Git 源码 commit 由 InputSet 固定|
|API 契约|`examples/standalone-project/backend/openapi.json`，由实际 FastAPI app 导出；SafeError 匹配实际安全响应，生成物单独保存|info.version=0.0.0 为参照元数据，不是 CloudHelm 软件版本|
|独立验收|[reference-http-r1.1](../acceptance/reference/r1/README.md)，独立代理只依固定需求编写，不读候选源码|入口、断言与资产清单不在候选构建上下文；实际结果由外部操作者绑定|
|候选与方法输入|[reference-input-set-r1.json](../acceptance/reference/input-set-r1.json)|保存 source_commit、需求/资产/锁文件/源码 SHA-256，不含秘密或运行数据|
|运行输入/结果|[validation-r1](../acceptance/reference/validation-r1.md)|绑定最终容器镜像身份、方法、故障注入和实际结果；新输入不沿用旧通过|
|实际拓扑|[当前角色与拓扑](../decisions/p0/topology.md)|WSL 仅为本机开发；Hub、Runner 和当前交付验证共同使用 s2413，按一个共享宿主计量；正式独立目标留在 P1.4/P1 出口前置|
|支持组合|[支持矩阵](../acceptance/support-matrix.md)|实际支持、开发配置、拒绝与未核验范围分列；当前修订包含用户补充的 s2413 同机角色|

独立验收是本轮外部 HTTP 方法，尚非 P2 产品执行器的正式受控验收服务。未来候选只取得源码/构建输入，正式入口、关键断言及跳过策略由验收来源单独只读提供；本轮 Docker build 的后端/前端目录不能访问 `docs/acceptance/`，没有提供跳过必需项的选项。人类验收字段仍为空。

## 2. 候选与运行约定

以下版本属于已固定的参照输入，按 InputSet、锁文件和镜像摘要核对。版本变化须建立新输入并更新对应规格，不能仅手工改写版本号或沿用旧运行证据。

Python 3.12.13、FastAPI 0.143.0、SQLAlchemy 2.1.4、Alembic 1.20.0、psycopg 3.3.6、Pydantic 2.14.1、Uvicorn 0.54.0；前端依 package-lock 固定 React/TypeScript/Vite 6.4.4，构建 Node 22.23.2；PostgreSQL 16.13。Node、Python、Nginx 与 PostgreSQL 基础镜像 digest 在参照开发 Compose 固定，最终候选镜像 ID 由 validation-r1 记录。

`compose.yaml` 是本机参照建设/故障取证入口，含 build、depends_on、健康检查、资源上限及 loopback 映射；不是已经实现的 CloudHelm Release 运行声明。产品解析器当前实验子集只接受 image/environment/networks/volumes/restart/healthcheck，拒绝其他字段；P1.2/P1.3 必须从固定构建生成制品及受限运行声明，不能把开发 Compose 原样提交到部署入口绕过拒绝。DNS 选项也只属于本轮开发环境，产品是否支持须独立评审。

[P0-G02a 适用决定](../decisions/p0/reference-applicability.md) 对固定原文件的 52 个映射字段分别明确复用、受控编译和拒绝，旧解析器实际首先拒绝 `services.postgres.mem_limit`。资源上限、只读根、有界 tmpfs、数据库持久卷、loopback 和 DNS 行为不能被剥掉；目标拒绝开发 trust 认证，并要求显式内部网络、完整资源组和版本化秘密引用。参照三个服务的上限合计为 896 MiB/1500m，仍不构成完整资源申请。历史 Compose/Remote 实验不冒充完整产品计划。

迁移明确执行 `alembic upgrade head`，应用启动不建表。当前链为 `0001_create_notes → 0002_add_updated_at_index`，单根/单 head。首批参照仅选择在线、单目标、线性迁移；未知迁移结果先查询原身份与实际 revision，数据破坏、并行分支、自动 downgrade 和任意 shell 迁移不支持。P1 将为真实 Deployment 建立稳定迁移操作与后置查询，当前外部 CLI 成功不等于部署已完成。

上述 `upgrade head` 是历史参照复现入口。P1 完整计划固定准确目标修订，先取得数据库实例、认证、卷和资源的真实前置证据，再按有界步骤迁移、更新应用并核验健康；`depends_on` 和 `pg_isready` 不证明迁移完成。数据库创建、角色配置和镜像加载属于受控副作用，不能藏进只读 `runtime_input_check`。

## 3. 九个检查点

各检查点的完整权威语义由 D06 §2.1 引用 D01～D05；此表固定参照输入、保留和执行入口，不另造状态机。P0 的参照启动不替代产品 Task 启动。

|检查点|固定输入/完成判定|失败保留与重试授权|最早完整证据|
|---|---|---|---|
|Task 启动|项目源码来源、需求/验收修订、当前发起者、预算与资源范围；可靠建立 WorkItem/初始请求，执行前另查模型/资源准入|保留身份/回执/拒绝；原身份查询，同义重投；改变范围由有权项目角色新修订|P1 基础、P2 单 Agent|
|长工具提交|稳定 Operation/规范摘要、当前权限及步骤依赖；持久 accepted 回执，结果独立查询|保留原操作和授权；异摘要拒绝，未知先核对；远端新步骤再取许可|P0 A01 有限接缝，P1 实际执行|
|固定候选|最终集成 commit、锁/构建输入、需求/验收资产 SHA、候选镜像身份；InputSet 不可变|保留候选/制品/失败；有权项目角色决定新候选，变更源码/资产/环境建立新 InputSet|P0 资产冻结、P1 制品|
|候选验证|上述输入、reference-http-r1.1 与方法版本、独立资产、运行环境/必需检查；全部必需项通过且仍适用|保留每轮输入/结果；同输入按规则新轮次，变更候选不复用旧证据|P0 参照本机，P2 正式门禁|
|可选人工测试|默认关闭；开启时固定候选、测试者、策略和环境实例；只有有权人类提交真实结论|关闭不造等待；保存反馈/未完成/明确跳过；环境故障不自动通过，新候选新轮次|P2 最低、P6 客户端|
|Task 完成|当前权限、Task/控制/输入版本、适用验收/集成证据、人测门槛与范围内写操作收尾；短事务唯一报告并关闭普通推进|不满足保留状态及阻塞对象；未知写先核对；同键/新键查询既有报告不生成第二份|P1 基础、P2/P3 扩展|
|形成 Release|完整不可变前后端制品、参数化契约、配置 schema、线性迁移与适用证据；满足发布策略|保留候选/拒绝/未完成检查；输入修订走新候选/Release，发布者另授权|P1|
|执行 Deployment|Release、环境修订、实际目标起始基线、批准计划摘要；每个新步骤当前许可，目标事实/迁移/后置检查证明结果|保留原计划、账本、许可和实际状态；未知查询，批准仍适用才能原计划续行；输入/批准变化重新解析批准|P1、P4 故障扩展|
|关闭 Incident|真实业务持续恢复窗口、观测覆盖、通知/确认及修复 Task；恢复证据满足业务规则|保留缺口/未完成操作；通知不等于确认/恢复，证据不足不关闭，由有权处置者继续|P5|

Task、Release、Deployment、Incident 的结论独立。服务存活、accepted、解除等待、单个命令成功或通知送达均不替代表中的完整判定。

## 4. 未决输入与下一门禁

P0.2 的源码、固定需求、独立方法、九检查点和实际诊断均有明确输入。用户当前仍选择 Hub、Runner 和交付验证共同使用 s2413；新 [实际快照](../acceptance/p0/topology-s2413-r2.md) 与 [受控方案](../decisions/p0/s2413-development-envelope.md) 补齐同机准备决定，尚未建立的路径、硬配额、身份与可信占用使新执行准入保持关闭。P1 的安装注册/产品网络、P2 的 DNS/TLS/预览/原生客户端及真实人类结论按各自入口取证。D06 的另一台独立交付机器由项目所有者在 P1.4/P1 出口前安排，不能用同机或 WSL 替代。

P0.1 和 P0.2 原估算分别保留 2～3、1～2 人日作历史对照，A01/A02、参照建设和本轮 G01/G02 另列增量。人工实际投入未计量，不能把并行代理墙钟差换算为人日；累计总量及 P1 实施/真实验收的剩余量按证据重估。P0 当前裁决见 [统一出口](../acceptance/p0/exit-review.md)，结项本身不启动 P1。
