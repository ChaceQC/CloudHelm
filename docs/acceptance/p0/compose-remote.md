# P0.1-07 Compose 与 Hub/Remote Agent 隔离接缝

> 状态：完成本次 WSL 隔离探测；仅覆盖本文列出的输入和观察，不代表 P0.1-07、P0 或产品验收完成。
> 协议标记：`cloudhelm.p0.experimental`，仅为实验草案，不是正式发布版本或 P0.3 决定。

## 运行环境与固定输入

验证运行在 WSL Ubuntu-24.04.4 LTS、WSL2 x86_64，仓库映射为 `/mnt/e/Project/CloudHelm`。环境基线记录在 [component-baseline.md](../../decisions/p0/component-baseline.md)：Linux 内核 `6.18.33.2-microsoft-standard-WSL2`，Docker client/server `29.1.3`，Compose `2.40.3+ds1-0ubuntu1~24.04.1`。本次 Python 环境实测为 Python `3.12.13`、Pydantic `2.14.1`、PyYAML `6.0.3`、rfc8785 `0.1.4`。未读取 Docker 配置、进程环境变量、用户 Compose 文件或密钥。

Compose 源由 [compose_probe.py](../../../scripts/p0/compose_probe.py) 在临时目录生成，并以实际 `docker compose config --format json` 归一化。输入含两个服务 `api` / `worker`、两个固定摘要镜像、一个内部项目网络、一个受管本地命名卷、健康检查和重启策略。`x-cloudhelm` 只声明 `api.environment.APP_MODE` 的枚举参数槽，以及 `api.environment.API_TOKEN` 的秘密引用槽。两份配置修订分别选择 `staging` 和 `production`；都只带合成引用 `secret://synthetic/api-token@v1`，没有秘密值。

最终 Compose 运行：`2026-10-13T04:40:05Z`。固定来源摘要为 `sha256:7b5e66d891dba6406ba80d6e22487e7033491e81312bff1a43bd3a34be6293a4`，Release 摘要为 `sha256:2bdd93b24c381e98616141a01e6faa2686e31a20bf98774651ffb7413ec6c647`。两份 EnvironmentConfigRevision 摘要为 `sha256:4b9a085b31d6f5926c85119dbc74b6299b8d1545d703a48f212b992165a783b0` 与 `sha256:682be830dc5f71be22eec65460d17b81becec6a9e096e4c0fa2f2ce480100a63`；DeploymentPlan 摘要为 `sha256:4838fd80610dff84a79b88afc77ece3eedb5b2d4b38b3440b3d226ec5e885f99` 与 `sha256:b708c9f9a37f84367af845ee3fae798f5969f478f5d9149a72396ee4871fbfb3`。

## Compose 观察

脚本先拒绝重复 YAML 键、别名/锚点和合并继承，再按固定字段白名单校验源文件，最后调用 Docker Compose 归一化。探测确认两个环境修订的镜像、服务、内部网络、健康检查及命名卷一致；仅 `APP_MODE` 随环境变化。缺参、越界参数、额外参数、非合成秘密输入、镜像替换、其他环境变量变化及卷拓扑变化均被拒绝。

本次记录到以下拒绝位置：

|输入|实际拒绝位置/原因|
|---|---|
|重复 YAML 键|第 3 行，`api` 重复|
|插值|`$.services.api.image`；不读取 shell 或 dotenv 继承值|
|`include` / `extends` / `profiles` / `build` / `privileged` / `network_mode` / `devices`|分别在对应根字段或服务字段拒绝|
|外部环境文件|`$.services.api.env_file` 拒绝|
|Docker socket 字符串和挂载|分别在 `$.services.worker.environment`、`$.services.worker.volumes[0].source` 拒绝|
|宿主 bind mount|`$.services.worker.volumes[0].type` 拒绝|
|未知 Compose 字段|`$.services.api.container_name` 拒绝|
|YAML 锚点/别名和合并继承|第 27 行及第 35 行拒绝|

本探针直接复用了 Compose CLI 的标准配置归一化，以及 PyYAML 解析和 RFC 8785 摘要能力；`x-cloudhelm` 参数位置和最终计划检查由隔离薄适配实现。实际覆盖的子集为固定摘要镜像、服务环境、内部项目网络、受管本地命名卷、健康检查和有限重启策略。未执行 `docker compose up`，因此不证明镜像可拉取、容器可运行、健康行为正确或任何远端环境已部署。短语中包含的 `include`、`extends`、`profiles`、`env_file`、插值、未知字段、任意宿主 bind、外部卷、host network、设备、特权和 Docker socket 均不支持。

## Remote Agent 观察

