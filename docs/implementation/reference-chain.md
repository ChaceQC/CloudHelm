# 首条参照交付链路规格 r1

日期：2026-10-13（Asia/Shanghai）。依据总体 v4.7、D06 §2.1 和 PROJECT_PLAN.md P0.2。P0.2 固定可核验输入、实际环境及逐检查点判定；表中的产品动作仍由 P1～P6 实施和验收。本规格不构成部署批准、人测结论或 P0 统一放行。

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
|实际拓扑|[topology-r1](../decisions/p0/topology.md)|WSL 开发与 s2413 独立交付候选分开；真实未决值列出责任和门禁|
|支持组合|[support-matrix-r1](../acceptance/support-matrix.md)|实际支持、开发配置、拒绝与未核验范围分列|

独立验收是本轮外部 HTTP 方法，尚非 P2 产品执行器的正式受控验收服务。未来候选只取得源码/构建输入，正式入口、关键断言及跳过策略由验收来源单独只读提供；本轮 Docker build 的后端/前端目录不能访问 `docs/acceptance/`，没有提供跳过必需项的选项。人类验收字段仍为空。

## 2. 候选与运行约定

Python 3.12.13、FastAPI 0.143.0、SQLAlchemy 2.1.4、Alembic 1.20.0、psycopg 3.3.6、Pydantic 2.14.1、Uvicorn 0.54.0；前端依 package-lock 固定 React/TypeScript/Vite 6.4.4，构建 Node 22.23.2；PostgreSQL 16.13。Node、Python、Nginx 与 PostgreSQL 基础镜像 digest 在参照开发 Compose 固定，最终候选镜像 ID 由 validation-r1 记录。

`compose.yaml` 是本机参照建设/故障取证入口，含 build、depends_on、健康检查、资源上限及 loopback 映射；不是已经实现的 CloudHelm Release 运行声明。产品解析器当前实验子集只接受 image/environment/networks/volumes/restart/healthcheck，拒绝其他字段；P1.2/P1.3 必须从固定构建生成制品及受限运行声明，不能把开发 Compose 原样提交到部署入口绕过拒绝。DNS 选项也只属于本轮开发环境，产品是否支持须独立评审。

迁移明确执行 `alembic upgrade head`，应用启动不建表。当前链为 `0001_create_notes → 0002_add_updated_at_index`，单根/单 head。首批参照仅选择在线、单目标、线性迁移；未知迁移结果先查询原身份与实际 revision，数据破坏、并行分支、自动 downgrade 和任意 shell 迁移不支持。P1 将为真实 Deployment 建立稳定迁移操作与后置查询，当前外部 CLI 成功不等于部署已完成。

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

P0.2 的源码、固定需求、独立方法、九检查点和实际诊断已建立并可复核。s2413 仅完成授权只读核验；Hub/Runner 分配、项目路径/配额、目标网络、DNS/TLS、原生客户端及实名人类结论按支持矩阵保留未核验。基础设施负责人/项目所有者在 P0.3 固定具体授权与范围，P1 实际交付前取得对应证据；不以 WSL 替代独立机器或原生证据。本轮不部署 s2413。

P0.1 和 P0.2 原估算分别保留 2～3、1～2 人日；P0.1-A01/P0.2-A01 的新增投入与剩余工作待估。本轮有并行小任务，不能把墙钟差或代理时长虚构为人日；P0.3 统一出口依据上述明确限制重估关键路径，P1 仍未开放。
