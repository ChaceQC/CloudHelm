# PROJECT_PLAN.md

本文件只记录当前下一步要落实的详细执行计划，不保存总项目规划。总流程和打钩清单见 `docs/14-roadmap/03-implementation-milestone-flow.md`。

## 1. 当前阶段

M1-M5 二次实现审计与修复。

本阶段由用户在 `0.4.1` 基线上明确要求重新检查，不沿用此前“测试通过即完成”的结论。审计必须逐项核对 AGENTS.md、M1-M5 总排期、模块契约、API/数据/事件契约和真实生产代码；发现问题后直接修复、补测试、同步文档并发布补丁版本。

本阶段不进入 M6，不创建 sample repo、Coder/Tester/Reviewer/Security 执行闭环或 PR record。

## 2. 阶段目标

1. 证明 M1-M5 每个已打钩任务均有当前源码、数据库、契约、测试或浏览器证据。
2. 修复二次审计发现的状态版本、分页、错误响应、工具工作区、审计脱敏和控制台竞态问题。
3. 补齐黑盒与白盒测试，使正常路径、非法输入、过期资源、终态约束、数据持久化和失败恢复均有覆盖。
4. 保持 Gemini 式浅色控制台，不使用任何前端设计 Skill 或 ImageGen。
5. 完成后提升补丁版本，更新 `PROJECT_PROGRESS.md`，再把本文件恢复为下一阶段 M6 详细计划。

## 3. 必须查阅的本地依据

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
- `docs/05-tool-layer/00-tool-gateway.md`
- `docs/08-api/`
- `docs/09-control-console/`
- `docs/10-security/00-security-boundary.md`
- `packages/shared-contracts/`

本阶段涉及的成熟实践继续使用已有资料归档：

- `informations/m2-data-api/official-references.md`
- `informations/m3-control-console/official-references.md`
- `informations/m4-agent-orchestration/official-references.md`
- `informations/m5-tool-gateway/official-references.md`

## 4. 审计对象与已发现问题

### 4.1 数据/API/状态

- 需求、技术设计、开发计划的 `version` 字段没有真实递增。
- 旧 Requirement/TechnicalDesign 仍可通过直接评审 API 修改当前任务状态，缺少最新版约束。
- 新需求或新设计创建后没有统一失效下游旧产物和审批。
- 手工通过 Requirement/TechnicalDesign 后，任务阶段未进入可继续编排的阶段。
- 非法分页 cursor 被静默当成第一页，控制台列表默认读取最旧数据，超过分页上限后会漏掉最新记录。
- 未处理异常缺少统一 `code/message/detail/trace_id` 500 响应。
- Alembic metadata 检查存在未同步差异，必须通过 `alembic check`。

### 4.2 Tool Gateway

- `workspace_root` / `repo_root` 完全由调用方提供，缺少平台配置的允许根目录边界。
- ToolCall 没有持久化 Gateway 生成的 `audit_json` / 参数 hash。
- 原始参数可能把 `content`、Token 或密码写入数据库；stdout/stderr 和结果 JSON 缺少敏感模式脱敏。
- Agent ToolCall 未校验 Task 仍处于可执行状态。
- ToolCallRequest 共享 JSON Schema 与 Pydantic 模型不一致，工具声明未暴露返回 schema。

### 4.3 控制台

- Project/Task 异步请求缺少“只接受最后一次请求”保护，快速切换项目时旧响应可能覆盖新状态。
- 切换项目时旧任务列表和旧 Task Detail 可能短暂残留。
- Requirement/TechnicalDesign 历史版本仍显示可执行评审按钮。
- M2 SSE 端点回放后关闭，控制台关闭 EventSource 后没有真正重连或轮询新事件。
- 现有前端白盒测试只覆盖按钮策略和刷新回调，需要补请求竞态、评审状态和事件去重逻辑。

## 5. 详细任务拆分

### 5.1 建立版本与最新版不变量

修改：

```text
modules/platform-api/src/cloudhelm_platform_api/repositories/
modules/platform-api/src/cloudhelm_platform_api/services/
modules/platform-api/tests/
```

