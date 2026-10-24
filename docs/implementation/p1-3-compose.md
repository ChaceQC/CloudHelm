# P1.3-02 两阶段 Compose 解析实施说明

本页记录 P1.3-02 的 Compose 剩余切片。实现位于
`modules/delivery/compose.py` 与 `packages/contracts/p1/compose_contracts.py`，只提供
受限 Compose 子集的解析、规范化和环境绑定；不把该切片写成完整部署执行器或产品验收结论。

## 1. 两个阶段

第一阶段 `parse_release_source(source_text)` 只接收调用方已经取得的 UTF-8 源文本：

1. 使用拒绝重复键、锚点/别名、合并继承和自定义标签的 YAML 装载器。
2. 拒绝进程或 dotenv 插值，核对根字段、服务字段、项目网络、命名卷和每个参数/secret 槽的位置。
3. 将 digest 固定的镜像、内部 bridge 网络、受管 local 命名卷、loopback TCP 端口、命令、健康检查和重启策略规范化为 `ComposeReleaseSpec`。
4. 以规范化源摘要和解析器修订生成不可变 `release_digest`/`release_id`。结果只保存参数契约和 secret 引用契约，不保存 secret 值。

第二阶段 `bind_environment_config(release, config)` 只接受已声明的参数集合和 secret 版本引用：

1. 参数集合必须与第一阶段契约完全相同，值必须属于声明的枚举。
2. secret 集合必须与第一阶段契约完全相同，值必须匹配 `secret://...@vN`；解析器不接收或读取 secret 明文。
3. 替换只发生在对应服务的声明槽位，镜像、网络、卷、端口、命令、健康和重启字段保持不变。
4. 重新计算配置摘要和 `plan_digest`，并再次核对服务拓扑和运行契约，形成 `ComposeDeploymentPlan`。

## 2. 当前支持与拒绝边界

支持范围固定为单个源文档、最多 16 个服务、32 个内部 bridge 网络、32 个受管 local 命名卷和每服务有界环境变量。镜像必须使用 `@sha256:` 摘要；卷只允许 long syntax 的 `type: volume`；发布端口只允许 `127.0.0.1` 的 TCP 端口。

以下输入明确拒绝并返回稳定的路径/原因码：`include`、`extends`、`profiles`、`build`、`env_file`、外部文件、插值、未知字段、重复 YAML 键、锚点/别名、合并继承、自定义标签、bind mount、设备、host 网络、Docker socket、非 loopback 端口、越界数量和未声明的网络/卷引用。敏感环境名（如 `TOKEN`、`PASSWORD`、`SECRET`、`API_KEY`）只能使用 secret marker，不能把明文放入源或配置。

解析错误只返回字段路径和原因码，不回显输入值。模块不读取任意路径、环境变量、Docker socket 或 secret 存储；Docker/Remote Agent 的物理执行、批准、迁移和健康事实仍由后续交付工作包负责。

## 3. 兼容与版本

当前协议标记为 `cloudhelm.p1.compose-r1`，解析器为 `p1-compose-parser-r1`，Release 和 DeploymentPlan 分别使用 `p1-compose-release-r1` 与 `p1-compose-deployment-r1`。扩展支持字段或改变参数/secret 语义时必须递增契约/解析器修订，不能静默把旧 Release 当作新拓扑。

P0 的 `cloudhelm.p0.experimental` 探针、历史 Docker Compose 文件和 `remote-plan.schema.json` 仍是历史输入，不由本实现追认成产品接口。当前实现的规范化结果不授予部署权限，也不表示目标机器、资源容量或人工验收已经通过。
