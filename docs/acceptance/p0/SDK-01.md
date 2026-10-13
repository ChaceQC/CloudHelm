# SDK-01 事务交接验证卡

## 卡片状态

**已验证（窄范围）**。本卡只覆盖同一 PostgreSQL 数据库、业务 schema 与 DBOS 系统 schema 分离的短事务交接样例；不代表业务产品模块、跨数据库 Outbox 或生产部署已通过。

## 验证目标与责任

验证一个固定的 `end_run` 命令在 Task 状态、AgentRun 状态、Operation、命令去重结果、事件、WorkflowBinding 和 DBOS 工作流入队之间共享一个由调用方持有的事务；在四个写入阶段注入异常后全部回滚。成功提交后模拟丢弃回执，同身份同摘要重投返回已保存结果且两个业务版本各推进一次；同身份异摘要被拒绝。

执行责任：技术、Runtime 与数据库负责人。复核责任：独立复核者核对固定身份/摘要、事务回滚观测和 DBOS SDK 公有查询证据。失败时阻塞所有依赖同事务交接的应用命令与工作流入口。

## 固定输入

每次探测启动时生成一次短 `run_id`，其后四个失败注入、成功提交、回执丢失重投和异摘要请求共用同一 `command_id`、`operation_id`、调用者、scope、幂等键、Task/AgentRun、event_id、workflow_id 与 RFC 8785 请求摘要。脚本输出本次全部身份和摘要，便于复核。规范化信封固定包含摘要/请求 schema 修订、调用者、scope、target（含 Operation ID）、命令类型、预期 Task/AgentRun 版本及 outcome；摘要为 `sha256:` 加 JCS UTF-8 字节的 SHA-256 小写十六进制值。

测试起始状态为 Task `active/version=7`、AgentRun `running/outcome=null/version=3`。成功命令应得到 Task `active/version=8`、AgentRun `succeeded/outcome=submitted/version=4`，并产生各一条 Operation、命令结果、事件、WorkflowBinding 和 DBOS workflow。

## 实际版本与环境

|项目|实际值|
|---|---|
|运行环境|WSL Ubuntu 24.04.4 LTS、仓库映射 `/mnt/e/Project/CloudHelm`、uv 工程 `.venv`|
|Python / uv|Python 3.12.13 / uv 0.11.29 (`/home/cloudhelm/.local/bin/uv`)|
|DBOS / SQLAlchemy / 驱动|DBOS 3.2.0 / SQLAlchemy 2.1.4 / psycopg 3.3.6|
|摘要 / 数据库|rfc8785 0.1.4 / PostgreSQL 16.13（临时容器 tmpfs）|
|业务 / DBOS schema|`p0_transaction` / `dbos_p0_transaction`，同一数据库内分离|
|运行拓扑|本探测进程中的单个 DBOS worker；`cloudhelm-p0-postgres-1` healthy，绑定 `127.0.0.1:55432`；Conductor 未配置|

## SDK 接口核验

从当前安装的 DBOS 3.2.0 源码与签名观察：

```text
DBOSClient.enqueue_in_transaction(self, conn_or_session, options: EnqueueOptions, *args, **kwargs)
```

方法文档说明调用方持有 SQLAlchemy 同步事务并负责 commit/rollback；返回的 handle 只在事务提交后有效；连接必须指向 DBOS 系统数据库。文档还明确 async SQLAlchemy 应使用 `await async_conn.run_sync(lambda sync_conn: client.enqueue_in_transaction(sync_conn, options, ...))`，普通 `enqueue_async` 不参与现有业务事务。

DBOSClient 构造文档说明它不会运行系统 schema 迁移。探测仅通过 DBOS 应用 `DBOS.launch()` 的公开启动路径并显式设置 `run_migrations=True`、`dbos_system_schema=dbos_p0_transaction` 初始化系统 schema；未读取或直接写入 DBOS 内部表。回滚后使用 `DBOS.get_workflow_status(workflow_id)` 的公开接口判定不存在；提交后使用 `DBOSClient.retrieve_workflow()`、handle `get_status()` 和 `get_result()` 查询。

