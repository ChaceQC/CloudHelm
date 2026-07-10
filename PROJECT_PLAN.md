# PROJECT_PLAN.md

本文件只记录当前下一步要落实的详细执行计划，不保存总项目规划。总流程和打钩清单见 `docs/14-roadmap/03-implementation-milestone-flow.md`。

## 1. 当前阶段

M6：本地代码实现、测试与 PR 闭环。

前置基线：2026-07-11 已完成 M1-M5 二次审计与 `v0.4.2` 修复。当前基线已经具备：

- Requirement、TechnicalDesign、DevelopmentPlan 真实递增版本和最新版评审约束。
- 严格 cursor、最新优先列表、Timeline 最新页内正序和统一错误响应。
- Tool Gateway 工作区 allowlist、AgentRun/Task 运行态约束、两阶段幂等事务、参数/结果脱敏和 `audit_json`。
- Task 取消对 AgentRun、ToolCall、Approval 的级联关闭。
- Responses API、`gpt-5.6-sol` 显式模型透传、`reasoning.effort=max`、有界重试和可恢复暂停。
- Gemini 式浅色控制台、Project/Task 请求竞态保护、历史评审按钮和 SSE 重连/去重/列表同步。

M6 不重复实现上述基线，也不为未上线旧代码增加兼容层；新增契约、数据库 migration 和前端类型可以直接按当前设计收敛，但必须同步 OpenAPI、JSON Schema、文档和测试。

## 2. 阶段目标

在 M5 已完成 Tool Gateway、Repo/Sandbox/Git 本地工具、审批拦截和审计记录的基础上，让 CloudHelm 能对一个受控 sample repo 完成最小本地开发闭环：

```text
已审批的 Development Plan
  -> Coder Agent 读取 Requirement / Design / Plan
  -> 通过 Tool Gateway 修改 sample repo
  -> Tester Agent 运行真实 pytest 并保存报告
  -> Reviewer Agent 检查真实 diff、测试结果和验收标准
  -> Security Agent 执行本地安全检查
  -> Git Tool 创建本地 branch / commit
  -> Platform API 保存 PR 或等价 PR record
  -> 控制台展示 diff、测试、安全、review 和 PR record
```

M6 只做本地 sandbox / sample repo 闭环，不执行远端部署、不 push 到远端、不创建真实 GitHub/Gitea PR、不操作生产环境。没有真实 Git 服务时必须生成可审计的本地等价 PR record，不能伪造 URL。

版本影响：M6 新增 Agent、状态、表、API、事件和控制台能力，属于兼容新增功能。完成后项目版本提升到 `0.5.0`；数据库 migration、OpenAPI、共享 schema、前端类型和文档必须同步。

## 3. 必须先参考的本地资料

开始编码前必须阅读：

- `AGENTS.md`
- `云舵 CloudHelm 毕设设计书.md`
- `docs/14-roadmap/03-implementation-milestone-flow.md`
- `docs/15-detailed-design/00-mvp-scope-and-cutline.md`
- `docs/15-detailed-design/01-module-contracts.md`
- `docs/15-detailed-design/02-agent-tool-contract.md`
- `docs/15-detailed-design/03-api-detail.md`
- `docs/15-detailed-design/04-data-detail.md`
- `docs/15-detailed-design/05-workflow-state-events.md`
- `docs/15-detailed-design/07-testing-acceptance-matrix.md`
- `docs/04-agents/agents/coder-agent.md`
- `docs/04-agents/agents/tester-agent.md`
- `docs/04-agents/agents/reviewer-agent.md`
- `docs/04-agents/agents/security-agent.md`
- `docs/05-tool-layer/00-tool-gateway.md`
- `docs/05-tool-layer/tools/repo-tool.md`
- `docs/05-tool-layer/tools/sandbox-tool.md`
- `docs/05-tool-layer/tools/git-tool.md`
- `docs/06-workflows/00-development-to-pr.md`
- `docs/08-api/03-agent-run-api.md`
- `docs/08-api/04-tool-call-api.md`
- `docs/10-security/00-security-boundary.md`
- `modules/agent-runtime/README.md`
- `modules/tool-gateway/README.md`
- `modules/platform-api/README.md`
- `packages/shared-contracts/openapi/cloudhelm.openapi.yaml`