要求：

- Requirement、TechnicalDesign、DevelopmentPlan 按任务真实递增 `version`。
- 直接 approve/request-changes 只接受当前最新版资源，旧版本返回稳定 `409 stale_*`。
- 新 Requirement 使旧 Design、Plan 和待审批失效；新 Design 使旧 Plan 和待审批失效。
- 手工 Requirement approve 进入 `Designing`；手工 Design approve 进入 `Planning`，暂停任务保留 paused 状态。
- 增加正常、旧版本、暂停和级联失效测试。

### 5.2 修复分页与统一错误

修改：

```text
modules/platform-api/src/cloudhelm_platform_api/api/deps.py
modules/platform-api/src/cloudhelm_platform_api/api/errors.py
modules/platform-api/src/cloudhelm_platform_api/repositories/pagination.py
modules/platform-api/src/cloudhelm_platform_api/repositories/*_repository.py
modules/platform-api/tests/
```

要求：

- cursor 只接受非负十进制字符串；非法值返回统一 `422 validation_error`。
- 控制台列表类 API 优先返回最新记录；Event Timeline 保持可读顺序且不能永久漏掉最新事件。
- 增加未处理异常的统一 500 响应，并保留 `X-Trace-Id`。
- 文档明确分页排序。

### 5.3 收紧 Tool Gateway 工作区与任务状态

修改：

```text
modules/tool-gateway/src/cloudhelm_tool_gateway/policies.py
modules/tool-gateway/src/cloudhelm_tool_gateway/gateway.py
modules/platform-api/src/cloudhelm_platform_api/core/config.py
modules/platform-api/src/cloudhelm_platform_api/main.py
modules/platform-api/src/cloudhelm_platform_api/services/tool_gateway_service.py
.env.example
```

要求：

- 新增 `CLOUDHELM_TOOL_WORKSPACE_ROOTS`，未配置时默认拒绝文件、Sandbox 和 Git 工具。
- workspace 必须等于或位于允许根目录内；越界返回 `workspace_not_allowed`。
- AgentRun 调用工具时，Task 必须仍为 `running`；暂停、等待审批和终态任务均拒绝新副作用。
- 保留纯 Tool Gateway 测试使用的显式临时允许目录，不污染真实路径。

### 5.4 持久化审计并脱敏

新增迁移并修改：

```text
modules/platform-api/migrations/versions/20260710_0004_harden_m1_m5.py
modules/platform-api/src/cloudhelm_platform_api/models/tool_call.py
modules/platform-api/src/cloudhelm_platform_api/schemas/tool_call.py
modules/platform-api/src/cloudhelm_platform_api/services/tool_gateway_service.py
modules/tool-gateway/src/cloudhelm_tool_gateway/audit.py
modules/tool-gateway/src/cloudhelm_tool_gateway/gateway.py
```

要求：

- `tool_calls.audit_json` 保存 tool、task、AgentRun、风险、幂等键、参数 hash、原因 hash 和终态。
- 数据库存储参数前对密码、Token、Cookie、私钥字段脱敏；文件 `content` 只保存长度和 hash，不保存正文。
- stdout/stderr/result JSON 对常见 API Key、Bearer Token 和私钥块做模式脱敏。
- API 只返回可公开的审计 JSON。
- Alembic upgrade、downgrade 和 `alembic check` 均通过。

### 5.5 修复共享契约与工具声明

修改：

```text
packages/shared-contracts/schemas/tools/tool-call-request.schema.json
packages/shared-contracts/openapi/cloudhelm.openapi.yaml
modules/tool-gateway/src/cloudhelm_tool_gateway/registry.py
modules/platform-api/src/cloudhelm_platform_api/schemas/tool_gateway.py
apps/control-console/src/shared/types/api.ts
```

要求：

- ToolCallRequest 增加内部 `agent_type`，`arguments` 与生产 Pydantic 必填规则一致。
- ToolDeclaration 增加 `result_schema`。
- OpenAPI 与 `create_app().openapi()` 反序列化后精确一致。
- 所有 JSON Schema 可解析，代表性 Agent/Tool 输出能通过共享 schema 校验。

