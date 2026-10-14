# P0 隔离接缝使用说明

该工程供开发者复现 P0.1 接缝实验，不是业务 Hub/Runner/Remote Agent 或 Desktop。以 [组件基线](../decisions/p0/component-baseline.md) 的版本和 [六卡及接缝报告](../acceptance/p0/seam-summary.md) 的支持范围为准。

P0.3 的决定模型和不依赖数据库/供应商的窄检查另见 [决定契约使用说明](p0-decisions.md)；复核决定时无需重跑本页历史收费或容器接缝。

## 1. 安装和启动

本机使用 WSL Ubuntu-24.04，仓库在 `/mnt/e/Project/CloudHelm`。从 Windows 启动一个验证期间保持运行的 WSL 终端，或执行 `wsl.exe -d Ubuntu-24.04 --exec /bin/sleep infinity` 保活。所有依赖、SDK、数据库和 Docker 命令在 WSL 内执行。

```bash
cd /mnt/e/Project/CloudHelm
export LANG=C.UTF-8
uv sync --locked
docker compose -f infra/p0/compose.yaml up -d --wait
uv run --frozen python scripts/p0/diagnostics.py
```

`.python-version` 固定 Python 3.12.13；`uv.lock` 固定整个依赖图，避免复现时重新选择间接依赖。uv 的跨盘 hardlink 回退 copy 提示不影响解析结果；如需消除提示可在本次命令使用 `UV_LINK_MODE=copy`，不修改系统环境。

临时 PostgreSQL 限 `127.0.0.1:55432`，无密码 trust、tmpfs 数据、256MiB 内存和 1 vCPU。这是隔离实验数据库，不放真实用户、生产数据或凭据。探测只使用各自的专用业务/DBOS schema；各卡列出它们的实际名字和重置范围。所有脚本使用固定实验输入，不自动连接其他数据库或清理其他项目资源。

## 2. 按需要复现

只运行需要重新取证的卡；输入、代码、依赖、环境或风险没有变化时，不重复执行已取得的实验。

```bash
# 事务、事件、绑定和 DBOS 公有接口原子入队
uv run --frozen python scripts/p0/transaction_probe.py

# Gateway 副作用去重、合法历史和延迟结果
uv run --frozen python scripts/p0/probe_protocol.py

# 检查点、真实 worker 崩溃恢复与控制响应
uv run --frozen python scripts/p0/probe_recovery.py

# 实际 Compose 归一化和受限参数映射
uv run --frozen python scripts/p0/compose_probe.py

# 远端计划、许可和本地账本；仅本机隔离操作
uv run --frozen python scripts/p0/remote_probe.py --local-seam

# 默认不收费的模型边界检查
uv run --frozen python scripts/p0/probe_model.py

# 打印当前公共输入哈希，不读取机器配置
uv run --frozen python scripts/p0/input_manifest.py
```

探测有意使用短固定场景。模型槽满的控制实验、同机计划许可和 Compose 解析均不代替供应商容量、独立 Linux 交付、TLS 身份、可信时钟误差或 Desktop 原生验收。

## 3. 获准的真实模型探测

本轮新增的当前门禁/费用、安全检查点和等待续接方法分别为 `check_admission.py`、`check_checkpoint.py`、`check_continuation.py`，均在同一 WSL 隔离数据库执行；具体命令和有限支持见 [A01 报告](../acceptance/p0/A01.md)。正式产品入口仍须经过 [受支持薄适配决定](../decisions/p0/admitted-runtime.md) 和 P0.3/P1 门禁。

`uv run --frozen python scripts/p0/probe_admitted_stream.py --live` 为固定 SDK-A01-C1 的 4 次获准供应商流输入，已执行；同输入再启动由本地 journal 拒绝收费重放。`connect_live_continuation.py` 查询该输入的原 Operation 并接到同库等待/新 Run，新增供应商请求为 0。查询/费用 journal、未知记录和恢复引用不能为重跑而删除；环境重建后缺少原对象时该查询应失败，不能补造成功。

