# PROJECT_PLAN.md

本文件只记录当前下一步要落实的详细执行计划，不保存总项目规划。总流程和打钩清单见 `docs/14-roadmap/03-implementation-milestone-flow.md`。

## 1. 当前阶段

M6：本地代码实现、测试与 PR 闭环。

## 2. 阶段目标

在 M5 已完成 Tool Gateway、Repo/Sandbox/Git 本地工具、审批拦截和审计记录的基础上，让 CloudHelm 能对一个受控 sample repo 完成最小本地开发闭环：

```text
已审批的 Development Plan
  -> Coder Agent 读取需求/设计/计划
  -> 通过 Tool Gateway 修改 sample repo
  -> Tester Agent 运行真实测试并记录报告
  -> Reviewer Agent 检查 diff、测试结果和验收标准
  -> Security Agent 执行本地可用安全检查
  -> Git Tool 创建本地 branch/commit
  -> Platform API 记录 PR 或等价 PR record
  -> 控制台展示 diff、测试报告、审查结论、安全结果和 PR record
```

M6 只做本地 sandbox / sample repo 闭环，不执行远端部署、不 push 到远端、不创建真实 GitHub/Gitea PR、不操作生产环境。若没有真实 Git 服务，必须生成等价 PR record 并在文档中说明边界。

版本影响：M6 新增 Coder/Tester/Reviewer/Security Agent、sample repo、artifact/test/security report、PR record 或等价 API，属于兼容新增能力。完成后建议提升到 `0.5.0`，同步 `README.md`、`.env.example`、OpenAPI、控制台和相关文档。

## 3. 必须先参考的资料

开始编码前必须阅读：

- `AGENTS.md`
- `docs/14-roadmap/03-implementation-milestone-flow.md`
- `docs/15-detailed-design/00-mvp-scope-and-cutline.md`
- `docs/15-detailed-design/01-module-contracts.md`
- `docs/15-detailed-design/02-agent-tool-contract.md`
- `docs/15-detailed-design/03-api-detail.md`
- `docs/15-detailed-design/04-data-detail.md`
- `docs/15-detailed-design/05-workflow-state-events.md`
- `docs/15-detailed-design/07-testing-acceptance-matrix.md`
- `docs/04-agents/` 下 Coder、Tester、Reviewer、Security 相关文档
- `docs/05-tool-layer/00-tool-gateway.md`
- `docs/05-tool-layer/tools/repo-tool.md`
- `docs/05-tool-layer/tools/sandbox-tool.md`
- `docs/05-tool-layer/tools/git-tool.md`
- `docs/06-workflows/00-development-to-pr.md`
- `docs/08-api/04-tool-call-api.md`
- `docs/10-security/00-security-boundary.md`
- `modules/tool-gateway/README.md`
- `modules/platform-api/README.md`
- `packages/shared-contracts/openapi/cloudhelm.openapi.yaml`

实现时应参考成熟方案和官方文档：

- FastAPI / SQLAlchemy 事务内写入 artifact、review、PR record 的做法。
- pytest 测试报告和临时目录实践。
- Git CLI 分支、diff、commit、format-patch 或本地 PR record 的可审计流程。
- Semgrep / Python 安全检查或依赖审计的本地最小接入方式；如果工具不可用，应记录替代验证。
- Docker sandbox 资源隔离实践；M6 前必须评估是否把 M5 本地 subprocess 边界增强为 Docker sandbox。

本阶段检索或查阅到的外部资料应归档到：

```text
informations/m6-code-test-pr/official-references.md
```

## 4. 本阶段不做的事项

- 不 push 到 GitHub/Gitea，不创建真实远端 PR；除非用户另行明确要求并提供远端。
- 不执行远端 SSH、远端部署、Docker Compose 上线、服务重启、回滚或监控告警。
- 不把 Agent 的代码修改写在 Platform API 路由或前端组件中。
- 不让 Agent 绕过 Tool Gateway 直接读写文件、执行命令或调用 Git。
- 不用 mock 代码、固定 diff、假测试报告、假 PR 链接冒充完成。
- 不在 sample repo、测试报告、日志或 PR record 中写入真实密钥、Token、Cookie 或服务器地址。

## 5. 预检步骤

### 5.1 Git 与工作区

```powershell
git branch --show-current
git status --short
```

确认当前分支为 `dev`。若在 `main`，必须先切回 `dev` 或从 `dev` 拉出功能分支。

### 5.2 M5 基线验证