### 5.6 修复控制台竞态、评审操作和事件重连

修改：

```text
apps/control-console/src/features/projects/useProjects.ts
apps/control-console/src/features/tasks/useTasks.ts
apps/control-console/src/features/tasks/TaskDetail.tsx
apps/control-console/src/features/design-review/
apps/control-console/src/shared/api/cloudhelmApi.ts
apps/control-console/tests/
```

要求：

- Project/Task 请求使用序列门禁，只允许最后一次响应更新状态。
- 切换 Project 立即清空旧 Task 选择和列表。
- 只有当前 draft Requirement/TechnicalDesign 可以批准；当前 draft/approved 可要求修改，历史版本和终态按钮禁用。
- SSE 回放结束后按固定退避重连，并按 event id 去重；清理函数必须关闭连接和定时器。
- 使用 Node 内置测试运行器补纯逻辑白盒测试，不新增测试框架依赖。
- 保持现有 Gemini 式浅色布局和响应式断点。

### 5.7 文档、版本和进度同步

预计提升到 `0.4.2`，同步：

```text
.env.example
README.md
apps/control-console/README.md
modules/platform-api/README.md
modules/tool-gateway/README.md
docs/05-tool-layer/00-tool-gateway.md
docs/08-api/
docs/09-control-console/
docs/10-security/00-security-boundary.md
docs/15-detailed-design/
infra/README.md
PROJECT_PROGRESS.md
```

完成后将本文件恢复为 M6 详细执行计划，并把 `0.4.2` 作为 M6 前置基线。

## 6. 验证方式

### 后端与数据库

```powershell
cd modules/platform-api
$env:CLOUDHELM_DATABASE_URL='postgresql+psycopg://cloudhelm:cloudhelm_dev@127.0.0.1:15432/cloudhelm'
uv run alembic upgrade head
uv run alembic check
uv run pytest -q
```

### Agent / Orchestrator / Tool Gateway

```powershell
cd modules/agent-runtime
uv run pytest -q

cd ..\orchestrator
uv run pytest -q

cd ..\tool-gateway
uv run pytest -q
```

### 前端

```powershell
cd apps/control-console
npm.cmd test
npm.cmd run build
```

浏览器回归至少覆盖：

- 1280×720、1024×768、375×812。
- Project 快速切换后不显示旧 Task。
- 历史 Requirement/Design 按钮禁用。
- 外部 API 产生新事件后，控制台无需手工刷新即可更新。
- 无水平溢出、无 console error/warn。

### 契约与静态检查

- 解析全部 `packages/shared-contracts/schemas/**/*.json`。
- 校验代表性 Agent/Tool 输出。
- 比较 FastAPI OpenAPI 与共享 YAML。
- `git diff --check`。
- 扫描 TODO、FIXME、NotImplemented、空 `pass`、敏感凭据和超过 300 行的普通源码。

## 7. 完成判定

- M0-M5 总排期无未完成复选框，且每项均有当前证据。
- 本计划列出的缺陷均完成“发现 -> 修复 -> 回归 -> 记录”闭环。
- 所有自动化测试、迁移、OpenAPI、JSON Schema、静态检查和浏览器回归通过。
- `PROJECT_PROGRESS.md` 记录真实结果、剩余边界和 M6 下一步。
- 工作区只包含本阶段相关改动，提交并推送到 `origin/dev`。

## 8. 风险与阻塞处理

- Windows symlink 权限不足：保留跳过测试，但必须继续覆盖既有 symlink 和允许根目录越界。
- 外部 LLM 无真实 API Key：生产 provider 使用真实 HTTP 实现；请求/响应契约由隔离测试验证，实调边界记录到进度。
- M5 Sandbox 仍是本地 subprocess，不得描述为容器隔离；Docker、资源 quota 和网络隔离仍属于 M6 前置增强。
- 如果工作区允许根目录未配置，工具调用应明确失败，不能回退到任意路径访问。