## 4. 写代码前必须查阅并归档的成熟实践

创建：

```text
informations/m6-code-test-pr/official-references.md
```

至少归档检索日期、官方链接、摘要、适用子任务和采用结论：

1. FastAPI 官方应用结构和 TestClient / httpx 当前迁移建议。
2. SQLAlchemy 2.x 事务与 PostgreSQL JSONB / 外键 / 索引实践。
3. Alembic 新增表、downgrade 和 `alembic check`。
4. pytest 临时目录、JUnit XML 或结构化测试结果输出。
5. Git 官方 `switch -c`、`diff --name-only`、显式 pathspec commit、`format-patch` 或本地 PR record。
6. Semgrep、Bandit、pip-audit 或等价本地安全检查的官方用法与许可证边界。
7. Docker 官方资源限制、只读挂载、网络隔离和一次性容器实践，用于评估是否在 M6 增强 Sandbox。
8. OpenAI Responses API 结构化输出与 reasoning 配置；继续兼容 `gpt-5.6-sol` + `reasoning.effort=max`，不得在 Coder 等新 Agent 中另写一套 provider。

只保存链接、结论和少量必要摘录，不保存第三方全文、真实 Token、Cookie 或服务器信息。

## 5. 本阶段不做的事项

- 不 push 到 GitHub/Gitea，不创建真实远端 PR；除非用户另行明确要求并提供远端。
- 不执行远端 SSH、远端部署、Compose 上线、服务重启、回滚或监控告警。
- 不让 Agent 绕过 Tool Gateway 直接读写文件、执行命令或调用 Git。
- 不把业务规则堆进 API 路由、React 页面或 prompt；规则进入 service、workflow、policy 或 adapter。
- 不用 mock 代码、固定 diff、假测试报告、假安全报告、假 commit 或假 PR 链接冒充完成。
- 不把 sample repo 的 `.git`、虚拟环境、依赖目录、测试缓存、构建产物或真实凭据提交到 CloudHelm 主仓库。
- 不使用前端设计 Skill 或 ImageGen；M6 控制台继续手工延续当前 Gemini 式浅色主题。

## 6. 预检步骤

### 6.1 Git 与工作区

```powershell
git branch --show-current
git status --short
git log --oneline --decorate --max-count=8
```

确认当前分支为 `dev`，工作区只包含已知改动。建议从 `dev` 创建 `feature/m6-local-dev-closure`；若继续在 `dev`，必须保持可验证小步提交。

### 6.2 M5 基线验证

```powershell
cd modules/tool-gateway
uv lock --check
uv run pytest -q

cd ..\agent-runtime
uv lock --check
uv run pytest -q

cd ..\orchestrator
uv lock --check
uv run pytest -q

cd ..\platform-api
$env:CLOUDHELM_DATABASE_URL='postgresql+psycopg://cloudhelm:cloudhelm_dev@127.0.0.1:15432/cloudhelm'
uv lock --check
uv run alembic upgrade head
uv run alembic check
uv run pytest -q

cd ..\..\apps\control-console
npm.cmd test
npm.cmd run build
```

### 6.3 本地依赖与 sample repo 边界

```powershell
Get-Command docker, git, uv, node, npm -ErrorAction SilentlyContinue
Get-ChildItem examples -Force
Get-ChildItem modules/tool-gateway -Force
```

要求：

- sample repo 固定放在 `examples/sample-repo-python/`。
- 本地运行 Platform API 时，`CLOUDHELM_TOOL_WORKSPACE_ROOTS` 必须显式包含 sample repo 或其受控父目录，不能改回任意目录访问。
- 若 sample repo 使用嵌套 Git，必须确认主仓库 `.gitignore`、打包策略和测试清理方式，不允许误提交嵌套 `.git`。
- 缺少 CLI 时优先使用项目局部依赖、`uv`、`npx` 或 Docker，不污染全局环境。

