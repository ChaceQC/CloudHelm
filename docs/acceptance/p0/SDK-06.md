# SDK-06 恢复与容量验收卡

**状态：部分验证；DBOS 本地恢复与控制接口有窄范围证据，物理资源准入仍未验证。** 本卡只适用于所列 WSL 与 SDK 版本。

## 固定候选与环境

- 工作区：`E:\Project\CloudHelm` 映射到 WSL `/mnt/e/Project/CloudHelm`；Ubuntu-24.04 / Python 3.12.13。
- 候选组件：DBOS 3.2.0；PydanticAI 2.55.0；SQLAlchemy 2.1.4；psycopg 3.3.6；PostgreSQL 16.13。
- PostgreSQL 位于本地 trust 模式的临时 `tmpfs` 容器，绑定 `127.0.0.1:55432`；容器预算为 1 CPU、256 MiB。DBOS 业务与系统数据分属 `p0_recovery` / `dbos_p0_recovery` schema；系统 migration marker 为 `123`。
- 本地候选应用版本：`p0.1-recovery-999ad31eecaf`。Git `HEAD` 为 `c7da7fb423cf37a76fa11006e0986e2a572b052d`，对应源码尚未提交；证据只适用于本工作树。
- 权威依据：[D02 §6、§7、§11](../../design/02-execution-recovery.md)、[D06 §2.2](../../design/06-implementation-validation.md)。

## 固定输入与命令

固定工作流输入使用 run ID `999ad31eecaf`、固定请求摘要、合成 secret/blob 引用以及一次 30 秒的 DBOS durable sleep。没有连接模型提供方、没有产生模型费用，也没有运行实际安装/构建/测试进程。

探针：[probe_recovery.py](../../../scripts/p0/probe_recovery.py)、[recovery_workflows.py](../../../scripts/p0/recovery_workflows.py)。执行命令：

```powershell
wsl.exe -d Ubuntu-24.04 --cd /mnt/e/Project/CloudHelm -- bash -lc 'uv run python scripts/p0/probe_recovery.py'
```

实际完成时间 `2026-10-13T04:42:10Z`（Asia/Shanghai `2026-10-13 12:42:10`）。固定探针 `run_id=999ad31eecaf`，DBOS app version `p0.1-recovery-999ad31eecaf`。

## 实际观测

| 场景 | 预期 | 实际结果 |
|---|---|---|
| 单 worker 重启恢复 | 原 workflow ID 恢复，业务结果按稳定身份查询/复用 | 同一 executor identity `999ad31eecaf-worker-a` 的独立 worker 进程以 SIGKILL 结束；以相同 identity 启动新进程后，同一 workflow 达到 `SUCCESS`，`recovery_attempts=2`。这证明该版本/同 executor identity/同 app version 的此固定故障输入。不同 executor identity 的旧 workflow 受控续接另见 [SDK-05](SDK-05.md)，不可据此推断跨版本恢复。 |
| priority 排序 | 用逆序入队排除 FIFO，记录 priority 的实际调度顺序 | worker 启动前先入队 `priority=9`，再入队 `priority=1`；两者开始顺序为 `1`、`9`。在该单 worker、同队列、两个候选任务的范围内，较小数值先开始。测试不足以证明抢占、长队公平性或所有负载下的优先级语义。 |
| model queue 占满 | 第二个模型槽工作流排队；独立控制仍能处理 | `model-calls` 队列 `worker_concurrency=1`、`global_concurrency=1`。首个固定 sleep 工作流已领取时，第二个保持 `ENQUEUED` 且 `dequeued_at=null`。此时 control 队列工作流 `SUCCESS`，耗时 1044.5 ms。 |
| 查询与取消 | 控制请求不因模型队列占满而阻塞 | 通过独立 `DBOSClient` 直接查询运行中 workflow 为 `PENDING`，耗时 5.3 ms；`cancel_workflow()` 调用耗时 4.8 ms，最终状态为 `CANCELLED`。本场景没有真实物理子进程，因此不把 DBOS 取消等同于物理进程停止。 |
| 实际资源准入 | 队列准入不能冒充 Runner/宿主资源预算 | 未实现/未调用 ResourceReservation、物理资源账本、Runner 或真实模型请求；无实际硬限或跨 worker 并发证据。 |

运行配置为 DBOS executor 线程数 2、system DB pool 4、polling concurrency 1。所有队列每次探针用独立名称；priority 对照在 worker 启动前同时处于 `ENQUEUED`。排队与控制工作流证据只覆盖这个本地 single-worker 组合。

## 复用结论与阻断入口

- DBOS 3.2.0 的公开 `Queue`/`register_queue` 接口支持 `worker_concurrency` 和 `global_concurrency`；`EnqueueOptions.priority` 是公开字段。当前输入下观察到数值 1 先于 9。
- 控制队列与 DBOSClient 查询/取消在 model queue 槽占用时仍可响应，支持继续采用受控独立控制容量和独立 client pool 做后续集成验证。
- 这些限制只调度 DBOS workflow。它们不证明物理 Runner、宿主、模型请求数、费用预算、队列外异步操作或多 worker 全局上限；不得把 DBOS 队列作为 ResourceReservation 替代。
- 真实模型入口、真实并发上限和共享宿主硬预算在 ResourceReservation/业务预算接缝形成前保持关闭。SDK-02 的实际供应商拦截、usage 与费用核算也不由本卡证明。
- 责任角色：Runtime/DBOS 集成负责人、共享资源账本与 Executor 负责人。复核点：任何真实模型/Runner 副作用入口开放前，补做业务准入/物理账本交接、跨 worker 全局限制核验、实际进程事实及相应模型预算证据。

## 限制与未执行范围

- 本卡覆盖同 executor identity 重启。跨 executor identity 的同版本公开 resume 仅有 [SDK-05](SDK-05.md) 所列单一合成记录；本卡没有重复该场景。本地/远端 Conductor 故障转移、跨版本恢复、多个 DBOS worker、新旧应用并存均未验证。
- 不证明供应商吞吐、计费、取消供应商请求、物理 Runner 停止或任何生产容量指标。
- 浏览器、Desktop 原生、独立机器、生产部署及人工验收：未执行。