```powershell
cd modules/tool-gateway
uv run pytest

cd ..\platform-api
$env:CLOUDHELM_DATABASE_URL='postgresql+psycopg://cloudhelm:cloudhelm_dev@127.0.0.1:15432/cloudhelm'
uv run alembic upgrade head
uv run pytest

cd ..\..\apps\control-console
npm.cmd run build
```

### 5.3 sample repo 边界预检

```powershell
Get-ChildItem examples -Force
Get-ChildItem modules/tool-gateway -Force
```

如果需要创建或重置 sample repo，必须放在 `examples/sample-repo-python/`，不得污染当前 CloudHelm 仓库根目录。

## 6. 详细任务拆分

### 6.1 创建 M6 资料归档

创建：

```text
informations/m6-code-test-pr/official-references.md
```

至少覆盖：

- FastAPI 示例项目结构。
- pytest 命令、测试报告和临时目录。
- Git 本地 branch/commit/format-patch/PR record 参考。
- Semgrep 或替代本地安全检查方式。
- Docker sandbox 增强取舍。

完成后在 `PROJECT_PROGRESS.md` 记录已查阅资料和采用结论。

### 6.2 准备 `examples/sample-repo-python`

建议创建：

```text
examples/sample-repo-python/
  README.md
  pyproject.toml
  src/sample_service/
    __init__.py
    main.py
  tests/
    test_health.py
  Dockerfile
  docker-compose.yml
  demo-issues/
    001-auth-profile.md
```

要求：

- 提供真实 FastAPI `/health` 和 `/metrics` 起点。
- 提供真实 pytest 测试，初始至少覆盖 `/health`。
- `demo-issues/001-auth-profile.md` 描述后续演示需求：用户注册、登录、个人资料。
- 初始化 sample repo 的独立 Git 仓库或可由 Git Tool 操作的受控目录；若嵌套 Git 不适合提交到主仓库，应记录原因并使用可复制初始化脚本。

### 6.3 扩展共享契约与数据模型

建议新增或更新：

```text
packages/shared-contracts/schemas/agents/coder-agent-output.schema.json
packages/shared-contracts/schemas/agents/tester-agent-output.schema.json
packages/shared-contracts/schemas/agents/reviewer-agent-output.schema.json
packages/shared-contracts/schemas/agents/security-agent-output.schema.json
packages/shared-contracts/schemas/artifacts/*.schema.json
packages/shared-contracts/openapi/cloudhelm.openapi.yaml
docs/15-detailed-design/03-api-detail.md
docs/15-detailed-design/04-data-detail.md
```

数据层建议新增：

- `artifacts`：保存 diff、测试报告、安全扫描报告、review 结果、PR record 等产物元数据。
- `pull_request_records`：保存本地等价 PR record，包含 base/head、commit hash、diff summary、review status、artifact refs。
- 必要时扩展 `agent_runs.structured_output_type` 枚举说明，不需要新增枚举表。

### 6.4 实现 Agent Runtime 扩展

建议新增：

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

- Agent 输出必须结构化，使用 Pydantic model 校验。
- Coder Agent 只生成可执行的文件修改计划和 Tool Gateway 调用请求，不直接写文件。
- Tester Agent 输出测试命令、通过标准、报告路径和失败摘要。
- Reviewer Agent 输出 diff 覆盖、验收标准匹配、风险和是否建议创建 PR record。
- Security Agent 输出本地可用安全检查命令、结果摘要和剩余风险。

### 6.5 扩展 Orchestrator 状态机

建议新增 M6 阶段：

```text
PlanningApproved -> Implementing -> Testing -> Reviewing -> SecurityChecking -> ReadyForPR
ReadyForPR -> Done
```

要求：

- 只有开发计划审批通过后才能进入 Implementing。
- 任一阶段失败必须进入 `failed` 或可重试状态，并写入 EventLog。
- 状态机纯函数测试必须覆盖非法迁移、失败恢复和审批缺失。

### 6.6 Platform API 编排与产物服务

建议新增或修改：

```text
modules/platform-api/src/cloudhelm_platform_api/models/artifact.py
modules/platform-api/src/cloudhelm_platform_api/models/pull_request_record.py
modules/platform-api/src/cloudhelm_platform_api/services/local_development_service.py
modules/platform-api/src/cloudhelm_platform_api/api/artifacts.py
modules/platform-api/src/cloudhelm_platform_api/api/pull_request_records.py
modules/platform-api/tests/test_local_development_workflow_api.py
```

要求：