## 7. 详细任务拆分

### 7.1 资料归档与 Sandbox 决策

创建：

```text
informations/m6-code-test-pr/official-references.md
docs/15-detailed-design/08-m6-local-development-flow.md
```

要求：

- 明确继续使用本地受控 `subprocess`，还是为测试/安全命令增加 Docker 一次性 sandbox。
- 若继续本地 subprocess，必须限制在 sample repo allowlist、命令数组、超时、环境变量白名单和输出上限内，并记录 M7 前剩余风险。
- 若采用 Docker，必须定义镜像、只读/可写挂载、CPU/内存/PID/网络、超时、清理和 artifact 回收。
- 先更新设计与计划，再写实现代码。

### 7.2 准备 `examples/sample-repo-python`

建议目录：

```text
examples/sample-repo-python/
  README.md
  pyproject.toml
  uv.lock
  src/sample_service/
    __init__.py
    main.py
    schemas.py
  tests/
    test_health.py
    test_metrics.py
  Dockerfile
  docker-compose.yml
  demo-issues/
    001-auth-profile.md
```

实现要求：

- 提供真实 FastAPI `/health` 和 `/metrics` 起点。
- 提供真实 pytest，初始至少覆盖健康检查和指标。
- `demo-issues/001-auth-profile.md` 描述注册、登录、个人资料需求与验收标准。
- sample repo 自身命令可复现：`uv sync`、`uv run pytest`、`uv run uvicorn ...`。
- 不预先实现演示 issue 的目标功能，必须由 M6 Coder 流程真实产生 diff。
- 独立 Git 初始化必须由受控脚本或测试 fixture 完成，不在主仓库中提交嵌套 `.git`。

完成后打钩：

- `docs/14-roadmap/03-implementation-milestone-flow.md` 中 “准备 `examples/sample-repo-python`”。

### 7.3 扩展共享 Agent 与 Artifact 契约

新增或更新：

```text
modules/agent-runtime/src/cloudhelm_agent_runtime/schemas/
  implementation.py
  test_report.py
  review_report.py
  security_report.py
packages/shared-contracts/schemas/agents/
  coder-agent-output.schema.json
  tester-agent-output.schema.json
  reviewer-agent-output.schema.json
  security-agent-output.schema.json
packages/shared-contracts/schemas/artifacts/
  artifact.schema.json
  pull-request-record.schema.json
```

最低字段：

- Coder：任务/计划引用、修改文件、每个文件的意图、ToolCallRequest 列表、风险和摘要。
- Tester：命令、exit code、通过/失败数、stdout/stderr 摘要、JUnit/artifact 引用、失败原因。
- Reviewer：验收标准映射、diff 覆盖、问题清单、结论、是否允许进入安全检查。
- Security：工具、规则、发现项、严重级别、剩余风险、是否阻断 PR record。
- Artifact：类型、路径/URI、hash、大小、生产者 AgentRun、任务、创建时间和公开摘要。
- PR record：base/head、commit hash、changed files、diff summary、artifact refs、review/security 结论和状态。

要求：

- Pydantic 与 JSON Schema 字段、required、枚举必须一致。
- 代表性成功输出和非法输出都要验证。
- 不允许自然语言文本替代结构化结论。

### 7.4 数据模型与 migration

建议新增：

```text
modules/platform-api/src/cloudhelm_platform_api/models/artifact.py
modules/platform-api/src/cloudhelm_platform_api/models/pull_request_record.py
modules/platform-api/src/cloudhelm_platform_api/repositories/artifact_repository.py
modules/platform-api/src/cloudhelm_platform_api/repositories/pull_request_record_repository.py
modules/platform-api/migrations/versions/<revision>_create_m6_artifacts.py
```

数据要求：

- `artifacts` 关联 task、agent_run、tool_call，可保存 JSON metadata、hash、摘要和受控本地路径。
- `pull_request_records` 关联 task、project、base/head、commit hash、diff/test/review/security artifact。
- 对 task、type、created_at、status 建立查询索引。
- 本地路径必须位于 artifact 根目录或 sample repo 内，API 不返回任意绝对路径。
- migration 必须支持 downgrade；`alembic check` 无差异。

