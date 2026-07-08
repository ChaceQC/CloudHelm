# PROJECT_PLAN.md

本文件只记录当前下一步要落实的详细执行计划，不保存总项目规划。总流程和打钩清单见 `docs/14-roadmap/03-implementation-milestone-flow.md`。

## 1. 当前阶段

M5：Tool Gateway 与本地工具层。

## 2. 阶段目标

在 M4 已完成 Requirement / Architect / Planner 结构化编排的基础上，建立所有后续 Agent 工具调用的统一入口。M5 只实现本地开发闭环所需的低风险工具底座，不执行远端部署、不接生产权限、不绕过审批。

本阶段目标：

- 新增 `modules/tool-gateway`，实现工具注册、参数校验、风险等级、审批拦截、审计记录和执行结果脱敏摘要。
- 新增最小 Tool Server / Adapter：Requirement Tool、Design Tool、Repo Tool、Sandbox Tool、Git Tool。
- Repo Tool 支持在受控 worktree 内真实读取、搜索和写入文件；必须限制路径越界和敏感文件。
- Sandbox Tool 支持在本地隔离目录执行命令、超时、中断、stdout/stderr 摘要和 artifact 记录；M5 可先不接 Docker，但必须说明隔离边界。
- Git Tool 支持 `status`、`diff`、`branch`、`commit` 的本地受控操作；不自动 push，不创建远端 PR。
- Platform API 新增 Tool Gateway 调用入口或内部 service，所有工具调用写入 `tool_calls` 和 `event_logs`。
- 控制台展示真实 ToolCall 参数摘要、风险等级、状态、输出摘要和审批状态。
- 同步 OpenAPI、工具 schema、模块契约、安全文档、测试记录、总排期和进度。

M5 不实现 Coder/Tester/Reviewer 的完整自动开发闭环，不执行远端 SSH、Docker Compose 部署、CI/CD、监控告警和生产环境操作。所有 L3/L4 动作只能创建 ApprovalRequest，不得自动执行。

版本影响：M5 新增 Tool Gateway、工具 schema、ToolCall 执行语义和可能的新 API，属于兼容新增能力。完成后建议提升到 `0.4.0`，同步 `README.md`、`.env.example`、模块版本、OpenAPI 和相关文档。

## 3. 必须先参考的资料

开始编码前必须阅读：

- `AGENTS.md`
- `docs/14-roadmap/03-implementation-milestone-flow.md`
- `docs/05-tool-layer/00-tool-gateway.md`
- `docs/05-tool-layer/01-risk-levels.md`
- `docs/05-tool-layer/02-mcp-tool-server-structure.md`
- `docs/08-api/04-tool-call-api.md`
- `docs/08-api/05-approval-api.md`
- `docs/10-security/00-security-boundary.md`
- `docs/10-security/01-permission-model.md`
- `docs/10-security/02-audit-log.md`
- `docs/15-detailed-design/00-mvp-scope-and-cutline.md`
- `docs/15-detailed-design/01-module-contracts.md`
- `docs/15-detailed-design/02-agent-tool-contract.md`
- `docs/15-detailed-design/03-api-detail.md`
- `docs/15-detailed-design/04-data-detail.md`
- `docs/15-detailed-design/05-workflow-state-events.md`
- `packages/shared-contracts/openapi/cloudhelm.openapi.yaml`
- `packages/shared-contracts/schemas/tools/tool-risk-level.schema.json`
- `modules/platform-api/README.md`
- `modules/orchestrator/README.md`

实现时应参考成熟方案和官方文档：

- Pydantic / JSON Schema 参数校验。
- Python `pathlib`、`subprocess`、`tempfile` 安全用法。
- Git CLI 本地状态、diff、commit 的可审计调用方式。
- Docker / sandbox 执行隔离实践；若暂不接 Docker，必须说明原因和替代边界。
- MCP Tool Server 的工具声明、参数 schema、返回 schema 和错误结构。
- pytest 对文件系统、命令超时、路径越界、审批拦截和事务副作用的测试实践。

本阶段搜索或查阅到的外部资料应归档到：

```text
informations/m5-tool-gateway/official-references.md
```