[remote_probe.py](../../../scripts/p0/remote_probe.py) 仅在显式 `--local-seam` 下运行。默认入口实际返回 `BLOCKED`。探针创建 loopback HTTP Hub 夹具和独立运行的 Remote Agent 探针子进程；Hub 仅登记固定的 `p0-isolated-probe` 测试批准记录，并按完整计划、操作/步骤/输入摘要、执行器实例、环境修订、代次、前序结果摘要和当前状态摘要在线签发短期许可。Ed25519 私钥在临时目录内生成并在进程退出后清理，验证密钥不进入命令输出。Remote Agent 探针以 SQLite `FULL` 同步持久化操作、步骤、许可回执、子进程事实和占用标记；真实子进程只把临时测试账本中的 counter 加一。

运行时间：`2026-10-13T04:37:27Z` 至 `2026-10-13T04:38:01Z`。实际观察为 9 次唯一许可签发、counter 最终值 6；测试中相同许可请求重投返回原 grant，同一操作身份搭配不同摘要返回冲突。执行内容如下：

|场景|实际观察|
|---|---|
|完整计划|两个步骤各先在线取得许可，再分别运行一个真实本地子进程|
|Hub 在步骤间失联|首步完成，第二步保持 `waiting_authorization`，counter 未增加|
|重复计划与回执丢失|重投不重复已完成副作用；进程在持久结果后退出模拟回执丢失，新进程从 SQLite 查询到原结果|
|同一 `operation_id`、不同 `plan_digest`|返回冲突，未启动子进程|
|取消|活动子进程运行期间，占用标记仍为真；确认子进程退出后才释放，并阻止后续步骤|
|过期许可|从 loopback Hub 在线收到签名许可后，在启动前拒绝|
|时间边界|`now + uncertainty == expires_at` 拒绝；超过接受至启动窗口的 `5.001s` 拒绝；带正误差的 5 秒边界向量也拒绝|
|Remote Agent / Hub 重启|在许可接受但尚未登记物理 intent 时终止 Agent，再轮换 Hub 临时签名材料和时间纪元；旧许可验证失败，持久账本记录其失效，新 Agent 取得新许可后才启动|

实验使用真实 loopback HTTP 请求、Ed25519 签名校验、独立 Agent 子进程、计数副作用子进程和临时 SQLite 账本。签名材料与时间样本均为本地实验夹具；同机单调时钟读数不能证明时钟误差上界。测试不包含 TLS、真实 Hub 身份体系、独立机器、实际网络中断路径、生产资源预留账本或数据库迁移。无法证明时间误差和来源时，真实普通远端许可/新步骤入口继续阻断；没有可调用的本机应急启用入口。

## 支持范围、未决输入与复核

本次可直接复用的是实际 Compose CLI 归一化、Pydantic 对实验计划形状/摘要的定向校验、RFC 8785 规范化摘要，以及 Python/SQLite/子进程在此 WSL 隔离环境中的行为。Compose 参数映射、短期许可签名校验和远端账本只是待评审薄适配，不是可直接复用的产品接口。Schema [remote-plan.schema.json](../../../packages/contracts/p0/remote-plan.schema.json) 标为 P0 实验草案；尚未冻结正式步骤类型、身份/权限策略、可信时间协议、部署结果语义或生产兼容窗口，留待 P0.3 与后续实现决定。

P0.2 的真实参照输入和独立拓扑仍缺失：当前没有 `docs/implementation/reference-chain.md`、`examples/standalone-project/` 或 `docs/decisions/p0/topology.md`；没有可核验参照源码/初始 commit，也没有独立 Linux 目标机器的网络、身份、DNS、TLS、资源和支持组合证据。此记录只关联到 [PROJECT_PLAN.md 的 P0.2](../../../PROJECT_PLAN.md) 与 [PROJECT_PROGRESS.md 当前阻塞](../../../PROJECT_PROGRESS.md)，不替代 P0.2-01/-03 取证。独立机器交付与时间误差证明必须在实际目标和适用负责人到位后另行验证。

|事项|责任角色|复核点|
|---|---|---|
|Compose 子集、字段位置和参数契约|技术负责人、Compose/交付负责人|P0.2 参照输入到位后，对照真实项目复核；P0.3 冻结前确认拒绝清单|
|Remote Agent 身份、许可、账本和停止证据|执行器/交付负责人、安全负责人|取得可认证 Hub 与独立执行器后重新建立证据；P0.3 决定身份/摘要/时间域前不开放生产入口|
|独立机器、网络和目标能力|基础设施负责人、P0.2 项目/验收负责人|P0.2-03 补齐真实拓扑及实际支持矩阵后核验；由项目负责人决定阶段出口|

## 可复现命令

```powershell
wsl.exe -d Ubuntu-24.04 --cd /mnt/e/Project/CloudHelm -- /home/cloudhelm/.local/bin/uv run python scripts/p0/compose_probe.py
wsl.exe -d Ubuntu-24.04 --cd /mnt/e/Project/CloudHelm -- /home/cloudhelm/.local/bin/uv run python scripts/p0/remote_probe.py --local-seam
```

两条命令均以零退出码完成。本次只运行这两个计划要求的定向探针；没有运行全量测试、容器部署、生产动作、独立机器验收或本机应急流程。