### 7.5 实现 Coder / Tester / Reviewer / Security Agent

新增：

```text
modules/agent-runtime/src/cloudhelm_agent_runtime/agents/
  coder_agent.py
  tester_agent.py
  reviewer_agent.py
  security_agent.py
modules/agent-runtime/tests/
  test_coder_agent.py
  test_tester_agent.py
  test_reviewer_agent.py
  test_security_agent.py
```

要求：

- 复用当前 `StructuredAgentProvider`、Responses API、`reasoning.effort=max` 和 retry 配置；不另写 HTTP client。
- Coder 只输出修改计划和结构化工具请求，不直接触碰文件系统。
- Tester 只提出允许命令并消费真实 ToolCall 结果，不伪造通过数。
- Reviewer 基于真实 diff、Requirement AC、测试报告给出结论。
- Security 基于真实扫描结果给出发现项；工具不可用时返回明确 blocked/partial，不写“通过”。
- 每个 Agent 明确允许工具列表，所有副作用经 Tool Gateway。

完成后分别打钩总排期中的 Scaffold/Coder/Tester/Reviewer/Security 项；如果 Scaffold 未实际实现，不得提前打钩。

### 7.6 扩展 Orchestrator M6 状态机

建议阶段：

```text
Planning
  -> Implementing
  -> Testing
  -> Reviewing
  -> SecurityScanning
  -> ReadyForPR
  -> Done
```

建议修改：

```text
modules/orchestrator/src/cloudhelm_orchestrator/
modules/orchestrator/tests/
docs/15-detailed-design/05-workflow-state-events.md
```

要求：

- 只有当前最新版 DevelopmentPlan 为 `approved` 才能进入 Implementing。
- 每次 `run-next` 或独立 M6 入口只推进一个可审计步骤。
- ToolCall/AgentRun 失败必须记录失败、可重试性和恢复阶段。
- 测试失败回到 Implementing；Reviewer 要求修改回到 Implementing；Security 阻断停在可修复状态。
- ReadyForPR 前必须存在真实 diff、通过测试、review 通过和非阻断安全结论。
- Task pause/cancel 继续沿用 `v0.4.2` 的运行态和级联关闭语义。

### 7.7 Platform API 本地开发工作流

建议新增或修改：

```text
modules/platform-api/src/cloudhelm_platform_api/services/local_development_service.py
modules/platform-api/src/cloudhelm_platform_api/services/artifact_service.py
modules/platform-api/src/cloudhelm_platform_api/services/pull_request_record_service.py
modules/platform-api/src/cloudhelm_platform_api/api/artifacts.py
modules/platform-api/src/cloudhelm_platform_api/api/pull_request_records.py
modules/platform-api/src/cloudhelm_platform_api/schemas/artifact.py
modules/platform-api/src/cloudhelm_platform_api/schemas/pull_request_record.py
modules/platform-api/tests/test_local_development_workflow_api.py
```

实现要求：

- service 层调用应用级共享 Tool Gateway，不在路由中执行文件、命令或 Git。
- 每步真实写 AgentRun、ToolCall、Artifact、EventLog 和任务阶段。
- 工作区来自 Project/sample repo 受控配置，不能由请求任意指定本机目录。
- 测试报告、安全报告、review 结论和 diff 必须来自真实命令/文件。
- PR record 只在 branch、commit、测试、review、安全门禁满足后创建。
- 幂等键包含 task、step、attempt，重试不能重复 commit 或重复 PR record。

建议 API：

```text
POST /api/tasks/{task_id}/local-development/start
POST /api/tasks/{task_id}/local-development/run-next
GET  /api/tasks/{task_id}/artifacts
GET  /api/artifacts/{artifact_id}
GET  /api/tasks/{task_id}/pull-request-records
GET  /api/pull-request-records/{record_id}
```

最终路径以更新后的 OpenAPI 为准；无兼容负担时可直接选择一致、清晰的契约，不保留临时别名。

### 7.8 Git 与本地 PR record

