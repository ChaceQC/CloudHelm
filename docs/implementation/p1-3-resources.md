# P1.3-01 共享宿主资源协议实施说明

依据 D03 v4.7.2 §4.2～4.4、P0 `p0-resources-r1` 决定及计划 P1.3-01。开发源码 `0.4.0`、工作流应用 `cloudhelm-hub/0.4.0`、业务迁移 `0005_p1_3_resources` 和执行协议 `p1-resources-r1` 分别维护。设计规则未变，本说明不扩大历史候选的证据范围。

## 1. 所有权和持久化

|产物|所有者与行为|
|---|---|
|`resource_pools` / `resource_runners`|`modules/execution/registry.py`；仅维护角色注册，真实宿主唯一归属一池，注册身份及预算不可被请求改写|
|`resource_reservations`|Hub 资源模块；API 新增不可变申请，worker 更新分配与实际回执，全部未释放状态参与计量|
|命令、事件和 Outbox|调用方同一 UoW；当前身份、显式 `operation.request`、Task 控制/输入修订与 UTC 期限先于新申请准入|
|宿主 SQLite|执行器独立持久事实；同一 OS 宿主的 Runner 共用路径、`flock` 启动锁和 `synchronous=FULL` 本地事务|
|实际进程/资源组|`DockerScratchBoundary`；固定镜像/配方摘要、确定性容器名与父组绑定完整预留身份|

Hub 持共享池行锁核算整组容量与冲突，创建预留、命令、领域事件和 Outbox 后提交；提交后才调用执行器。接受、查询、启动和停止不位于 Hub 事务内。资源事件本身不启动新的 DBOS worker；所属业务流程或受控 CLI 负责消费该操作。

执行器先持久接受再返回回执；相同请求恢复原记录，不接受不同摘要覆盖、过时代次或不同 incarnation。启动前在同一本地锁内调用 Hub 当前门禁，再持久保存 launching/ProcessBinding，随后施加物理边界。未知启动只查询原绑定，不重放。启动被门禁拒绝则持久 `closed_unstarted`；晚到请求不能复活该分配。

## 2. 核对及占账

回执只经绑定到已登记 Runner 的受控通道查询，没有公共“提交成功/已停止”接口。回执绑定原身份/摘要和单调序号；Hub 更新分配与观察事件同事务提交。传输失败保留原额度，转入 orphaned；同一已知回执也能解除纯传输未知，不需要伪造更大序号。

reserved、active、releasing、orphaned 都保留占账与互斥键。租约/期限、Task 取消、命令结束和回执丢失不释放容量。本切片只有真实未启动封闭，或完整进程组停止、容器及全部 tmpfs 移除后才整组释放；残留/未知继续全额占账。分维释放、磁盘转记与资源调整由 P1.3-02 承接。

## 3. 首个实际硬限适配器

支持 `linux-systemd-docker-scratch-r1`：Linux/amd64、cgroup v2、systemd Docker 驱动和已加载的固定镜像。维护配置绑定 image ID、配方 argv 摘要、最大向量及 CPU period；普通申请不传入 argv、镜像、路径、挂载、Docker 选项或权限布尔值。

父 slice 对全部容器子进程施加 CPU quota/period、memory.max、memory.swap.max=0 和 pids.max。沙箱使用 UID/GID 65534、只读根、断网、全 capabilities drop、no-new-privileges、无宿主挂载、无 Docker socket、关闭容器日志。可写 `/work` 和 `/dev/shm` 仅为固定总字节上限的 tmpfs，且同时计入组内存；不写宿主构建缓存、镜像层或工作区。镜像缺失、已有可写 Volume、非匹配能力、物理余量不足或无法施加硬限时拒绝。

Docker 元数据与受控账本属于预留前排除的平台开销，不将该适配器声称为覆盖任意 Docker 构建/镜像加载的磁盘配额。P1.2 既有构建/环境夹具维持原独立验证组合；不能在未经重新核验池外及未知占用时与本池混跑。通用构建后端和跨真实机器传输不由本次 scratch 证据放行。

## 4. 兼容和验证边界

`0005` 从 `0004` 线性新增三张表，固定 DDL 不读取未来应用 metadata；旧安装由启动基线明确拒绝，本次未执行旧库升级或降级。原 P0 契约与快照未修改。Hub HTTP 快照增加申请和查询，原 API 的领域语义保持。

本机 OS 身份来自 `/etc/machine-id` 的不可逆摘要，基础设施仍须核验其物理宿主归属。该摘要不能证明两台虚拟机有独立物理预算；不以 Runner 名称、PID、Docker daemon 或 WSL 名称复制容量。

方法、固定输入和退出映射见 [P1.3-01 记录](../acceptance/p1/p1-3-01.md)，命令和故障处置见 [开发说明](../development/p1-resources.md)。WSL 开发验证、s2413 安装、独立机器交付与人工验收分别记录。
