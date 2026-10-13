# SDK-05 检查点与保留验收卡

**状态：部分验证；敏感输入默认序列化边界未通过，相关入口保持受限。** 本卡只覆盖隔离 WSL 中 DBOS 3.2.0 的小型工作流探针，不构成产品验收。

## 固定候选与环境

- 工作区：`E:\Project\CloudHelm` 映射到 WSL `/mnt/e/Project/CloudHelm`；Ubuntu-24.04 / Python 3.12.13。
- 候选组件：DBOS 3.2.0；PydanticAI 2.55.0；SQLAlchemy 2.1.4；psycopg 3.3.6；PostgreSQL 16.13。
- PostgreSQL 位于本地 trust 模式的临时 `tmpfs` 容器，绑定 `127.0.0.1:55432`；容器预算为 1 CPU、256 MiB。没有读取真实模型配置，也没有调用模型提供方。
- 业务探针 schema 为 `p0_recovery`，DBOS 通过 `DBOS.migrate()` 管理独立系统 schema `dbos_p0_recovery`。本次 DBOS migration marker 为 `123`，由迁移完成后的只读版本查询取得；未直接写 DBOS 内部表，也未用内部表实现业务行为。
- 本地候选应用版本：`p0.1-recovery-999ad31eecaf`。Git `HEAD` 为 `c7da7fb423cf37a76fa11006e0986e2a572b052d`，本卡对应的源码尚未提交；当前证据只适用于本工作树。
- 权威依据：[D02 §8、§12.2](../../design/02-execution-recovery.md)、[D06 §2.2](../../design/06-implementation-validation.md)。

## 固定输入与实验方法

InputSet 使用固定摘要 `e6d5ed9083a7cd08208faf69a1f531697453849af0c9e014b078dae58634dbbc`、合成 `secret_ref`、合成 `blob_ref` 以及 25 MiB 大对象的长度元数据；没有传入秘密值或大对象字节。输入 canary 和错误 canary 都是明确标记的非凭据合成字符串。

探针在 [probe_recovery.py](../../../scripts/p0/probe_recovery.py) 中使用 DBOS 公共 `migrate`、workflow、step、工作流查询、重启恢复、查询与清理接口。业务结果只由 `p0_recovery.workflow_results` 按稳定 `operation_id` 幂等登记。

命令：

```powershell
wsl.exe -d Ubuntu-24.04 --cd /mnt/e/Project/CloudHelm -- bash -lc 'uv run python scripts/p0/probe_recovery.py'
```

最终记录时间为 `2026-10-13T04:42:10Z`（Asia/Shanghai `2026-10-13 12:42:10`），探针 `run_id=999ad31eecaf`；对应 recovery workflow 为 `p0r-999ad31eecaf-recover`，业务操作为 `operation-999ad31eecaf-checkpoint-gap`。

## 实际观测

| 场景 | 预期 | 实际结果 |
|---|---|---|
| 成功检查点与引用 | 持久输入/输出只含有界字段、摘要及引用 | workflow 和 step 输出字段均在探针 allowlist 内；记录 `secret_ref`、`blob_ref`、摘要和长度元数据，没有秘密值或 blob 字节。此项只说明该合成输入形状，不证明外部制品存储读取或正式脱敏能力。 |
| 业务提交后、DBOS step checkpoint 前崩溃 | 原身份恢复时核对业务记录，不能重复写入 | worker 进程以 SIGKILL 结束，退出码 `-9`；杀进程前业务行已提交且处于 `committed_before_checkpoint`。该 workflow 在重启前仍为 `PENDING`。使用相同 executor identity `999ad31eecaf-worker-a` 启动新进程后，同一 workflow ID 达到 `SUCCESS`；最终 `recovery_attempts=2`，结果标记复用既有业务记录，`write_count=1`。 |
| 失败与重试 | 故障事实可核对，重试只按稳定身份推进 | 合成失败 canary 出现在 DBOS 公共 workflow 状态的终端错误中；retry step 的业务观测次数为 2，最终 workflow 为 `SUCCESS`，结果只返回有限状态。 |
| 参数序列化 | 持久参数仅可为允许字段 | 公共 `list_workflows(load_input=True)` 返回值中可见合成参数 canary；可见内容由 DBOS 按输入原值保存，默认序列化没有替调用方脱敏。该值为非凭据 canary；未传入真实秘密，因此没有声称观察到真实秘密泄露。 |
| 错误序列化 | 错误文本不得意外携带秘密 | 公共 workflow/step 查询可见合成错误 canary。真实异常文本必须按敏感持久数据处理，不能让凭据进入异常消息。 |
| 清理窗口 | 仍等待/恢复的引用保留；无引用的完成历史可按 SDK 能力清理 | PENDING recovery workflow 在重启前仍可查询，探针没有对它调用删除；完成且无等待引用的 control workflow 通过 `DBOSClient.delete_workflow()` 删除，随后公共查询不再返回该项。此结果证明探针按状态选择清理；不证明 DBOS API 会拒绝调用方误删活动工作流。 |

