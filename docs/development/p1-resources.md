# 共享宿主资源与 Runner 开发说明

当前开发基线为 `0.8.0`，工作流应用单独为 `cloudhelm-hub/0.7.0`，业务迁移 `0009_p1_5_sync`。资源实现及既有证据仍按 `0.5.0` / `0006_p1_3_resource_lifecycle` 的固定输入理解，不追认新验证。原 scratch 的 `p1-resources-r1` 保留；分维释放和受管后端使用 r2。环境、锁定依赖和数据库角色使用 [Hub 开发说明](p1-hub.md)；使用新隔离库，`initialize` 不自动升级旧安装。远端执行组的独立门禁见 [Remote Agent 说明](p1-remote-agent.md)。

## 1. 注册与申请

由基础设施维护者准备 Linux 原生文件系统中的私有 JSON（目录 0700、文件 0600、单链接、无符号链接），严格对应 `modules.execution.cli.LocalRunnerConfiguration`：`pool`、`runner` 和可信固定 `argv`。配置不存秘密、数据库 URL 或业务数据；镜像预先加载并绑定 image ID，argv 不接收用户命令或秘密。

`pool` 沿用 P0 `HostResourcePool` 的宿主、预算、实测总容量、未知占用上界与证据引用，再固定 Hub incarnation/资源代次。`runner` 绑定同一宿主/池、执行器身份、最大向量、CPU period、镜像/配方摘要和能力证据。每个实际独立节点单独核验；同宿主全部 Runner 必须列入同一池。注册值不能靠重复调用改变，当前仍拒绝原地重配。

```bash
# 使用专用 migrator 配置，仅注册证据已核实的池与 Runner。
$UV run --locked python -m modules.execution.cli register --registration-file /private/runner.json
```

HTTP `POST /api/tasks/{task_id}/resource-reservations` 接受 `ReserveResourcesRequest`，需要真实当前会话、显式 `operation.request` 及 `Idempotency-Key`。申请固定 Task 版本、控制/输入修订、UTC 期限、完整资源向量、预留/操作/组身份、目标池/执行器和冲突键；摘要用 `resource_request_digest` 按规范 JSON 计算。HTTP 202 返回可靠预留，不表示已经接受、启动或完成。`GET /api/resource-reservations/{reservation_id}` 经当前 `resource.read` 返回占账状态。

## 2. 受控执行与核对

下列命令属于可信执行器控制进程，使用 worker 数据库角色；不是提供给模型或沙箱的 shell 工具。父级 systemd 资源组需要明确的本机特权控制器；工作负载本身仍为 UID65534。所有同机 Runner 使用同一服务账户及本地账本目录，不复制账本规避容量。

```bash
$UV run --locked python -m modules.execution.cli accept --registration-file /private/runner.json --reservation-id RESERVATION_ID
$UV run --locked python -m modules.execution.cli start --registration-file /private/runner.json --reservation-id RESERVATION_ID
$UV run --locked python -m modules.execution.cli query --registration-file /private/runner.json --reservation-id RESERVATION_ID
$UV run --locked python -m modules.execution.cli stop --registration-file /private/runner.json --reservation-id RESERVATION_ID
```

默认宿主账本在 `/home/cloudhelm/.local/state/cloudhelm/resources/<observed-host-id>/`。CLI 只输出状态、身份、修订、占账和固定错误分类，不输出配置值。注册/查询/接受不会拉取镜像或启动进程；start 再查当前授权、Task、期限、维护基线、能力与物理余量。

回执丢失先 query 原预留，不能创建第二个身份。unknown/orphaned/releasing 必须保留预算与冲突；stop 重试和核对沿用原绑定。容器或组意外消失仍可能有迟到创建，不能将单纯“未找到”改填为未启动封闭。账本丢失、注册冲突、未知磁盘或关闭无法确认时保留现场并停止新准入，不手工删除 SQLite 或原资源组来制造空闲。

## 3. 支持范围与定向方法