- service 层通过 M5 Tool Gateway 调用 Repo/Sandbox/Git Tool，不在路由里直接执行工具。
- 每个阶段写入 AgentRun、ToolCall、Artifact、EventLog。
- 测试报告、安全报告和 review 结论必须来自真实命令或真实 diff，不得固定返回。
- PR record 必须关联任务、分支、commit hash、diff summary、测试报告、安全报告和 review 结论。

### 6.7 控制台展示本地开发闭环

建议修改：

```text
apps/control-console/src/features/diff-viewer/
apps/control-console/src/features/tasks/TaskDetail.tsx
apps/control-console/src/shared/types/api.ts
apps/control-console/src/shared/api/cloudhelmApi.ts
```

要求：

- 展示真实 diff summary、changed files、测试报告、安全报告、review 结论和 PR record。
- 无记录时保持真实空态，不展示假 diff、假测试或假 PR 链接。
- UI 继续参考 Codex 桌面端：低饱和、面板式、紧凑按钮、清晰边框。

### 6.8 测试与验证设计

黑盒测试至少覆盖：

- 从 demo issue 创建任务并进入 M6 本地开发流程。
- Coder 通过 Tool Gateway 修改 sample repo 文件。
- Tester 运行 sample repo 的真实 pytest。
- Reviewer 读取真实 diff 并输出 review 结论。
- Git Tool 创建本地 branch/commit。
- Platform API 返回真实 PR record。
- 控制台构建通过并能展示真实产物字段。

白盒测试至少覆盖：

- Agent 输出 schema 成功与失败分支。
- Orchestrator M6 状态迁移和非法迁移。
- Artifact / PR record service 的事务一致性。
- Tool Gateway 调用失败时 workflow 的失败记录和 EventLog。
- Git Tool 脏工作区、无变更、commit message 校验。
- Tester 命令失败、超时、stderr、报告截断。

至少执行：

```powershell
cd modules/tool-gateway
uv run pytest

cd ..\agent-runtime
uv run pytest

cd ..\orchestrator
uv run pytest

cd ..\platform-api
$env:CLOUDHELM_DATABASE_URL='postgresql+psycopg://cloudhelm:cloudhelm_dev@127.0.0.1:15432/cloudhelm'
uv run alembic upgrade head
uv run pytest

cd ..\..\examples\sample-repo-python
uv run pytest

cd ..\..\apps\control-console
npm.cmd run build
```

## 7. 文档同步

必须更新：

```text
README.md
.env.example
examples/sample-repo-python/README.md
modules/agent-runtime/README.md
modules/orchestrator/README.md
modules/platform-api/README.md
apps/control-console/README.md
docs/04-agents/*.md
docs/06-workflows/00-development-to-pr.md
docs/08-api/*.md
docs/09-control-console/*.md
docs/10-security/*.md
docs/15-detailed-design/*.md
docs/14-roadmap/03-implementation-milestone-flow.md
PROJECT_PROGRESS.md
```

要求：

- 文档必须说明 M6 是本地 sample repo 闭环，不是远端部署闭环。
- 如果没有真实远端 Git 服务，PR record 必须明确是等价记录。
- 如果 Docker sandbox 仍未接入，必须写明原因、边界和 M7 前风险。

## 8. M6 完成判定

只有全部满足才算 M6 完成：

- sample repo 可独立运行 `/health` 和 pytest。
- Coder/Tester/Reviewer/Security Agent 都有结构化输出和测试。
- 代码修改、测试命令和 Git 操作都经过 Tool Gateway。
- sample repo 产生真实 diff、测试报告、review 结论、安全结果和本地 commit。
- Platform API 记录 artifact 和 PR record，并写入 EventLog。
- 控制台展示真实 diff/test/security/review/PR record 信息。
- `modules/tool-gateway`、`modules/agent-runtime`、`modules/orchestrator`、`modules/platform-api`、`examples/sample-repo-python`、`apps/control-console` 验证通过。
- `PROJECT_PROGRESS.md`、总排期流程和下一阶段 `PROJECT_PLAN.md` 已同步。

## 9. 风险与处理

- 如果 Docker sandbox 增强成本过高：M6 可以继续使用 M5 本地受控目录，但必须限制在 sample repo，并把 Docker 隔离列为 M7 前置风险。
- 如果真实安全扫描工具不可用：先实现可复现的本地静态检查或依赖检查，并记录替代验证和后续补强。
- 如果 Git Tool 可能影响 CloudHelm 主仓库：sample repo 必须使用独立目录和显式 `repo_root`，测试前后检查 `git status --short`。
- 如果 workflow 任一工具失败：必须写失败 AgentRun、ToolCall 和 EventLog，不得伪装成功。