要求：

- 从 sample repo 默认分支创建 `codex/` 或 `feature/` 前缀分支。
- `git.commit` 继续只接受显式文件列表；提交前检查 status/diff。
- commit message 使用中文类型前缀，例如 `feat: 实现注册登录接口`。
- 保存 commit hash、base/head、changed files、diff stat 和 patch artifact。
- 没有远端时创建 `local` provider 的 PR record，不构造 `https://...` 假链接。
- 重复执行同一步不得创建多个等价 commit/record。

### 7.9 控制台展示本地开发闭环

建议新增：

```text
apps/control-console/src/features/diff-viewer/
apps/control-console/src/features/test-reports/
apps/control-console/src/features/security-reports/
apps/control-console/src/features/pull-requests/
apps/control-console/src/shared/types/api.ts
apps/control-console/src/shared/api/cloudhelmApi.ts
apps/control-console/src/features/tasks/TaskDetail.tsx
apps/control-console/tests/
```

要求：

- 展示真实 changed files、diff summary/patch、测试结果、安全发现、review 结论和 PR record。
- 加载态、错误态、空态、重试和外部事件刷新都必须真实可用。
- 继续使用当前 Gemini 式浅色信息架构：`#f0f4f9` 蓝灰侧栏、白色主工作区、浅蓝选择态、柔和圆角和宽松阅读流。
- 不使用前端 Skill/ImageGen，不引入假截图或静态演示数据。
- 1280×720、1024×768、375×812 无水平溢出；复杂 diff 在窄屏可纵向滚动或折叠，但不能截断关键状态。
- Project/Task 最新请求门禁、历史评审规则和 SSE 重连逻辑必须继续复用，不能回退。

### 7.10 OpenAPI、事件与文档同步

更新：

```text
packages/shared-contracts/openapi/cloudhelm.openapi.yaml
packages/shared-contracts/schemas/events/task-event.schema.json
docs/04-agents/
docs/06-workflows/00-development-to-pr.md
docs/08-api/
docs/09-control-console/
docs/10-security/
docs/15-detailed-design/
README.md
.env.example
```

要求：

- FastAPI `create_app().openapi()` 与共享 YAML 反序列化后精确一致。
- 事件 schema 覆盖 M6 Agent、artifact、测试、review、安全、branch、commit、PR record 事件。
- 配置文档加入 sample repo、artifact root、安全工具和 sandbox 变量。
- 文档明确 M6 是本地等价 PR 闭环，不是远端 PR/部署完成。

## 8. 黑盒测试设计

至少覆盖：

1. 从 demo issue 创建任务并完成 Requirement/Design/Plan 审批。
2. 未批准计划不能启动 M6。
3. Coder 通过 Tool Gateway 对 sample repo 产生真实文件变更。
4. Tester 执行真实 pytest，成功和失败结果均落库。
5. Reviewer 读取真实 diff 与 AC，发现缺项时阻止进入 Security。
6. Security 执行真实工具或明确 partial/blocked，阻断项不能创建 PR record。
7. Git Tool 创建真实本地 branch 和 commit。
8. Platform API 返回真实 artifact 与本地 PR record。
9. 重复请求不重复写文件、commit 或 PR record。
10. pause/cancel 能阻止后续副作用并关闭 active 记录。
11. 控制台无需手工刷新即可通过 SSE 展示新阶段和 artifact。

## 9. 白盒测试设计

至少覆盖：

- Agent 输入/输出 schema 的成功、缺字段、非法枚举、断裂引用和超长输出。
- Orchestrator 每个阶段、非法迁移、测试失败回退、review/security 阻断和恢复。
- Artifact/PR repository 分页、任务归属、事务回滚和唯一约束。
- Tool Gateway 工作区 allowlist、敏感路径、输出脱敏、超时、限流、审批和幂等。
- Git 脏工作区、无变更、目录 pathspec、重复分支、重复 commit。
- 测试命令失败、超时、stderr 截断、JUnit 解析失败和 artifact 缺失。
- Security CLI 不存在、非零退出、发现项分级和报告解析失败。
- 前端 API client、条件渲染、SSE 去重、请求竞态和报告状态策略。

