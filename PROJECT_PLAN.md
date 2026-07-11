# PROJECT_PLAN.md

本文件只记录当前下一步要落实的详细执行计划，不保存总项目规划。总流程和
打钩清单见 `docs/14-roadmap/03-implementation-milestone-flow.md`。

## 1. 当前阶段

M6：本地代码实现、测试与 PR 闭环。

前置基线：2026-07-11 已完成 M1-M5 二次审计和 Task conversation /
Prompt Cache 纠偏，当前项目版本为 `0.4.3`，Agent Runtime 为 `0.3.2`。
当前基线已经具备：

- Requirement、TechnicalDesign、DevelopmentPlan 真实递增版本、最新版评审
  约束和 stale approval 拦截。
- 严格 cursor、最新优先列表、Timeline 最新页内正序和统一错误响应。
- Tool Gateway 工作区 allowlist、AgentRun/Task 运行态约束、两阶段幂等事务、
  参数/结果脱敏和 `audit_json`。
- Task 取消对 AgentRun、ToolCall、Approval 的级联关闭。
- 每个 Task 唯一 root `agent_conversations`；Requirement、Architect、Planner
  跨独立 API 请求共享完整 ResponseItem 历史和同一 `prompt_cache_key`。
- 只有显式 `spawn_subagent` 才创建 child conversation，fresh/full-history、
  parent/depth/role/status 和最终通知边界已经完成白盒验证。
- HTTP SSE Responses API、Codex User-Agent、thread/session headers、
  `reasoning.encrypted_content`、`gpt-5.6-sol` / `xhigh`、逐请求 usage、有界
  重试和可恢复暂停。
- Agent 步骤 savepoint：业务产物、成功 AgentRun、conversation turn 和完成
  事件原子保存，晚期失败不会留下半成品。
- Gemini 式浅色控制台、Project/Task 请求竞态保护、历史评审按钮、SSE
  重连/去重/列表同步，以及 AgentRun turn/cache/逐请求 usage 展示。

M6 不重复实现上述基线，也不为未上线旧代码增加兼容层。新增契约、数据库
migration、事件和前端类型可以直接按当前设计收敛，但必须同步 OpenAPI、
JSON Schema、文档、测试和进度记录。

## 2. 阶段目标

在 M5 Tool Gateway 与 M4 Task root conversation 基础上，让 CloudHelm 对一个
受控 sample repo 完成最小本地开发闭环：

```text
已审批 DevelopmentPlan
  -> Coder 在同一 Task root conversation 中生成工具请求
  -> Tool Gateway 修改 sample repo
  -> Tester 在同一 root conversation 中运行真实 pytest
  -> Reviewer 检查真实 diff、测试结果与验收标准
  -> Security 执行真实本地安全检查
  -> Git Tool 创建本地 branch / commit
  -> Platform API 保存 Artifact 与本地等价 PR record
  -> 控制台展示 diff、测试、安全、review 和 PR record
```

关键会话不变量：

1. Coder、Tester、Reviewer、Security、Scaffold 等普通角色继续复用当前 Task
   root conversation，不能按角色隐式创建新会话。
2. 只有模型明确请求且 Tool Gateway/Policy 允许的显式 spawn 操作才能创建
   child conversation。
3. 工具 call/output、测试结果、diff、审批上下文和最终结构化结果必须按顺序
   进入 root 或对应 child 历史。
4. Base Instructions、稳定扁平输出 schema 和发送给模型的工具定义集合不得
   随普通角色切换而变化；角色权限由 `<role_contract>`、Tool Gateway 和 Policy
   共同限制。
5. Prompt Cache 只使用供应商 usage 证据，不因 M6 新角色增加而回退为本地估算。

M6 只做本地 sandbox / sample repo 闭环，不执行远端部署、不 push 到远端、
不创建真实 GitHub/Gitea PR、不操作生产环境。没有真实 Git 服务时必须生成
可审计的本地等价 PR record，不能伪造 URL。

版本影响：M6 新增 Agent、状态、表、API、事件和控制台能力，属于兼容新增功能。
完成后项目版本提升到 `0.5.0`；数据库 migration、OpenAPI、共享 schema、
前端类型和文档必须同步。