DBOS migration marker `123` 通过迁移后只读版本元数据取得。所有工作流/step 历史观测通过 SDK 公共查询接口完成。探针不直接查询内部 workflow/step 表。

PydanticAI 2.55.0 的静态源码核对位置为 `.venv/lib/python3.12/site-packages/pydantic_ai/durable_exec/dbos/_durability.py:41-46`、`.../_agent.py:200-206`。`DBOSDurability` 将模型及 MCP I/O 放入 DBOS steps；官方 workflow wrapper 的输入包含 `Conversation` 和 `message_history`，源码未显示该边界会自动裁剪或脱敏调用方历史。未运行真实 Agent 或模型请求，因此这是版本绑定的静态观察，不是 adapter 运行验收。

最终探针后，另用 WSL `uv run python -` 执行一次性安全清理：先通过 DBOS 公共查询确认两条早期探针记录为 `ENQUEUED`，并通过本卡业务 schema 确认对应 operation 行数为 0；分别调用 `cancel_workflow()`，观察状态到 `CANCELLED` 后才调用 `delete_workflow()`，最后用 `list_workflows()` 确认记录已不可见。目标仅为未领取、无业务写入的合成 probe workflow：`p0r-257cf7a8c02c-recover`、`p0r-32d46eceb9b7-recover`。两项实际结果均为 `ENQUEUED → CANCELLED → SDK 删除后不可见`。该操作没有写入 DBOS 内部表。

## 复用结论与阻断入口

- DBOS workflow/step/检查点基础能力可在该版本直接复用，但调用方必须只传稳定身份、摘要、有限状态及 `secret_ref`/`blob_ref`。DBOS 默认序列化不作为秘密脱敏层。
- 当前不批准将未裁剪的 PydanticAI `message_history`、`Conversation`、完整上下文或真实凭据直接交给 DBOS workflow。受控 Runtime 入口须先形成有界持久输入，并补做 adapter 恢复与实际存储边界验证；未证明前阻塞相关模型历史恢复及持久执行入口。
- 错误消息、step 返回值、输入和工作流输出都属于持久边界。任何真实秘密都不得通过异常文本、参数、结果或日志进入该边界。
- 清理只在业务引用已解除、工作流终态已核对后使用 SDK 支持的清理接口。DBOS 本身没有替代业务层等待/恢复/去重引用判断的证据。
- 责任角色：Runtime/DBOS 集成负责人、PydanticAI 适配负责人。复核点：P1 任何模型历史或真实副作用入口开放前，补齐有界历史策略、适配器恢复检查和独立存储审查。

## 证据范围与遗留项

- 自动验证：仅上述 WSL/Linux、PostgreSQL 16.13、DBOS 3.2.0 和应用版本；没有跨 worker identity 接管、跨版本恢复、真实秘密、真实 blob、正式 artifact store、生产清理或用户验收结论。
- PydanticAI 只做静态源码核对；没有证明 adapter 下真实请求的参数、重试异常、模型消息和 usage 数据具体写入哪些记录。
- 单独收尾了早期的跨 executor 合成样例 `p0r-3d5572970349-recover`：在 `/proc` 中未发现原 worker 命令行匹配（匹配数 0）后，通过 DBOS 公共查询核对 workflow 原状态 `PENDING`、原 executor `3d5572970349-worker-a`、原 app version `p0.1-recovery-3d5572970349`、固定 operation/digest/合成引用输入及业务 operation `operation-3d5572970349-checkpoint-gap` 的 `write_count=1`。使用原 app version、订阅原队列 `p0-recovery-orchestration` 的新 executor `3d5572970349-resume-worker` 调用 `DBOSClient.resume_workflow()`；该原 workflow ID 于 `2026-10-13T04:47:18.896Z` 达到 `SUCCESS`，结果复用业务记录，`write_count` 仍为 1。该结果是同版本受控 resume，不是同 executor 自动恢复证据。
- 早期探针遗留的两条未领取、无业务行工作流 `p0r-257cf7a8c02c-recover`、`p0r-32d46eceb9b7-recover` 已先经公共 API 取消为 `CANCELLED`，再使用 `delete_workflow()` 删除并通过 `list_workflows()` 确认不可见；不适用于仍带恢复或业务去重引用的记录。
- 其他已完成探针业务行和 DBOS 历史保留在各自隔离 schema 供复核；本卡未执行 schema drop、数据库重置或全局清理。
- 人工验收：未执行。生产、跨版本、真实存储和支持矩阵：未验证。