## 10. 验证命令

```powershell
cd modules/tool-gateway
uv lock --check
uv run pytest -q

cd ..\agent-runtime
uv lock --check
uv run pytest -q

cd ..\orchestrator
uv lock --check
uv run pytest -q

cd ..\platform-api
$env:CLOUDHELM_DATABASE_URL='postgresql+psycopg://cloudhelm:cloudhelm_dev@127.0.0.1:15432/cloudhelm'
uv lock --check
uv run alembic upgrade head
uv run alembic check
uv run pytest -q

cd ..\..\examples\sample-repo-python
uv lock --check
uv run pytest -q

cd ..\..\apps\control-console
npm.cmd test
npm.cmd run build
```

补充门禁：

- Alembic `downgrade <previous>` -> `upgrade head` -> `alembic check`。
- 解析全部共享 JSON Schema，并校验代表性 Agent/Artifact 输出。
- OpenAPI 与 FastAPI 精确比较。
- 浏览器回归 1280×720、1024×768、375×812，检查 diff/report/PR record、SSE 外部事件和 console。
- `git diff --check`、secret scan、TODO/FIXME/NotImplemented/空 `pass`、普通生产源码超过 300 行检查。
- sample repo 与 CloudHelm 主仓库分别执行 `git status --short`，确认没有混入依赖、缓存、嵌套 `.git` 或真实凭据。

## 11. 文档与进度同步

每完成一个可验证小步：

1. 更新 `PROJECT_PROGRESS.md`，记录命令、结果、失败/修复闭环和剩余风险。
2. 满足完成判定后，在 `docs/14-roadmap/03-implementation-milestone-flow.md` 勾选对应 M6 子项。
3. 修改 API、schema、事件、配置、状态机或安全边界时同步对应 `docs/`。
4. 按可验证粒度提交并 push 当前开发分支，不累计一次大提交。
5. M6 全部完成后把本文件重写为 M7 详细计划。

## 12. M6 完成判定

只有全部满足才算 M6 完成：

- sample repo 可独立启动 `/health`、`/metrics` 并通过 pytest。
- Coder、Tester、Reviewer、Security Agent 均有结构化生产实现和测试。
- 代码修改、测试、安全检查和 Git 操作都经过 Tool Gateway。
- sample repo 产生真实 diff、测试报告、review 结论、安全结果、branch 和 commit。
- Platform API 持久化真实 Artifact 和本地等价 PR record，并写入完整 EventLog。
- 控制台展示真实 diff/test/security/review/PR record，三种视口和 SSE 通过。
- migrations、全部模块测试、sample repo 测试、OpenAPI、JSON Schema 和静态检查通过。
- 总排期 M6 复选框、`PROJECT_PROGRESS.md` 和下一阶段 `PROJECT_PLAN.md` 同步。
- 工作区只包含 M6 相关改动，已按小步提交并推送 `dev` 或 M6 功能分支。

## 13. 风险与阻塞处理

- Docker sandbox 成本过高：可继续使用 M5 本地受控目录，但只允许 sample repo，必须记录网络/资源隔离不足，并列为 M7 前置风险。
- 安全 CLI 不可用：使用可复现的局部安装或 Docker；仍不可用时标记 blocked/partial，不得伪造扫描通过。
- Git Tool 可能影响主仓库：sample repo 使用独立受控目录和显式 `repo_root`，每步前后检查两个仓库状态。
- 外部 LLM 不可用：默认 `local_structured` 不能伪造 Coder 真实执行结果；模型调用失败按 `v0.4.2` 重试/暂停语义记录，待配置恢复。
- Windows symlink 权限不足：保留跳过条件，但继续覆盖普通越界和既有 symlink；不能因此放宽 allowlist。
- 真实远端 Git 不存在：生成本地 PR record 和 patch artifact，文档明确等价边界。
- 任一工具、测试、review 或安全门禁失败：写失败 AgentRun、ToolCall、Artifact/Event，回到可恢复状态，不创建 PR record，不勾选完成。
