# 支持矩阵 r1

日期：2026-10-13（Asia/Shanghai）。输入见 [首条参照规格](../implementation/reference-chain.md)、[A01 接缝](p0/A01.md) 和 [实际拓扑](../decisions/p0/topology.md)。此表区分本机开发取证、候选决定和产品支持；没有证据的组合保留未核验，不自动纳入正式支持。

|组合/能力|本轮实际范围与证据|不支持或未核验时的行为/门禁|
|---|---|---|
|WSL 开发|Ubuntu 24.04.4、x86_64、WSL2 内核，Python 3.12.13，Docker 29.1.3/Compose 2.40.3；真实接缝和参照验证通过|只作为开发环境；可见内存约 7.36 GiB，不宣称 8 GiB light 整机容量通过|
|独立交付 s2413|Debian 13、x86_64、6 vCPU、约 15.51 GiB RAM；Docker 26.1.5/Compose 2.39.4，只读可达|项目路径、配额、目标身份、网络/TLS及实际交付待核验；阻断 P1 对该机副作用启动，责任基础设施/交付负责人|
|Hub 与开发 Runner|设计分别为 Linux x86_64；本机可做隔离探针，尚无已部署 Hub/注册 Runner|未获得角色/共享宿主/物理配额证据时不开放产品执行；P0.3 决定，P1 取证|
|模型/Gateway/DBOS|固定 gpt-6-luna/max、Standard 全球用户函数流、单 worker、有界引用薄适配；A01 所选有限切片及 [A02](p0/A02.md) 恢复新请求/消费后失败检查点/严格断流组合已取得证据；SDK 二次请求用固定夹具核验门禁|未知费用保持占账；未支持档位拒绝准入/计价；未经裁剪的默认 DBOS 包装入口拒绝；P0.1 完整出口未放行，不扩展多 worker或跨版本支持|
|产品 Compose 实验子集|image/environment/networks/volumes/restart/healthcheck；两阶段解析与版本绑定拒绝清单见 p0/compose-remote.md|build、privileged、devices、network_mode、env_file、include/extends/profiles及未列字段明确拒绝；固定 development Compose 不能原样送产品部署|
|参照构建与开发 Compose|Docker BuildKit 的两个独立目录，Python/Node/Nginx/Postgres digest 固定；锁定依赖生产构建、健康/迁移/故障/持久化通过|build/depends_on/read_only/tmpfs/dns_opt/ports等仅为本轮开发夹具；P1.2/P1.3 生成受限 Release 运行声明，不由本轮推定产品支持|
|迁移|PostgreSQL 16.13，在线单目标线性 Alembic，两修订、单根/head；显式迁移与实际 head 核对|非线性、并行迁移、任意 shell、自动 downgrade不支持；P1 仍须稳定操作/未知结果核对和后置证据|
|浏览器参照|Codex 内嵌浏览器的真实 CRUD、失败提示/表单保留；外部 HTTP method r1.1 覆盖同源静态资源与 API|只覆盖参照 Web UI；不推定其他浏览器、Tauri/WebView 或能力隔离通过|
|Windows/Linux Desktop|Tauri/React/TypeScript 为设计决定，工程和原生矩阵尚未实施|Windows 11/WebView2、Linux WebKitGTK 的安装/升级/隔离证据未执行；责任客户端，P1/P2/P6 相应门禁|
|预览 DNS/TLS|采用 D05 规定的受控代理与受限会话；实际域名/证书及通路尚未核验|不提供生产预览、票据兑换或撤销支持结论；P0.3 决定，P2 六组证据取得前拒绝正式入口|
|可信时间/本机应急|s2413 NTP enabled/synchronized仅为系统快照|不能据此证明许可误差、老化或失信恢复；P0.3/P1/P4 验证。P4 前本机应急关闭|

Compose 字段的产品权威规则在 D04；当前有限解析探针不负责完整产品兼容表。新增字段、构建器、迁移模式、客户端或机器均须新输入/方法证据。支持矩阵冻结是 P0.2 的规格产物，不代表矩阵中所有产品组合已经通过验收。
