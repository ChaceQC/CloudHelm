# T-SIM-06 共享资源集成

依据 D03 §4.2～4.4、D02 的稳定身份与恢复门禁及 PROJECT_PLAN 的 06a～06e。源码和工作流应用分别为 `0.5.0` / `cloudhelm-hub/0.5.0`，业务迁移为 `0006_p1_3_resource_lifecycle`。资源 r1 保留，持久磁盘回执和受管后端使用 `p1-resources-r2`；开发存储的新登记使用 `p1-development-storage-r3`。版本类别独立维护。

## 路径与所有权

|路径|原执行/写入位置|集成后的所有权与边界|
|---|---|---|
|固定候选构建|`engineering_build_runner`、backend/frontend BuildKit、镜像导出/加载|`engineering_resources.build` 先准入整组；Docker、独立 containerd、BuildKit 和子进程归同一父组；内容库在登记 backing 内。完成回执在整组停止核对之后登记|
|Workspace 依赖安装|`workspace_development_dependencies`、安装 tmpfs、快照归档|必须绑定同一受管父组；安装容器上限受父组约束，已发布快照留在 backing，不另收第二份相同 backing 字节|
|长期服务与数据库|Runtime/Lifecycle、PostgreSQL、迁移、reload 服务与 reader pin|按 environment 的稳定资源身份恢复；查询只观察，suspend 保留原绑定及配额，resume 继续核验原组，dispose 核对全部进程后收束父组|
|工作文件/Git/候选/缓存/制品/数据库目录|`DevelopmentStorage` 的用途目录|同一完整分配 ext4 backing 由唯一 storage owner 占账；目录用途和锁继续独立。保留对象不因进程结束退账，新副本仍受原文件系统上界和剩余空间门禁|
|Docker 内容与运行状态|过去使用宿主 Docker/containerd|新后端显式启动独立 containerd，将其 root 和 Docker data-root 放入 `cache/managed-docker-r1`；运行状态使用 16 MiB tmpfs，两个 daemon 及 shim 同受父级限制|
|内部网络|固定 internal bridge|Root 通道只为同一资源绑定的 internal bridge 允许桥内转发，保留宿主原 FORWARD 策略。规则绑定完整 network ID、binding 和 ifindex；整组停止后只回收自己的规则和接口|
|登记种子与控制账本|既有只读种子、Hub 数据、宿主 SQLite|种子准备仍为可信维护入口；既存内容、平台控制开销及未映射占用在容量证据/U 中明确扣除。不能用目录逻辑上限宣称物理配额，也不把控制账本重复算成沙箱磁盘|

06a 的本机只读观测及旧引用限制见 [进度](../../PROJECT_PROGRESS.md#2026-10-25源码简化专项-t-sim-06)。没有观测到进程不表示既存 backing、业务库或持久工作流可删除；原 8 GiB backing 保留。

## 父子预留与释放

storage owner 只申请磁盘，额度等于 backing 的完整物理字节。创建身份固定在可信工程登记，Hub 和 Runner 都保留该所有者；进程组引用同一 backing，不重复申请这份容量。停止 owner 只把其转为保留占账；本轮不自动 GC 或依据路径消失退账。

首个受管执行配方固定为 4096 MiB、3000m CPU、512 PID、1 个重执行槽，瞬态磁盘上界为 4 GiB + 16 MiB。构建和长期环境共用此配方，子容器的上限由父级合计约束，不另建子账本。使用 4 GiB 开发预算时同时只能接纳一个该配方；suspend 保守保留父组和全部配额，减少空闲占用不是本轮出口。

Hub/Runner 共用 `allocation_from_receipt`。可信停止事实允许归零进程维度；磁盘证据缺失则保留原额，有 r2 剩余字节则只减少已证明回收部分。`releasing` 的磁盘仍参与准入，停止未知仍保留整组。已经封闭的执行不能被晚到 running 回执重新开启。

原地调额明确不支持，返回 `in_place_resource_adjustment_unsupported_stop_then_reallocate`。`resource_adjustments` 独立保存调整身份、规范摘要和原结果；相同输入重投返回原结果，不同输入复用身份拒绝。真正改变额度须先核对停止，再使用新操作/预留身份申请；不创建无证据的 pending 扩额或降低未知占账。

## 启动、恢复和兼容

Root `resource_host` 使用受保护的登记文件和固定 Unix socket。请求只包含动作和身份，不接受路径、命令、秘密、审批布尔值或公共回执。当前权限与 Task/输入/期限门禁在宿主启动锁内重新检查。先持久接受和 launching，再创建实际资源；未知先查原绑定，不再启动第二组。

工程首次申请/启动窗口固定为原命令接受后 2 小时，过期需要新操作；已有运行绑定的查询与安全停止不借此复活普通执行。该窗口是当前固定后端限制，不是远端部署许可或产品响应时限承诺。

Root host 使用独占锁识别活动控制器，只有确认无监听者、原 socket 属于 root 且 inode 未变时才移除崩溃遗留 socket。回执丢失不停止 host；新 host 沿同一 SQLite 和操作身份恢复。完整宿主重启和跨机器恢复仍须对应阶段取证。

工程 r2 登记必须同时绑定 `resource_runner_id`、`storage_runner_id` 和 `storage_owner_reservation_id`。旧 r1 登记、日志及 scratch 协议继续用于查询、停止、核对；旧执行组的新建入口退役，旧 accepted intent 也不能绕过统一准入重新启动。旧构建结果可在原组已核对关闭后回读内容与固定观察，不为查询重启 daemon。

存储 r3 仅允许 root 管理、不可被普通用户写入的指定 Docker 子树产生受控别名挂载；原 r2 的拒绝规则保持不变。Root 对 overlay 的 lower/upper/work 逐项核对真实路径与 backing 设备；普通 reader 核对内核挂载路径和 root 所有权，不读取 daemon 私有内容。其它嵌套挂载或别名仍拒绝。存储维护同时检查持久资源账本，即使 reader pin 或 host 进程丢失，也不能据此卸载仍有未知执行的 backing。

新迁移线性追加，不修改 `0005`；旧库不由 initialize 自动升级。旧安装与在途工作流先按原版本收束和受控迁移方案处理，不由本次版本号自动兼容。Compose 解析、独立机器、Desktop、容量和人类验收保持各自入口；具体方法、实际结果和未执行项只记在进度中。
