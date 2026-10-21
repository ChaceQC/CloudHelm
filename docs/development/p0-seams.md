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

### 3.1 当前可执行的定向检查

先列出不连接供应商的本地检查，随后单列需要当次授权的真实请求入口。具体有限支持范围见 [A01 报告](../acceptance/p0/A01.md) 与 [A02 报告](../acceptance/p0/A02.md)；正式产品入口仍须经过 [受支持薄适配决定](../decisions/p0/admitted-runtime.md) 和 P0.3/P1 门禁。

```bash
# 不收费：断流判定方法的定向拒绝检查
uv run --locked --offline python scripts/p0/check_stream_assertions.py

# 不连接供应商：真实 SDK 路径 + 固定 HTTP 夹具 + 隔离 PostgreSQL 门禁
uv run --locked --offline python scripts/p0/check_admitted_paths.py

# 消费瞬态输入后的成功/异常检查点；需要上述隔离 PostgreSQL
uv run --locked --offline python scripts/p0/check_checkpoint.py
```

以下两条会因固定授权而发出真实供应商请求，仅在具备当次服务、模型、用途和预算授权时执行；重复调用同一批次会在 HTTP 前由本地 journal 阻断，不得删除 journal 绕过上限。

```bash
# 固定授权输入：自身 worker 崩溃恢复后，最多 1 条真实新模型请求
uv run --locked --offline python scripts/p0/probe_admitted_recovery.py --live

# 新固定 r2 流输入：最多 4 条真实请求；既有批次拒绝重放
uv run --locked --offline python scripts/p0/probe_admitted_stream.py --live --live-revision r2
```

恢复脚本只杀自身创建的 worker，并确认退出后重新启动；不结束其他 worker 或 WSL。默认入口不发送收费模型请求；`--fault-check` 只验证本地故障输入。SDK 路径夹具的 usage 不作为供应商证据；受控摘要 Agent 的压缩请求和后续请求均经过同一门禁，不宣称 SDK 内建自动压缩能力。DBOS 3.2.0 公共 step 查询不提供输入内容，检查点方法只把仅引用的 step 入参签名作为静态约束。临时数据库清理前保留脱敏运行结果、账本快照与仍需核对的 unknown 引用。

价格、金额或 usage 缺失保留 unknown/null，不用 token 数估算成已知费用。

### 3.2 历史已执行批次说明

以下批次已在各自固定输入下执行完毕，结果与原 journal 一并保留，仅用于按原身份核对，不重复发送：

- P0.1-A01 的供应商流式批次绑定 `SDK-A01-C1`；同输入再启动由本地 journal 拒绝收费重放。`connect_live_continuation.py` 查询原 Operation 并接到同库等待/新 Run，新增供应商请求为 0。
- 历史非流式批次与另行授权的真实流式批次分别使用各自 journal，实际计数及界限见 SDK-02，不合并为同一批次或统一请求上限。
- P0.1-A01 的门禁/检查点/续接定向检查：`check_admission.py`、`check_checkpoint.py`、`check_continuation.py` 在同一 WSL 隔离数据库通过。
- 2026-10-14 的 P0.1-A02 断流批次：严格 r2 必须显式给出 `--live-revision r2`；旧 `--live` 命令不会隐式开启新输入。恢复使用独立固定批次：四个场景分别保留一条本地尝试，其中仅 allow 允许一条真实 HTTP；取消、撤权和 unknown 占账导致预算不足必须零 HTTP。原 r1 journal 与未知记录保持原身份，不删除以绕过上限。

查询/费用 journal、未知记录和恢复引用不能为重跑而删除；环境重建后缺少原对象时该查询应失败，不能补造成功。实际请求计数、金额和覆盖限制见 [A01](../acceptance/p0/A01.md)、[A02](../acceptance/p0/A02.md) 和 [SDK-02](../acceptance/p0/SDK-02.md)，不在本页重复登记。