## 4. 本阶段不做的事项

- 不让 Agent 直接调用 `subprocess`、Git、文件系统或 Docker；所有生产路径必须经 Tool Gateway。
- 不执行远端 SSH、远端部署、服务重启、回滚、数据库 destructive migration 或生产环境动作。
- 不自动 push、创建远端 PR、操作 GitHub/Gitea 远端。
- 不把工具执行失败吞掉或伪装成功。
- 不在生产代码中使用固定 ToolCall 结果、mock repo、假 stdout 或假 diff。
- 不读取或写入 `.env`、密钥、私钥、证书、依赖目录、构建产物和工作区外路径。
- 不新增复杂插件市场、多租户权限或分布式队列；M5 先完成本地可验证工具底座。

## 5. 预检步骤

### 5.1 Git 与工作区

```powershell
git branch --show-current
git status --short
```

确认当前分支为 `dev`。若在 `main`，必须先切回 `dev` 或从 `dev` 拉出功能分支。

### 5.2 后端 M4 基线

```powershell
docker compose -f infra/docker-compose.dev.yml up -d postgres
cd modules/platform-api
$env:CLOUDHELM_DATABASE_URL='postgresql+psycopg://cloudhelm:cloudhelm_dev@127.0.0.1:15432/cloudhelm'
uv run alembic upgrade head
uv run pytest
```

### 5.3 Agent / Orchestrator 基线

```powershell
cd modules/agent-runtime
uv run pytest

cd ..\orchestrator
uv run pytest
```

### 5.4 前端 M4 基线

```powershell
cd apps/control-console
npm.cmd install
npm.cmd run build
```

### 5.5 工具执行边界预检

确认本地工具只作用于仓库内测试目录或 `examples/`：

```powershell
Get-ChildItem examples -Force
Get-ChildItem modules -Force
git status --short
```

若需要创建 sample worktree 或 sandbox 目录，优先放在 `examples/`、`tests/fixtures/` 或模块内临时目录，不得污染系统全局路径。

## 6. 详细任务拆分

### 6.1 创建 M5 资料归档

创建：

```text
informations/m5-tool-gateway/official-references.md
```

必须覆盖：

- Pydantic / JSON Schema 参数校验。
- Python 安全路径处理和 subprocess 超时。
- Git CLI 本地操作参考。
- Docker / sandbox 隔离参考与取舍。
- MCP Tool Server 工具契约参考。
- pytest 文件系统和命令执行测试参考。

完成后在 `PROJECT_PROGRESS.md` 记录已查阅资料和采用结论。

### 6.2 补充共享工具契约

建议新增或更新：

```text
packages/shared-contracts/schemas/tools/
  tool-call-request.schema.json
  tool-call-result.schema.json
  repo-tool.schema.json
  sandbox-tool.schema.json
  git-tool.schema.json
  requirement-tool.schema.json
  design-tool.schema.json
packages/shared-contracts/openapi/cloudhelm.openapi.yaml
docs/15-detailed-design/02-agent-tool-contract.md
docs/15-detailed-design/03-api-detail.md
docs/15-detailed-design/04-data-detail.md
```

要求：

- 每个工具声明工具名、参数 schema、返回 schema、风险等级、是否需要审批、审计字段。
- ToolCallRequest 必须包含 `task_id`、`agent_run_id`、`tool_name`、`risk_level`、`idempotency_key`、`arguments`、`reason`。
- ToolResult 必须包含 `status`、`summary`、`result_json`、`stdout_summary`、`stderr_summary`、`duration_ms`、`started_at`、`finished_at`、`error_code`。
- L3/L4 工具 schema 必须标记 `requires_approval=true`，M5 只创建审批，不执行动作。

### 6.3 建立 `modules/tool-gateway`

建议新增：

```text
modules/tool-gateway/
  pyproject.toml
  README.md
  src/cloudhelm_tool_gateway/
    __init__.py
    registry.py
    gateway.py
    policies.py
    audit.py
    schemas/
      tool_call.py
      repo.py
      sandbox.py
      git.py
      requirement.py
      design.py
    tools/
      repo_tool.py
      sandbox_tool.py
      git_tool.py
      requirement_tool.py
      design_tool.py
    tests/
      test_registry.py
      test_policy.py
      test_repo_tool.py
      test_sandbox_tool.py
      test_git_tool.py
```

