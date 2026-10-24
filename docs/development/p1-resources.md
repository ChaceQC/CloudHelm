# 共享宿主资源与 Runner 开发说明

当前开发基线为 `0.4.0`，执行协议 `p1-resources-r1`，业务迁移 `0005_p1_3_resources`。环境、锁定依赖和数据库角色使用 [Hub 开发说明](p1-hub.md)；使用新隔离库，`initialize` 不自动升级旧安装。

## 1. 注册与申请

由基础设施维护者准备 Linux 原生文件系统中的私有 JSON（目录 0700、文件 0600、单链接、无符号链接），严格对应 `modules.execution.cli.LocalRunnerConfiguration`：`pool`、`runner` 和可信固定 `argv`。配置不存秘密、数据库 URL 或业务数据；镜像预先加载并绑定 image ID，argv 不接收用户命令或秘密。

`pool` 沿用 P0 `HostResourcePool` 的宿主、预算、实测总容量、未知占用上界与证据引用，再固定 Hub incarnation/资源代次。`runner` 绑定同一宿主/池、执行器身份、最大向量、CPU period、镜像/配方摘要和能力证据。每个实际独立节点单独核验；同宿主全部 Runner 必须列入同一池。注册值不能靠重复调用改变，P1.3-02 前拒绝原地重配。

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

本适配器只执行配置固定、只读根、断网、无宿主卷的 scratch 资源组；`/work` 与 `/dev/shm` 总字节硬限同时受父组内存/PID/CPU 硬限约束。现有 P1.2 构建、持久数据和缓存不自动变成该池的受管写入者；通用后端必须先补齐覆盖全部写入路径的适配与重新核验，不共用未经登记的空闲额度。

历史 `check_resources` 的 PostgreSQL/SQLite/cgroup 整套方法及专用夹具已从当前分支删除。实际结果与固定输入继续见 [P1.3-01 记录](../acceptance/p1/p1-3-01.md)，复现时按 InputSet 的 `source_commit` [独立检出](p0-seams.md#取回历史方法)。

当前决定契约检查保留资源准入、未知调整与物理释放的纯函数边界，命令见[精简验证入口](checks.md)；它不运行实际容器、内核限额或共享宿主竞争，不能替代历史物理方法。P1.3-02 的调整、分维释放、磁盘保留和 Compose 解析，以及 s2413/独立机器/原生和人工验收仍有各自前置。