## 3. 必须先阅读的本地资料

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
- `docs/04-agents/00-agent-layer.md`
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
- `informations/m4-agent-context/codex-responses-context.md`
- `modules/agent-runtime/README.md`
- `modules/tool-gateway/README.md`
- `modules/platform-api/README.md`
- `packages/shared-contracts/openapi/cloudhelm.openapi.yaml`

## 4. 写代码前必须查阅并归档的成熟实践

创建：

```text
informations/m6-code-test-pr/official-references.md
```

至少记录检索日期、官方链接、适用子任务、摘要和采用结论：

1. FastAPI 当前应用结构、同步长任务边界和 TestClient/httpx 迁移建议。
2. SQLAlchemy 2.x savepoint、事务回滚、PostgreSQL JSONB、外键和索引实践。
3. Alembic 新增表、约束、downgrade 和 `alembic check`。
4. pytest 临时目录、JUnit XML、结构化测试结果和失败恢复。
5. Git 官方 `switch -c`、`diff --name-only`、显式 pathspec commit、
   `format-patch` 和本地 PR record。
6. Semgrep、Bandit、pip-audit 或等价本地安全检查的官方用法、输出格式和许可证。
7. Docker 一次性容器的只读挂载、可写 worktree、CPU/内存/PID/网络限制和清理。
8. OpenAI Responses function calling、完整 ResponseItem、streaming、reasoning
   与 Prompt Cache；复用当前 `gpt-5.6-sol` / `xhigh` Provider，不另写 HTTP client。
9. Codex 多 Agent 的显式 spawn、父子历史过滤、工具 call/output 回放和最终通知。

只保存链接、结论和少量必要摘录，不保存第三方全文、真实 Token、Cookie、
服务器地址或许可证不明的大段代码。

## 5. 本阶段不做

- 不 push 到 GitHub/Gitea，不创建真实远端 PR，除非用户另行明确要求并提供远端。
- 不执行远端 SSH、Compose 上线、服务重启、回滚或监控告警。
- 不让 Agent 绕过 Tool Gateway 直接读写文件、执行命令或调用 Git。
- 不把业务规则堆进 API 路由、React 页面或 prompt。
- 不用固定 diff、假测试报告、假安全报告、假 commit 或假 PR 链接冒充完成。
- 不把 sample repo 的 `.git`、虚拟环境、依赖目录、缓存、构建产物或凭据提交
  到 CloudHelm 主仓库。
- 不实现 Responses WebSocket；继续使用已验证的 HTTP SSE。
- 不使用前端设计 Skill 或 ImageGen；继续手工延续 Gemini 式浅色主题。

## 6. 预检步骤

### 6.1 Git 与工作区

```powershell
git branch --show-current
git status --short
git log --oneline --decorate --max-count=8
```

确认当前分支为 `dev`，工作区干净。建议从 `dev` 创建
`feature/m6-local-dev-closure`；如果继续在 `dev`，必须保持可验证小步提交。

### 6.2 v0.4.3 基线验证

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
uv lock --check
uv run alembic upgrade head
uv run alembic check
uv run pytest -q