要求：

- `registry.py` 只负责注册和查找工具声明。
- `gateway.py` 负责统一执行流程：校验参数 -> 判定风险 -> 审批拦截 -> 执行工具 -> 摘要脱敏 -> 返回结果。
- `policies.py` 负责路径边界、风险等级、敏感文件、命令 allowlist/denylist、超时上限。
- `audit.py` 负责形成可写入 Platform API 的审计摘要，不直接写数据库。
- 工具实现不得直接依赖 FastAPI 路由；Platform API 通过 service 调用 Gateway。

### 6.4 实现 Repo Tool

建议工具：

```text
repo.read_file
repo.search_text
repo.write_file
repo.list_files
```

要求：

- 所有路径必须解析到允许的 `workspace_root` 内，禁止 `..` 越界、绝对路径越界和 symlink 越界。
- 禁止读取或写入 `.env`、密钥、私钥、证书、依赖目录、构建产物、`.git` 内部文件。
- `repo.write_file` 默认 L1；覆盖大量文件或敏感目录必须升级风险或拒绝。
- 返回内容必须支持大小限制和摘要，避免把巨大文件完整写入 `tool_calls.result_json`。

### 6.5 实现 Sandbox Tool

建议工具：

```text
sandbox.run_command
sandbox.collect_artifact
```

要求：

- M5 可先使用本地受控工作目录 + `subprocess` 超时实现，并在 README 和进度中标明 Docker sandbox 留到 M6 前增强。
- 命令必须包含 `cwd`、`timeout_seconds`、`env` 白名单和输出大小限制。
- 默认禁止交互式命令、后台常驻服务、网络扫描、系统全局安装和删除工作区外文件。
- stdout/stderr 必须摘要化，完整输出如需保存只能写入 artifact 路径。

### 6.6 实现 Git Tool

建议工具：

```text
git.status
git.diff
git.create_branch
git.commit
```

要求：

- 只操作受控 repo 根目录。
- `git.status`、`git.diff` 为 L0/L1。
- `git.create_branch`、`git.commit` 为 L2，M5 可执行本地操作但必须写审计。
- 不允许 `push`、远端 PR、force reset、clean -fdx、rebase、tag release；这些留到后续阶段并需审批。

### 6.7 扩展 Platform API ToolCall 执行入口

建议新增或修改：

```text
modules/platform-api/src/cloudhelm_platform_api/api/tool_gateway.py
modules/platform-api/src/cloudhelm_platform_api/schemas/tool_gateway.py
modules/platform-api/src/cloudhelm_platform_api/services/tool_gateway_service.py
modules/platform-api/src/cloudhelm_platform_api/services/tool_call_service.py
```

建议接口：

```text
POST /api/tasks/{task_id}/tool-gateway/call
GET  /api/tool-gateway/tools
```

要求：

- 写操作必须在 service 层完成事务和事件副作用。
- 每次工具调用必须写 `tool_calls`，并写 `ToolCallStarted`、`ToolCallSucceeded`、`ToolCallFailed` 或 `ApprovalRequested`。
- L3/L4 或策略要求审批时，创建 `approval_requests`，ToolCall 状态为 `waiting_approval`，不得执行工具。
- API 返回统一错误结构和 `trace_id`。

### 6.8 控制台接入 ToolCall 展示

建议修改：

```text
apps/control-console/src/shared/types/api.ts
apps/control-console/src/shared/api/cloudhelmApi.ts
apps/control-console/src/features/tool-calls/ToolCallList.tsx
apps/control-console/src/features/tasks/TaskDetail.tsx
```

要求：

- 展示 ToolCall 的 `tool_name`、`risk_level`、`arguments_summary`、`status`、`approval_id`、`result_summary`、`error_code`。
- 若新增工具调用演示入口，只能面向开发/调试，且必须清楚标注真实工具执行范围和风险等级。
- 不展示假 ToolCall；无记录时保持真实空态。
- UI 风格继续参考 Codex 桌面端：低饱和、面板式、紧凑按钮、清晰边框，不使用营销式大视觉。