2026-10-14 的 P0.1-A02 更新了断流方法；旧 `--live` 命令不会隐式开启新输入，严格 r2 必须显式给出 `--live-revision r2`。恢复使用独立固定批次：四个场景分别保留一条本地尝试，其中仅 allow 允许一条真实 HTTP；取消、撤权和 unknown 占账导致预算不足必须零 HTTP。原 r1 journal 与未知记录保持原身份，不删除以绕过上限。方法和实际支持范围见 [A02](../acceptance/p0/A02.md)。

```bash
# 不收费：断流判定方法的定向拒绝检查
uv run --locked --offline python scripts/p0/check_stream_assertions.py

# 不连接供应商：真实 SDK 路径 + 固定 HTTP 夹具 + 隔离 PostgreSQL 门禁
uv run --locked --offline python scripts/p0/check_admitted_paths.py

# 消费瞬态输入后的成功/异常检查点；需要上述隔离 PostgreSQL
uv run --locked --offline python scripts/p0/check_checkpoint.py

# 固定授权输入：自身 worker 崩溃恢复后，最多 1 条真实新模型请求
uv run --locked --offline python scripts/p0/probe_admitted_recovery.py --live

# 新固定 r2 流输入：最多 4 条真实请求；既有批次拒绝重放
uv run --locked --offline python scripts/p0/probe_admitted_stream.py --live --live-revision r2
```

恢复脚本只杀自身创建的 worker，并确认退出后重新启动；不结束其他 worker 或 WSL。SDK 路径夹具的 usage 不作为供应商证据；受控摘要 Agent 的压缩请求和后续请求均经过同一门禁，不宣称 SDK 内建自动压缩能力。DBOS 3.2.0 公共 step 查询不提供输入内容，检查点方法只把仅引用的 step 入参签名作为静态约束。临时数据库清理前保留脱敏运行结果、账本快照与仍需核对的 unknown 引用。

当前任务已由用户授权读取当前 Codex 自定义 Responses 服务配置，仅使用 `gpt-6-luna`、reasoning `max`。配置路径由本机调用提供，不进入公开版本控制。凭据只在获准请求步骤内解析，禁止打印配置、环境变量值、HTTP Authorization、完整异常或响应正文。

默认入口不发送收费模型请求；`--fault-check` 只验证本地故障输入。本任务的非流式真实批次已执行，固定 C2 journal 记录 6 条预留；再次调用同一 `--live` 批次会在 HTTP 前阻断重放，不应删除 journal 绕过界限。实际每次输出上限为 512 tokens，首轮 12 次加 C2 的 6 次均为非流式；这些是主会话制定的探测界限，不是用户提供的金额限额。

真实供应商流式入口使用单独的 `--live-stream` 固定批次，要求实际 `stream=true`、SSE 事件及完成 usage，不能以异步 Python 调用代替流式证据。已执行批次及其 journal 不反复发送；新增输入/批次须有对应服务、模型、用途和预算授权。具体版本、请求计数和覆盖限制见 [SDK-02](../acceptance/p0/SDK-02.md)。价格、金额或 usage 缺失保留 unknown/null，不用 token 数估算成已知费用。

## 4. 故障处置和清理

若数据库不可达，先看本项目容器状态并确认 WSL 仍存活，随后只重启本项目 PostgreSQL。不要把 WSL 自动关闭、端口冲突或依赖未安装当成接缝失败通过记录。worker 故障注入只针对探测自身创建的 PID；不终止其他项目进程。

```bash
docker compose -f infra/p0/compose.yaml ps
docker compose -f infra/p0/compose.yaml up -d --wait postgres

# 结束本轮数据库探测，删除本项目临时容器和网络
docker compose -f infra/p0/compose.yaml down
```

关闭临时数据库会删除 tmpfs 运行数据；重跑时重新建立本轮专属 schema，既有卡片事实和公共输入哈希保留。版本推进后按 AGENTS.md 清理本项目已替代且无当前任务/验证/回滚引用的旧开发镜像；先核对具体标签和摘要，不使用全局 prune。固定基础镜像可供同版本实验复现，不将它误认成早期 CloudHelm 开发镜像。
