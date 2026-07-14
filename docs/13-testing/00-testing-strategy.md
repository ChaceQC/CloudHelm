# 测试方案

> 来源：[设计书 17 章](../../云舵 CloudHelm 毕设设计书.md)、
> [测试与验收矩阵](../15-detailed-design/07-testing-acceptance-matrix.md)<br>
> 目的：定义 M1-M6 当前实现的黑盒、白盒、集成与证据门禁，并把 M7-M8
> 规划测试与已交付能力分开。

## 1. 当前测试范围

M1-M6 当前可验证闭环为：

```text
Project / Task
  -> Requirement / Architect / Planner
  -> 审批
  -> Scaffold / Coder / Tester / Reviewer / Security
  -> 本地 branch / commit / format patch / 等价 PR record
```

当前生产路径使用 PostgreSQL、显式 Orchestrator 状态机、Agent Runtime、
Tool Gateway、受控本地 workspace 和 `subprocess`。Docker sandbox、真实远端
PR/CI、Release / Deploy、Remote Agent、Prometheus/Loki 与 SRE 属于 M7-M8
后续测试范围。

## 2. 黑盒测试

黑盒测试从控制台、API 调用方或 Agent 工具调用方视角验证可见行为：

- Project/Task 创建返回 `201`，成功响应不包裹 `data`。
- Task 创建 DTO 只接收 OpenAPI 声明字段，不接受 `constraints` 或
  `auto_start`；创建后保持 `created / Created`。
- 分页、过滤、非法 cursor、缺失字段、非法枚举和错误结构必须稳定。
- `start` / `run-next` 推荐始终携带当前 `expected_phase`；阶段漂移返回
  `409 orchestration_phase_changed`。
- pause/resume/cancel、设计/计划审批、返工和过期审批应产生正确状态与事件。
- M6 每次 `run-next` 只推进一个角色或 Git 收尾动作，不接受调用方指定任意
  workspace、命令、分支或 Artifact root。
- Artifact API 只返回安全预览；本地 PR record 必须是 `provider=local` 且
  `url=null`。
- 控制台切换 Task 后立即隐藏旧详情；旧请求、旧 SSE 和旧 timer 不得覆盖新
  Task，Timeline 同时刻事件保持稳定顺序。

## 3. 白盒测试

白盒测试依据 service、repository、状态机、policy、事务和持久化证据设计：

- Platform API：service/repository 分层、事务回滚、EventLog、副作用幂等、
  行锁、唯一约束、迁移 upgrade/downgrade，以及显式 child 的父运行/Task
  绑定、默认深度 1、active 上限 6、并发配额和 Task 取消级联。
- Orchestrator：M4/M6 显式状态机合法路径、非法迁移、审批等待和返工回退。
- Agent Runtime：八类严格输出、受控 recipe、风险不可降级、Provider
  call/output 配对、结构化修复重试、完整 conversation 和逐请求 usage；
  subagent prompt、过滤 fork context、父子 metadata、摘要长度和最终通知契约。
- Tool Gateway：Pydantic 参数、角色 allowlist、风险等级、审批拦截、路径边界、
  命令 profile、环境白名单、超时、进程树清理、输出上限、脱敏，以及 Platform
  API 集成层沿 conversation lineage 强制的父子角色工具权限交集。
- M6 证据链：Coder changed files 与 lossless Artifact 的 raw bytes/SHA 一致；
  Tester 退出码与 JUnit 一致；Reviewer 读取非空、未截断且保留 Git 结构的
  脱敏安全投影；Security 区分 finding 与基础设施失败；Git 收尾只消费同一
  DevelopmentPlan/recipe/evidence set。
- Shared Contracts：FastAPI `app.openapi()` 与共享 YAML 反序列化后精确一致；
  全部 JSON Schema 可加载，并与 Pydantic/registry 字段一致。

## 4. PostgreSQL 测试隔离

Platform API pytest 默认连接本地 PostgreSQL 实例，但不重置开发库：

1. 以 `cloudhelm_test` 为基名创建会话级随机数据库
   `cloudhelm_test_<pid>_<uuid>`。
2. 在临时库执行 Alembic 迁移和测试。
3. 会话结束执行 `DROP DATABASE ... WITH (FORCE)` 清理。
4. 并行 pytest 会话使用不同数据库，不能互相 TRUNCATE，也不能触碰
   `cloudhelm` 开发库。