队列配置通过公开 `DBOS.register_queue()` 注册，实际顺序为 `DBOS.launch()` 之后；将它提前到 `launch()` 前会因 system database 尚未启动而失败。未配置 Conductor，也未启用第二个 worker。

## 故障注入与实际观测

|注入点|预期|实际结果 / 证据|
|---|---|---|
|两个领域状态更新后（`domain_writes`）|命令结果、Operation 和 Task/AgentRun 更新均回滚，事件、绑定、入队不可见|通过；Task `active/7`、AgentRun `running/outcome=null/3`；命令/Operation/事件/绑定行均 0；DBOS 公有状态不存在|
|事件写入后（`event`）|命令、Operation、两个领域状态和事件、绑定、入队整体回滚|通过；Task `active/7`、AgentRun `running/outcome=null/3`；命令/Operation/事件/绑定行均 0；DBOS 公有状态不存在|
|WorkflowBinding 写入后（`workflow_binding`）|上述全部记录与入队整体回滚|通过；Task `active/7`、AgentRun `running/outcome=null/3`；命令/Operation/事件/绑定行均 0；DBOS 公有状态不存在|
|`enqueue_in_transaction` 返回后（`enqueue`）|所有业务记录回滚；DBOS 公有状态查询无 workflow|通过；Task `active/7`、AgentRun `running/outcome=null/3`；命令/Operation/事件/绑定行均 0；DBOS 公有状态不存在|
|async `run_sync` 入队返回后|外层 AsyncConnection 回滚全部参与记录；DBOS workflow 不可见|通过；Task `active/7`、AgentRun `running/outcome=null/3`；命令/Operation/事件/绑定行均 0；DBOS 公有状态不存在|

成功用例提交后，在返回前模拟丢弃回执。相同身份/摘要重投读取原命令结果，没有再次入队；Task 版本 `7→8`、AgentRun 状态为 `succeeded`、独立 outcome 为 `submitted`、版本 `3→4`，Operation、事件与 WorkflowBinding 各一条。事件为 `agent_run.succeeded`，其 outcome 字段为 `submitted`。DBOS 公有查询返回 `SUCCESS`，`get_result()` 与 request digest 相同。同身份不同摘要在触碰领域写入前抛出冲突，已提交结果保持不变。

## 复用结论与限制

|能力|结论|依据 / 适用限制|
|---|---|---|
|调用方 SQLAlchemy 同步 Connection 上的事务入队|直接复用|四个失败点均观察到业务记录和 DBOS workflow 整体不可见；提交后 workflow 可由 SDK 公有接口查询|
|同库不同 schema 的业务/DBOS 原子提交|直接复用，限同一 PostgreSQL 数据库|业务 schema `p0_transaction` 与 DBOS schema `dbos_p0_transaction` 分离；仅覆盖同一个 PostgreSQL 事务|
|规范化摘要及同键摘要冲突|直接复用 JCS + SHA-256；应用负责去重和冲突规则|rfc8785 0.1.4 的 RFC 8785 序列化；不替代完整请求 schema 默认值/引用解析设计|
|回执丢失后的应用命令去重|应用命令表薄适配|同身份同摘要返回原 JSON 结果；同身份异摘要拒绝。DBOS 重复 Workflow ID 行为不替代业务摘要校验|
|AsyncConnection 桥接|直接复用 `AsyncConnection.run_sync`|psycopg 3.3.6 async 连接桥接入同一业务函数与 DBOS 事务入队；不调用 `enqueue_async`|
|跨数据库、外部副作用、真实领域模块与生产权限|不支持 / 未覆盖|需要事务 Outbox、稳定身份和实际结果核对；本卡不据此宣称跨机器 exactly-once|