### 6.9 测试与验证设计

后端至少新增：

```text
modules/tool-gateway/tests/test_registry.py
modules/tool-gateway/tests/test_policy.py
modules/tool-gateway/tests/test_repo_tool.py
modules/tool-gateway/tests/test_sandbox_tool.py
modules/tool-gateway/tests/test_git_tool.py
modules/platform-api/tests/test_tool_gateway_api.py
```

黑盒测试要求：

- 查询工具注册表。
- 调用 `repo.read_file` 读取测试 fixture。
- 调用 `repo.write_file` 写入受控临时文件。
- 调用 `sandbox.run_command` 执行安全命令并记录输出摘要。
- 调用 L3/L4 示例动作时只创建 ApprovalRequest，不执行工具。
- 路径越界、敏感文件、非法命令、超时、重复 idempotency key 返回稳定错误和 `trace_id`。

白盒测试要求：

- Registry 重复注册、未知工具和 schema 校验分支。
- Policy 风险升级、路径越界、敏感文件拒绝、命令拒绝。
- Repo Tool symlink/绝对路径/`..` 越界分支。
- Sandbox Tool 超时、stderr、非零退出码、输出截断。
- Git Tool 非 repo、脏工作区、commit message 校验和禁止 push。
- Platform API 事务：ToolCall、ApprovalRequest、EventLog 同步写入或同步回滚。

至少执行：

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

## 7. 文档同步

必须更新：

```text
README.md
.env.example
modules/tool-gateway/README.md
modules/platform-api/README.md
apps/control-console/README.md
docs/05-tool-layer/*.md
docs/08-api/04-tool-call-api.md
docs/09-control-console/*.md
docs/10-security/*.md
docs/15-detailed-design/01-module-contracts.md
docs/15-detailed-design/02-agent-tool-contract.md
docs/15-detailed-design/03-api-detail.md
docs/15-detailed-design/04-data-detail.md
docs/15-detailed-design/05-workflow-state-events.md
docs/14-roadmap/03-implementation-milestone-flow.md
PROJECT_PROGRESS.md
```

要求：

- 文档必须说明 M5 能力边界：只完成本地工具入口和审计，不执行远端部署。
- 若 Sandbox 暂不接 Docker，必须说明临时隔离边界和 M6 前补强计划。
- OpenAPI、工具 schema、事件名称和控制台展示字段必须保持一致。

## 8. M5 完成判定

只有全部满足才算 M5 完成：

- Tool Gateway 能注册工具并统一执行校验、策略、审批、审计和结果摘要。
- Repo Tool、Sandbox Tool、Git Tool 至少完成 M5 要求的真实本地功能。
- L3/L4 或策略要求审批的工具不会执行，只创建 ApprovalRequest 和 waiting_approval ToolCall。
- 每次工具调用都写入真实 `tool_calls` 和 `event_logs`。
- 控制台能展示真实 ToolCall 记录、风险等级、状态、输出摘要和审批关联。
- 路径越界、敏感文件、非法命令、超时和工具失败均可追溯。
- `modules/tool-gateway`、`modules/platform-api`、`apps/control-console` 验证通过。
- `PROJECT_PROGRESS.md`、总排期流程和下一阶段 `PROJECT_PLAN.md` 已同步。

## 9. 风险与处理

- 如果 Docker sandbox 引入成本过高：M5 可先使用本地受控目录 + subprocess 超时，但必须在 README、进度和安全文档标明边界，并把 Docker 隔离补强列入 M6 前置任务。
- 如果 Repo Tool 路径边界不稳定：先停止写工具，仅保留只读工具，修复路径策略后再开放写入。
- 如果 Git Tool 可能混入无关改动：commit 工具必须要求显式文件列表并复查 diff；验证失败不得提交。
- 如果 Tool Gateway 与 Platform API 事务冲突：先补 service 契约，确保 ToolCall、ApprovalRequest、EventLog 在同一事务内一致。
- 如果验证失败：不得把 M5 任务打钩，不得提交“完成”类 commit；修复后必须执行回归测试。