运行测试的 PostgreSQL 用户需要具备创建和删除测试数据库的权限。

只有需要复用明确的专用测试库时，才设置
`CLOUDHELM_TEST_DATABASE_URL`。数据库名必须包含独立 `test` 段，并同时设置：

```powershell
$env:CLOUDHELM_TEST_DATABASE_URL='postgresql+psycopg://cloudhelm:cloudhelm_dev@127.0.0.1:15432/cloudhelm_test'
$env:CLOUDHELM_TEST_ALLOW_SCHEMA_RESET='true'
```

该模式会重建目标测试库的 `public` schema；不得指向 `cloudhelm` 或其他开发/
业务数据库。未显式确认时测试必须在迁移前失败。

## 5. 自动化验证命令

Windows PowerShell 统一使用 UTF-8：

```powershell
$env:PYTHONIOENCODING='utf-8'
$OutputEncoding=[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new()
```

### 5.1 Python 模块

```powershell
cd modules/orchestrator
uv lock --check
uv run pytest -q

cd ..\agent-runtime
uv lock --check
uv run pytest -q

cd ..\tool-gateway
uv lock --check
uv run pytest -q

cd ..\platform-api
uv lock --check
uv run alembic upgrade head
uv run alembic check
uv run pytest -q
```

Platform API 的 `tests/test_m6_shared_contracts.py` 同时校验共享 OpenAPI 和全部
JSON Schema；`tests/test_database_migration.py` 校验迁移、约束、索引、回滚及
测试数据库保护。

### 5.2 控制台

```powershell
cd apps/control-console
npm.cmd test
npm.cmd run build
```

### 5.3 sample repo 与安全扫描

```powershell
cd examples/sample-repo-python
uv lock --check
uv run pytest -q
uv run bandit -r src -f json -q
uv run pip-audit --format json --progress-spinner off
```

Bandit finding、pip-audit 漏洞、扫描器不可用、超时和漏洞数据源不可达必须分别
记录；CLI 未运行不能写成“零发现”。

## 6. 黑盒/白盒完成门禁

每个可验证功能至少覆盖：

- 正常路径、边界值、异常输入和非法状态。
- 权限/审批、状态流转、数据库持久化和事件副作用。
- 失败注入、事务回滚、幂等重试和回归测试。
- 对应需求、API、字段、事件、Agent/Tool 契约或验收矩阵的可追溯编号。

提交前还必须执行：

- `git diff --check`。
- `git diff --stat` 和关键文件 diff 复查。
- Markdown 相对链接与 UTF-8 检查。
- 敏感信息扫描。
- 真实 `implementation.diff` 与 `format.patch` 的 `git apply --check`。

只改文档时可不运行代码测试，但必须执行文档结构、链接、关键词漂移和 diff
检查，并记录未运行代码测试的原因。

## 7. 失败恢复边界

M6 已覆盖进入应用错误处理的 Provider、CLI、文件系统和数据库异常：可记录失败
AgentRun、暂停 Task、回滚事务，并通过 ToolCall/Artifact/PR record 幂等证据
重试。

Platform API 进程在终态持久化前被强制终止的场景尚无 lease、heartbeat 或
stale reclaim；`pending/running` AgentRun/ToolCall 可能需要人工核验数据库后
处置。因此当前测试结论不得写成“任意进程崩溃后自动恢复”。该能力应在引入
worker lease 与副作用恢复协议后补充故障注入测试。

## 8. M7-M8 后续测试

- M7：真实远端 PR、CI 状态回传、Release / Deploy 审批、Compose 部署、
  健康检查、回滚和重复请求幂等。
- M8：Remote Agent 心跳、日志/指标采集、Prometheus/Loki、告警、Incident、
  SRE 分析和 runbook。
- Docker sandbox：只读挂载、CPU/内存/PID/网络限制、容器清理与逃逸边界。

这些项目在对应模块和真实依赖落地后执行，不纳入 M1-M6 已通过数量。

## 9. 测试记录

每次执行必须在 `PROJECT_PROGRESS.md` 或阶段测试报告记录：

- 日期、分支、提交或工作区基线。
- 命令、环境变量边界和数据库实例。
- passed/failed/skipped 数量及 skip 原因。
- 缺陷定位、修复、回归结果和剩余风险。
- OpenAPI、JSON Schema、Artifact patch 和安全扫描证据。