scratch 后端只执行配置固定、只读根、断网、无宿主卷的资源组；`/work` 与 `/dev/shm` 总字节硬限同时受父组内存/PID/CPU 硬限约束。固定工程的构建、持久数据和缓存使用下节单独登记的受管后端；其它写入路径须先补齐适配与重新核验，不共用未经登记的空闲额度。

历史 `check_resources` 的 PostgreSQL/SQLite/cgroup 整套方法及专用夹具已从当前分支删除。[P1.3-01 记录](../acceptance/p1/p1-3-01.md)保留实际结果与支持限制；原始 JSON 从 Git 查询，复现时按输入和方法绑定[独立检出](p0-seams.md#取回历史方法)。

当前决定契约检查保留资源准入、未知调整与物理释放的纯函数边界，命令见[精简验证入口](checks.md)；它不运行实际容器、内核限额或共享宿主竞争。T-SIM-06 的资源前置、路径和兼容边界见[实施说明](../implementation/t-sim-06-resources.md)，实际证据见[进度](../../PROJECT_PROGRESS.md#2026-10-25源码简化专项-t-sim-06)。Compose 解析、s2413/独立机器/原生和人工验收仍有各自前置。

## 受管工程执行

新工程使用显式创建的存储 r3：可信维护者在 WSL PID 1 的挂载命名空间执行原 `create-pool` 命令，增加 `--managed-docker`，保留实际容量与安全余量证据。旧 backing 不原地改登记；未知引用仍保留或计入 U，不清理旧数据。

Root host 的受保护 JSON 为 `HostConfiguration`，包含 `registrations` 数组。每项沿用 `pool` 与 `runner`；受管后端不接受 `argv`。至少登记两个 Runner：

- `linux-development-storage-r1`：r2 Runner、真实 storage ref、仅磁盘的 maximum，配方摘要由 `resource_storage.storage_recipe(ref)` 计算，不填写镜像。
- `linux-systemd-docker-development-r1`：同池/同宿主的 r2 Runner、同一 storage ref、固定 `storage_owner_reservation_id`，配方由 `resource_development.development_recipe(ref, owner_id)` 计算；能力须覆盖固定整组向量。

容量、宿主身份、incarnation、代次和 capability evidence 来自实际维护记录；不能复制其它机器的值。池内包括 backing 全额、瞬态磁盘额度、其它未释放分配和 U。4 GiB 池会拒绝两个总硬上限为 5 GiB 的组合，不把队列数量当物理并发。

在原受控数据库角色的秘密文件引用已配置、当前目录为仓库根后，维护者使用锁定环境运行：

```bash
uv run --locked --offline --no-sync python -B -m services.dev-runner.resource_host register --registration-file <private-host-registration.json>
uv run --locked --offline --no-sync python -B -m services.dev-runner.resource_host serve --registration-file <private-host-registration.json>
```

两条均为明确的 root 维护入口，并须与 PID 1 共用挂载视图；不要让普通请求选择文件、命令或宿主目录。host 只开放固定本机 Unix 通道，HTTP 不接收物理回执。Root host 和控制账本的开销属于预先扣除的平台预算。

工程登记改用 `p1-engineering-registration-r2`，保留原 storage/种子引用，并填写已登记的 `resource_runner_id`、`storage_runner_id`、`storage_owner_reservation_id`。API/worker 沿原工程登记入口加载；构建和环境按稳定身份自动申请、投递并查询，缺少登记或未知旧占用时拒绝启动。旧 r1 日志只承接查询、停止和核对。

运行中调额使用新增 `POST /api/resource-reservations/{reservation_id}/adjustments`，正文为 `ResourceAdjustment`，摘要用 `adjustment_digest` 计算。相同 ID/摘要返回原结果，异输入拒绝。当前只允许记录“不变”或明确拒绝原地变更；真正更改资源须停止核对后用新身份申请。进程停止后 backing 仍全额占账，自动 GC、在线扩额及完整宿主故障恢复不在本后端的支持声明中。