供应商配置由当次任务授权提供：只读取获准的本机自定义 Responses 服务配置，具体服务地址、模型名和推理档位按该次授权使用，不写入本页、不进入公开版本控制。凭据只在获准请求步骤内解析；禁止打印配置、环境变量值、HTTP Authorization、完整异常或响应正文。输出上限、场景次数和预算上界由主会话在方法中定义，不是用户提供的金额限额。

## 4. 故障处置和清理

若数据库不可达，先看本项目容器状态并确认 WSL 仍存活，随后只重启本项目 PostgreSQL。不要把 WSL 自动关闭、端口冲突或依赖未安装当成接缝失败通过记录。worker 故障注入只针对探测自身创建的 PID；不终止其他项目进程。

```bash
docker compose -f infra/p0/compose.yaml ps
docker compose -f infra/p0/compose.yaml up -d --wait postgres

# 结束本轮数据库探测，删除本项目临时容器和网络
docker compose -f infra/p0/compose.yaml down
```

关闭临时数据库会删除 tmpfs 运行数据；重跑时重新建立本轮专属 schema，既有卡片事实和公共输入哈希保留。版本推进后按 AGENTS.md 清理本项目已替代且无当前任务/验证/回滚引用的旧开发镜像；先核对具体标签和摘要，不使用全局 prune。固定基础镜像可供同版本实验复现，不将它误认成早期 CloudHelm 开发镜像。

## 5. 同机准备与参照适用性

环境口径：s2413 是用户选定的临时同机组合，现有快照只证明采集时的系统事实；实际安装、配额生效和运行验证分别取证。WSL 结果不能替代这些证据，正式独立目标仍是 P1.4/P1 出口前置。具体方案见 [开发组合决定](../decisions/p0/s2413-development-envelope.md)，分类结果见 [支持矩阵](../acceptance/support-matrix.md)。

P0-G01/G02 只需要环境事实与固定参照的适用性证据时，不启动数据库或重跑上述收费批次。对应入口为 [本轮快照](../acceptance/p0/topology-s2413-r2.md)、[受控环境决定](../decisions/p0/s2413-development-envelope.md) 和 [参照适用决定](../decisions/p0/reference-applicability.md)。在已有 WSL 环境按实际需要运行：

```bash
cd /mnt/e/Project/CloudHelm
# 只读系统字段和本地 Docker 聚合信息；逐项保留 unknown/不可调用。
PATH="$HOME/.local/bin:$PATH" python3 scripts/p0/topology_snapshot.py wsl

# 只读固定公共文件及指定历史 Git 对象，实际观察旧解析器的拒绝。
uv run --locked --offline --no-sync python -B -m scripts.p0.reference_applicability \
  --historical-repository "/mnt/d/graduation project"
```

采集器退出 0 仅表示完成采集；各分区的 observed、unknown、拒绝与未配置必须分别解释。它不读取完整配置、容器配置或凭据，也不实现产品准入；当前已批准预算和可信占用上界未知，因此诊断要求新执行按零可准入处理。s2413 由现有获授权连接将同一源码通过 SSH stdin 执行；本机没有直接可用的 `ssh s2413` 别名，具体连接值不得复制进仓库。

适用性方法依赖本机历史仓库内的已登记对象，路径按实际本机位置传入；它不会执行历史源码或读取该仓库工作树配置。结果中的 passed 只覆盖固定来源/字节、字段分类和原解析器拒绝；`product_deployment_supported=false` 不是待忽略的提示。缺少历史对象或输入变动时非零退出，不能用旧结果补造通过。

最终公开输入冻结与历史摘要复核使用 [收尾清单方法](p0-decisions.md#收尾输入与历史证据)。不因文档更新重取无变化的环境快照；方法或环境变化时记录新窗口与新证据，历史数据保留。P1 实际安装、配额、身份、制品、迁移及独立目标，P2 预览/原生支持分别按门禁取证。
