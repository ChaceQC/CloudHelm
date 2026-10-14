# 支持矩阵 r4

修订日期：2026-10-15（Asia/Shanghai）。r4 新增 [P1.1 固定候选开发记录](p1/p1-1.md)，原 r3 的 s2413 同机准备事实和逐入口方案保持其历史范围。其余输入见 [首条参照规格](../implementation/reference-chain.md)、[A01 接缝](p0/A01.md)、[A02](p0/A02.md)、[P0 拓扑快照](p0/topology-s2413-r2.md)、[受控环境决定](../decisions/p0/s2413-development-envelope.md)、[参照适用决定](../decisions/p0/reference-applicability.md) 和 [P0 出口评审](p0/exit-review.md)。各运行证据绑定各自候选和时间，没有证据的产品组合不自动纳入支持。

|组合/能力|本轮实际范围与证据|不支持或未核验时的行为/门禁|
|---|---|---|
|WSL 开发|Ubuntu 24.04.4、x86_64、WSL2 内核，锁定工程 Python 3.12.13；P0 采集器使用系统 Python 3.12.3，Docker 29.1.3/Compose 2.40.3；历史接缝和参照验证按原候选有效，P1.1 另绑定当前源码与新输入|只作为开发环境；P0 可见内存约 7.36 GiB，不宣称 8 GiB light 整机容量通过。P0 PATH 无 Linux Node，Windows npm 被采集器拒绝的记录不影响历史固定容器构建证据|
|Hub 身份、命令与 Task 基础|`cloudhelm-hub/0.1.0`、PostgreSQL 16.13、DBOS 3.2.0、业务 head 0001_p1_1；[125 个固定输入](p1/input-set-p1-1-r1.json)对应[61 个结果键全部通过](p1/validation-p1-1-r1.json)，覆盖真实角色/HTTP、同库事务、Task 控制竞争与单 worker；API 13 路径/15 操作|完成/封闭正向域事实为 protocol_validation 合成来源，不代表真实开发/人测/执行器验收；模型、构建、Runner/Remote、Desktop 和 s2413 部署未由本行放行。精确 DBOS 系统 schema 数字保持 null，多机 HA/跨版本恢复不支持|
|s2413 同机开发组合|用户选择 Hub、开发 Runner 和当前交付验证均使用 s2413；本轮快照为 Debian 13、x86_64、6 CPU、约 15.51 GiB RAM、Docker 26.1.5+dfsg1/Compose 2.39.4，四个候选项目目录均不存在|共享一个物理宿主资源池；具体受控方案已单列，项目额度/归属占用上界仍未知，新准入关闭。安装注册、配额生效、产品身份/通道和网络/TLS仍须 P1 实际取证|
|正式独立交付拓扑|s2413 同机结果不能计为另一台交付机器；本次未安排第二台目标|项目所有者/基础设施负责人在 P1.4 前指定并核验独立目标；不宣称 D06 独立交付或两档容量通过|
|模型/Gateway/DBOS|固定 gpt-6-luna/max、Standard 全球用户函数流、单 worker、有界引用薄适配；A01 所选有限切片及 [A02](p0/A02.md) 恢复新请求/消费后失败检查点/严格断流组合已取得证据；SDK 二次请求用固定夹具核验门禁|未知费用保持占账；未支持档位拒绝准入/计价；未经裁剪的默认 DBOS 包装入口拒绝。历史支持范围由各自输入限定，产品接线仍须 P1/P2 证据，不扩展多 worker 或跨版本支持|
|产品 Compose 实验子集|image/environment/networks/volumes/restart/healthcheck；旧专项仍保留原候选，本轮实际观察原参照被 parse_source 拒绝|build、privileged、devices、network_mode、env_file、include/extends/profiles及未列字段明确拒绝；G02a 覆盖全部 52 个映射字段，资源/只读/网络不可剥离后冒充支持|
|参照构建与开发 Compose|Docker BuildKit 的两个独立目录，Python/Node/Nginx/Postgres digest 固定；锁定依赖生产构建、健康/迁移/故障/持久化通过|build/depends_on/read_only/tmpfs/dns_opt/ports等仅为本轮开发夹具；P1.2/P1.3 生成受限 Release 运行声明，不由本轮推定产品支持|
|迁移|历史参照为 PostgreSQL 16.13、在线单目标线性 Alembic、两修订和实际 head 核对；P0.3 [迁移决定](../decisions/p0/migration-contract.md) 冻结单事务模式、五类查询及稳定身份|非线性、并行迁移、任意 shell、自动 downgrade、非事务/无界迁移不支持；新契约的给定事实校验不替代 P1 的真实账本、未知结果核对和后置证据|
|浏览器参照|Codex 内嵌浏览器的真实 CRUD、失败提示/表单保留；外部 HTTP method r1.1 覆盖同源静态资源与 API|只覆盖参照 Web UI；不推定其他浏览器、Tauri/WebView 或能力隔离通过|
|Windows/Linux Desktop|Tauri/React/TypeScript 为设计决定，工程和原生矩阵尚未实施|Windows 11/WebView2、Linux WebKitGTK 的安装/升级/隔离证据未执行；责任客户端，P1/P2/P6 相应门禁|
|预览 DNS/TLS 与撤销|P0.3 [预览决定](../decisions/p0/preview-access.md) 固定路线、无 URL 票据、原始入口和逐代理确认；实际域名/证书及通路尚未核验|未验证客户端保持关闭；P2 六组真实隔离/撤销证据前不声明预览支持，合成元数据检查不替代网络/原生证据|
|许可时间|P0.3 [许可决定](../decisions/p0/time-preview-access.md) 选择 Hub 单调授权时间、整数微秒和有界误差；s2413 NTP 布尔值仍仅为历史系统快照|实际误差依据、暂停检测、认证样本和真实接受/启动/失信恢复须 P1/P4 取证；旧 grant 的窗口不刷新|
|本机应急|[核心决定](../decisions/p0/core-boundaries.md) 固定 Unix socket、独立管理员认证、动作/期限和显式交还；本修订 enabled 只能为 false|P4 验证前关闭，未生成授权配置或认证材料，不把人类模型任务授权当作应急身份|
|P0.3 决定契约|独立 p0-decisions-r1 模型、JSON Schema 和固定类型/纯函数检查，实际候选与结果见出口评审|只证明绑定输入的契约；不授予权限、不提供持久唯一性、物理执行或人工验收结论|

Compose 字段的产品权威规则在 D04；当前有限解析探针不负责完整产品兼容表。新增字段、构建器、迁移模式、客户端或机器均须新输入/方法证据。支持矩阵冻结是 P0.2 的规格产物，不代表矩阵中所有产品组合已经通过验收。