cd ..\..\apps\control-console
npm.cmd test
npm.cmd run build
```

必须额外确认：

- Task root conversation 白盒测试仍通过。
- 真实外部测试保持默认 skip，只有显式注入凭据时才执行。
- `CLOUDHELM_LLM_REASONING_EFFORT=xhigh`、Codex User-Agent 和 HTTP SSE 默认
  配置没有被 M6 新 Agent 覆盖。

### 6.3 本地依赖与 sample repo

```powershell
Get-Command docker, git, uv, node, npm -ErrorAction SilentlyContinue
Get-ChildItem examples -Force
Get-ChildItem modules/tool-gateway -Force
```

要求：

- sample repo 固定放在 `examples/sample-repo-python/`。
- `CLOUDHELM_TOOL_WORKSPACE_ROOTS` 必须显式包含 sample repo 或其受控父目录。
- sample repo 使用嵌套 Git 时，不允许主仓库提交其 `.git`。
- 缺少 CLI 时优先使用项目局部依赖、`uv`、`npx` 或 Docker，不污染全局环境。

## 7. 详细任务拆分

### 7.1 资料归档与 Sandbox 决策

创建：

```text
informations/m6-code-test-pr/official-references.md
docs/15-detailed-design/08-m6-local-development-flow.md
```

要求：

- 明确继续使用受控 `subprocess`，还是对测试/安全命令增加 Docker 一次性 sandbox。
- 本地 subprocess 方案必须限制 sample repo allowlist、命令数组、超时、环境
  变量白名单、输出上限和进程清理，并记录资源/网络隔离不足。
- Docker 方案必须定义镜像、只读/可写挂载、CPU/内存/PID/网络、超时、
  清理和 artifact 回收。
- 先更新设计，再写实现。

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
- 提供真实 pytest，初始覆盖健康检查和指标。
- demo issue 描述注册、登录、个人资料需求和可追溯 AC。
- sample repo 可独立执行 `uv sync`、`uv run pytest` 和 `uv run uvicorn ...`。
- 不预先实现 demo issue 目标功能，必须由 M6 Coder 流程产生真实 diff。
- 独立 Git 由受控脚本或测试 fixture 初始化，主仓库不提交嵌套 `.git`。

完成后仅在真实命令通过时勾选总排期“准备 sample repo”。

### 7.3 扩展稳定 Agent、Tool 与 Artifact 契约

新增或更新：

```text
modules/agent-runtime/src/cloudhelm_agent_runtime/schemas/
  implementation.py
  test_report.py
  review_report.py
  security_report.py
modules/agent-runtime/src/cloudhelm_agent_runtime/prompts/
  coder.md
  tester.md
  reviewer.md
  security.md
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

- Coder：Task/Plan 引用、修改文件、每个文件意图、工具请求、风险和摘要。
- Tester：命令、exit code、通过/失败数、stdout/stderr 摘要、报告引用和失败原因。
- Reviewer：AC 映射、diff 覆盖、问题清单、结论和是否允许进入安全检查。
- Security：工具、规则、发现项、严重级别、剩余风险和阻断结论。
- Artifact：类型、受控路径/URI、hash、大小、生产者、Task、摘要和创建时间。
- PR record：base/head、commit、changed files、diff/test/review/security 引用和状态。

缓存与工具要求：

- 一次性扩展 `cloudhelm_agent_output_v1`，使所有普通角色发送完全相同的扁平
  `text.format`；当前角色仍由专属 Pydantic model 严格校验。
- 定义 M6 root conversation 的稳定工具集合；不能按角色改变 Responses
  `tools` 前缀。角色能否调用由 Role allowlist、Tool Gateway 和 Policy 判断。
- Tool declaration、function/custom call、Tool Gateway result 和
  function/custom output 必须结构化并使用同一 `call_id`。
- Pydantic、JSON Schema、OpenAPI/事件字段和 TypeScript type 必须一致。

### 7.4 数据模型与 migration

建议新增：

```text
modules/platform-api/src/cloudhelm_platform_api/models/artifact.py
modules/platform-api/src/cloudhelm_platform_api/models/pull_request_record.py
modules/platform-api/src/cloudhelm_platform_api/repositories/artifact_repository.py
modules/platform-api/src/cloudhelm_platform_api/repositories/pull_request_record_repository.py
modules/platform-api/migrations/versions/<revision>_create_m6_artifacts.py
```

要求：

- `artifacts` 关联 task、agent_run、tool_call，保存 metadata JSONB、hash、摘要和
  受控本地引用。
- `pull_request_records` 关联 task、project、base/head、commit、diff/test/
  review/security artifact。
- 对 task/type/status/created_at 建索引和必要唯一约束。
- API 不返回任意绝对路径。
- migration 支持 downgrade，`alembic check` 无差异。

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

- 复用当前 Provider、Instructions、HTTP SSE、`xhigh`、retry、root
  conversation 和逐请求 usage，不另写 HTTP client。