## 复现命令与记录

从 WSL Ubuntu 24.04 的仓库根目录运行：

```bash
uv run python scripts/p0/transaction_probe.py
```

数据库必须是 `infra/p0/compose.yaml` 声明的本任务临时 PostgreSQL 16.13 容器（tmpfs），并在运行前确认健康。每次运行会重建仅属于本探测的 `p0_transaction` 业务 schema，以防脚本迭代遗留表结构；`dbos_p0_transaction` 只由 DBOS SDK 迁移管理并保留。stdout JSON 状态为 `passed`，进程正常结束；输出不包含 DSN 或秘密。

|证据项|实际值|
|---|---|
|执行日期|2026-10-13（Asia/Shanghai）|
|实际命令|`/home/cloudhelm/.local/bin/uv run python scripts/p0/transaction_probe.py`，cwd `/mnt/e/Project/CloudHelm`|
|退出结论|进程退出码 `0`、`PASS`；stdout `status=passed`，四处同步回滚、回执重投、异摘要拒绝和异步桥接回滚均断言通过|
|run_id|`353e9a65811a`|
|主 command / operation / workflow|`sdk01-353e9a65811a-command` / `sdk01-353e9a65811a-operation` / `sdk01-353e9a65811a-workflow`|
|固定 request_digest|`sha256:15e76be9e1579e44a56e5e898cc74dc50a3e30620ae90ccf0629be8b4acdd54a`|
|成功后的 AgentRun|status `succeeded`，outcome `submitted`，version `3→4`；事件 `agent_run.succeeded` 带 outcome `submitted`|
|异摘要冲突输入|`sha256:04e11668a0f812f45323734b087c763fee765f5c0d8a64e8314cd40f45456a17`，拒绝且原结果未变|
|AsyncConnection 桥接 command / operation / workflow|`sdk01-353e9a65811a-async-command` / `sdk01-353e9a65811a-async-operation` / `sdk01-353e9a65811a-async-workflow`|
|AsyncConnection 桥接摘要|`sha256:f053c8f9e2ed7a1e4054883eecea132c8671372c56bcb136946e3653aa74bd2d`|

执行调整记录：首次运行在事务场景开始前发现 `DBOS.register_queue()` 必须在 `DBOS.launch()` 后调用；随后一次运行在 async event loop 中调用同步 `DBOS.get_workflow_status()` 被 SDK 拒绝；再一次运行在同一 tmpfs 数据库上遇到前次脚本版本留下的旧业务表结构（`event_log.operation_id` 尚不存在）。脚本现于每次运行前只重建自有 `p0_transaction` schema，保留 DBOS schema 由 SDK 管理。集成复核还将 AgentRun 状态修正为 `succeeded`，将 `submitted` 保留为独立 outcome；最终命令验证 status/outcome 与事件内容均正确。最终运行的四个同步故障点、回执重投、异摘要拒绝和异步桥接回滚全部通过；以上探测器/schema 调整不作为事务能力失败证据。

## 复核点

1. 核对 `request_digest` 是相同固定 JCS 信封的 SHA-256；五类事务尝试（四处失败与成功）使用同一身份。
2. 每次回滚后核对 Task/AgentRun 仍为初始状态和版本，命令、Operation、事件、WorkflowBinding 查询均无本命令记录，DBOS 公有状态返回不存在。
3. 成功后核对 Task/AgentRun 版本各仅推进一次、Run status/outcome 分列保存、Operation/事件/绑定各一条、丢回执重投结果完全相同，工作流经 SDK 公有 API 可查且结果匹配摘要。
4. 核对异摘要冲突没有改变已提交结果，并确认 async `run_sync` 回滚后无 workflow。
5. 仅将本卡实测结论用于同版本、同一 PostgreSQL 数据库事务和本卡输入；产品模块接入仍需在 P1.1 重新验证应用命令边界。