- Coder 只提出结构化 ToolCall，不直接触碰文件系统。
- Tester 只提出允许命令并消费真实 ToolCall 结果，不伪造通过数。
- Reviewer 基于真实 diff、Requirement AC 和测试报告。
- Security 基于真实扫描结果；工具不可用时返回 blocked/partial。
- 普通角色切换只增加 root turn；需要并行工作时必须显式 spawn child。
- 每个 Agent 成功步骤继续使用 savepoint 原子保存产物、AgentRun、conversation
  turn 和事件。

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

要求：

- 只有当前最新版 DevelopmentPlan 为 `approved` 才能进入 Implementing。
- 每个入口一次只推进一个可审计步骤。
- ToolCall/AgentRun 失败记录可重试性和恢复阶段。
- 测试失败、Review 要求修改、Security 阻断均回到明确可恢复状态。
- ReadyForPR 前必须存在真实 diff、通过测试、review 通过和非阻断安全结论。
- pause/cancel 沿用 `v0.4.3` 语义，不能绕过运行态继续副作用。

### 7.7 Platform API 本地开发工作流

建议新增：

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

建议 API：

```text
POST /api/tasks/{task_id}/local-development/start
POST /api/tasks/{task_id}/local-development/run-next
GET  /api/tasks/{task_id}/artifacts
GET  /api/artifacts/{artifact_id}
GET  /api/tasks/{task_id}/pull-request-records
GET  /api/pull-request-records/{record_id}
```

要求：

- service 层调用应用级共享 Tool Gateway，路由不执行文件、命令或 Git。
- 每步真实写 AgentRun、ToolCall、Artifact、EventLog 和 Task phase。
- 工作区来自 Project/sample repo 受控配置，不能由请求任意指定本机目录。
- 报告、diff、review 和安全结论必须来自真实工具结果。
- 幂等键包含 task/step/attempt，重试不能重复写文件、commit 或 PR record。
- 无兼容负担时直接采用一致清晰契约，不保留临时别名。

### 7.8 Git 与本地 PR record

- 从 sample repo 默认分支创建 `codex/` 或 `feature/` 前缀分支。
- `git.commit` 只接受显式文件列表；提交前检查 status/diff。
- commit message 使用中文类型前缀。
- 保存 commit hash、base/head、changed files、diff stat 和 patch artifact。
- 没有远端时创建 `provider=local` 的 PR record，不构造假链接。
- 重复执行不得创建多个等价 commit/record。

### 7.9 控制台展示

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

- 展示真实 changed files、diff、测试、安全、review 和 PR record。
- 提供加载、错误、空、重试和 SSE 刷新状态。
- 继续使用 Gemini 浅色布局、低饱和背景、浅蓝选择态、柔和圆角和宽松阅读流。
- 不使用前端 Skill/ImageGen，不添加静态演示数据。
- 1280×720、1024×768、375×812 无水平溢出；窄屏 diff 可折叠/纵向滚动。
- 复用最新请求门禁、历史评审策略和 SSE 重连，不得回退。

### 7.10 契约、事件与文档同步

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
PROJECT_PROGRESS.md
```

要求：

- FastAPI OpenAPI 与共享 YAML 反序列化后精确一致。
- 事件 schema 覆盖 M6 Agent、artifact、测试、review、安全、branch、commit
  和 PR record。
- 配置文档加入 sample repo、artifact root、安全工具和 sandbox 变量。
- 文档明确 M6 是本地等价 PR 闭环，不是远端 PR/部署完成。

## 8. 黑盒测试

至少覆盖：

1. 从 demo issue 创建 Task 并完成 Requirement/Design/Plan 审批。
2. 未批准计划不能启动 M6。
3. Coder 经 Tool Gateway 产生真实文件变化。
4. Tester 执行真实 pytest，成功和失败均落库。
5. Reviewer 读取真实 diff 与 AC，缺项时阻断 Security。
6. Security 执行真实工具或返回 partial/blocked，阻断时不能创建 PR record。
7. Git Tool 创建真实本地 branch 和 commit。
8. Platform API 返回真实 artifact 和本地 PR record。
9. 重复请求不重复写文件、commit 或 record。
10. pause/cancel 阻止后续副作用并关闭 active 记录。
11. 控制台通过 SSE 无手工刷新展示阶段和 artifact。
12. Agent Timeline 继续证明所有普通角色使用同一 root conversation。

## 9. 白盒测试

至少覆盖：

- 新 Agent schema 成功、缺字段、非法 enum、断裂引用和超长输出。
- 稳定输出 schema/工具定义跨所有普通角色完全一致。
- root conversation 前缀、tool call/output 配对、格式修复与 subagent 隔离。
- Orchestrator 阶段、非法迁移、失败回退、review/security 阻断和恢复。
- Artifact/PR repository 分页、任务归属、事务回滚和唯一约束。
- Tool Gateway allowlist、敏感路径、脱敏、超时、限流、审批和幂等。
- Git 脏工作区、无变更、目录 pathspec、重复分支和重复 commit。
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
uv lock --check
uv run alembic downgrade <previous_revision>
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

- 解析全部共享 JSON Schema，并校验代表性 Agent/Artifact 输出。
- OpenAPI 与 FastAPI 精确比较。
- 浏览器回归 1280×720、1024×768、375×812，检查 diff/report/PR、SSE 和 console。
- `git diff --check`、secret scan、TODO/FIXME/NotImplemented/空 `pass`、
  普通生产源码超过 300 行检查。
- sample repo 与主仓库分别执行 `git status --short`，确认没有依赖、缓存、
  嵌套 `.git` 或凭据。
- 真实外部模型仅在 Agent/Tool/Conversation 契约变化时执行最小必要回归，
  凭据只临时注入进程。

## 11. 文档、进度与 Git

每完成一个可验证小步：

1. 更新 `PROJECT_PROGRESS.md`，记录命令、结果、缺陷闭环和剩余风险。
2. 满足完成判定后，在总排期勾选对应 M6 子项。
3. 修改 API/schema/事件/配置/状态机/安全边界时同步对应文档。
4. 检查 `git status`、`git diff --stat` 和关键 diff。
5. 按可验证粒度提交中文 commit，并 push 当前开发分支。
6. M6 全部完成后把本文件重写为 M7 详细计划。

## 12. M6 完成判定

只有全部满足才算 M6 完成：

- sample repo 可独立启动 `/health`、`/metrics` 并通过 pytest。
- Coder、Tester、Reviewer、Security Agent 均有结构化生产实现和测试。
- 普通 Agent 继续共享 Task root conversation，工具调用均经过 Tool Gateway。
- sample repo 产生真实 diff、测试报告、review、安全结果、branch 和 commit。
- Platform API 持久化真实 Artifact 和本地 PR record，并写完整 EventLog。
- 控制台展示真实 diff/test/security/review/PR，三种视口和 SSE 通过。
- migrations、全部模块测试、sample repo、OpenAPI、JSON Schema 和静态检查通过。
- 总排期、`PROJECT_PROGRESS.md` 和下一阶段 `PROJECT_PLAN.md` 同步。
- 已按小步提交并推送 `dev` 或 M6 功能分支。

## 13. 风险与阻塞

- Docker sandbox 成本过高：可继续使用受控目录，但只允许 sample repo，并记录
  网络/资源隔离不足。
- 安全 CLI 不可用：局部安装或 Docker；仍不可用时标记 blocked/partial，
  不得伪造通过。
- Git Tool 影响主仓库：sample repo 使用独立目录和显式 root，每步前后检查
  两个仓库状态。
- 外部 LLM 不可用：按 `v0.4.3` 重试/暂停语义记录；本地 Provider 不能伪造
  Coder 真实执行结果。
- Windows symlink 权限不足：保留跳过条件，但不放宽 allowlist。
- 真实远端 Git 不存在：生成本地 PR record 和 patch artifact，明确等价边界。
- 上下文增长过快：M6 先测量 root conversation 体积；达到阈值前补
  compaction/truncation 设计，不能静默丢历史。
- 任一工具、测试、review 或安全门禁失败：写失败记录并回到可恢复状态，
  不创建 PR record、不勾选完成。
