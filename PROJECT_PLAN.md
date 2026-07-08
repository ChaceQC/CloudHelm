# PROJECT_PLAN.md

本文件只记录当前下一步要落实的详细执行计划，不保存总项目规划。总流程和打钩清单见 `docs/14-roadmap/03-implementation-milestone-flow.md`。

## 1. 当前阶段

M2：数据模型、API 与事件底座。

## 2. 阶段目标

在 M1 Monorepo 最小工程基础上，完成 CloudHelm 平台核心数据与 API 底座，使控制台和后续 Agent 编排可以使用真实持久化数据，而不是静态假数据或内存 mock。

本阶段目标：

- 建立 Project、Task、RequirementSpec、TechnicalDesign、AgentRun、ToolCall、ApprovalRequest、EventLog 的真实数据库模型。
- 建立数据库连接、session 管理、迁移脚本和本地 PostgreSQL 开发配置。
- 建立 API、schemas、services、repositories、models 分层。
- 实现 Project API、Task API、Requirement / Design API、Agent Run API、Tool Call API、Approval API、Event Timeline API。
- 每次任务、需求、设计、审批等状态变化写入 `event_logs`。
- 同步更新 OpenAPI、JSON Schema、README、API 文档和本地开发命令。
- 版本影响：本阶段属于兼容新增能力，完成时项目版本应从 `0.1.0` 提升到 `0.2.0`，并同步 `README.md`、`modules/platform-api/pyproject.toml`、`packages/shared-contracts/openapi/cloudhelm.openapi.yaml` 和后端响应版本。

本阶段不实现 Agent 自动生成、Tool Gateway 执行、真实代码修改、远端部署或监控业务逻辑。

## 3. 必须先参考的资料

开始编码前必须阅读：

- `AGENTS.md`
- `docs/14-roadmap/03-implementation-milestone-flow.md`
- `docs/03-modules/00-module-map.md`
- `docs/03-modules/modules/platform-api.md`
- `docs/03-modules/packages/shared-contracts.md`
- `docs/07-data/00-entity-model.md`
- `docs/07-data/01-database-schema.md`
- `docs/15-detailed-design/00-mvp-scope-and-cutline.md`
- `docs/15-detailed-design/01-module-contracts.md`
- `docs/15-detailed-design/03-api-detail.md`
- `docs/15-detailed-design/04-data-detail.md`
- `docs/15-detailed-design/05-workflow-state-events.md`
- `docs/08-api/00-api-overview.md`
- `docs/08-api/01-task-api.md`
- `docs/08-api/02-requirement-design-api.md`
- `docs/08-api/03-agent-run-api.md`
- `docs/08-api/04-tool-call-api.md`
- `docs/08-api/05-approval-api.md`
- `docs/08-api/06-event-stream-api.md`

实现时应参考成熟方案和官方文档：

- FastAPI 分层、dependencies、错误处理、OpenAPI 生成。
- Pydantic v2 DTO、字段校验、枚举和 datetime 序列化。
- SQLAlchemy 2.x ORM、session 生命周期和 repository 模式。
- Alembic migration、PostgreSQL UUID、JSONB、TIMESTAMPTZ、索引。
- PostgreSQL 官方数据类型和约束。
- Starlette/FastAPI `StreamingResponse` 或成熟 SSE 方案，用于事件流端点。
- pytest、FastAPI TestClient / httpx 和测试数据库实践。

本阶段搜索或查阅到的外部资料应归档到：

- `informations/m2-data-api/official-references.md`

归档必须包含检索日期、官方链接、适用子任务、采用命令或工程实践、不采用或延后采用的能力及原因；不得保存真实密钥、账号、Cookie、服务器地址或第三方文档全文。

## 4. 本阶段不做的事项

- 不实现 Requirement / Architect / Planner / Coder / Tester / Reviewer 等 Agent。
- 不实现 LangGraph 编排和 Agent 自动推进。
- 不实现 Tool Gateway 的真实工具执行、审批拦截和 MCP 路由。
- 不实现 Git branch、commit、PR。
- 不实现远端部署、Remote Agent、Deployment Controller、Prometheus、Loki 或 Alertmanager。
- 不用内存列表、固定返回、假任务、假 AgentRun 或假 ToolCall 冒充真实功能。
- 不为了测试方便把 mock/stub/fake 放入生产代码路径。

## 5. 预检步骤

### 5.1 检查当前 M1 基线

执行：

```powershell
Get-ChildItem -Force
Get-ChildItem apps,modules,packages,infra,examples,tests,informations
cd modules/platform-api
uv run pytest
cd ..\..\apps\control-console
npm.cmd run build
```

确认：

- `modules/platform-api` 的 `/health` 测试通过。
- `apps/control-console` 可构建。
- `packages/shared-contracts` 已存在 OpenAPI 和 schema 起点。
- `docs/14-roadmap/03-implementation-milestone-flow.md` 中 M1 已全部勾选。

### 5.2 检查本机工具和数据库能力

执行：

```powershell
uv --version
python --version
docker --version
docker compose version
git --version
```

处理规则：

- 如果 Docker 不可用，不得把 M2 标记完成；先在 `PROJECT_PROGRESS.md` 记录阻塞，并选择是否仅完成代码草案但保持阶段未完成。
- 如果 PostgreSQL 容器无法启动，不得改用内存 mock 冒充数据库；可使用项目内测试数据库方案，但必须记录差异和后续修复。
- Python 依赖继续写入 `modules/platform-api/pyproject.toml` 和 `uv.lock`。
- 不全局安装数据库、Alembic 或测试工具；优先使用 `uv add`、`uv run` 和 `infra/docker-compose.dev.yml`。

## 6. 详细任务拆分

### 6.1 创建 M2 资料归档

创建或更新：

```text
informations/
└── m2-data-api/
    └── official-references.md
```

必须覆盖：

- FastAPI dependencies、APIRouter、错误响应和 OpenAPI。
- SQLAlchemy 2.x ORM 映射、session 管理、事务边界。
- Alembic 初始化、迁移生成和应用命令。
- PostgreSQL UUID、JSONB、TIMESTAMPTZ、索引。
- Pydantic v2 schema / enum / datetime。
- pytest + 数据库测试实践。

完成后在 `PROJECT_PROGRESS.md` 记录已查阅资料和采用结论。

### 6.2 补充后端依赖和配置

修改：

```text
modules/platform-api/pyproject.toml
modules/platform-api/src/cloudhelm_platform_api/core/config.py
modules/platform-api/README.md
README.md
.env.example
```

新增依赖建议：

```powershell
cd modules/platform-api
uv add sqlalchemy alembic "psycopg[binary]"
uv add --dev pytest
```

配置要求：

- 新增 `CLOUDHELM_DATABASE_URL`，本地默认示例为 PostgreSQL，不在生产代码里硬编码真实地址。
- 保留 `CLOUDHELM_ENV`、`CLOUDHELM_VERSION`。
- 如引入 Redis 配置，只先声明示例值，不在 M2 强行使用。
- 同步版本到 `0.2.0`。

### 6.3 建立本地 PostgreSQL 开发配置

创建：

```text
infra/
└── docker-compose.dev.yml
```

要求：

- 至少包含 PostgreSQL 服务。
- 可选包含 Redis，但如果未被 M2 代码使用，应在 README 写明“预留，未接入生产路径”。
- 使用示例用户名、密码和数据库名，不写真实凭据。
- 暴露端口必须可通过 `.env.example` 调整或清楚说明。
- 不直接暴露非必要管理入口。

建议验证：

```powershell
docker compose -f infra/docker-compose.dev.yml up -d postgres
docker compose -f infra/docker-compose.dev.yml ps
```

### 6.4 初始化数据库分层和迁移

建议结构：

```text
modules/platform-api/
├── alembic.ini
├── migrations/
│   ├── env.py
│   └── versions/
├── src/cloudhelm_platform_api/
│   ├── db/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   └── session.py
│   └── models/
│       ├── __init__.py
│       ├── project.py
│       ├── task.py
│       ├── requirement.py
│       ├── design.py
│       ├── agent_run.py
│       ├── tool_call.py
│       ├── approval.py
│       └── event_log.py
```

实现要求：

- 使用 SQLAlchemy 2.x typed ORM。
- 主键使用 UUID。
- JSON 字段在 PostgreSQL 使用 JSONB。
- 时间字段使用 timezone-aware datetime。
- 表结构与 `docs/07-data/01-database-schema.md`、`docs/15-detailed-design/04-data-detail.md` 对齐。
- 为 `tasks(project_id, status)`、`event_logs(task_id, created_at)` 等关键查询建立索引。
- 迁移文件必须可通过 Alembic 应用到 PostgreSQL。

建议命令：

```powershell
cd modules/platform-api
uv run alembic revision --autogenerate -m "create core m2 tables"
uv run alembic upgrade head
```

如果 autogenerate 与设计文档不一致，先修正 model 或 migration，不允许直接忽略差异。

完成后在总流程中勾选：

```markdown
- [x] 实现 projects、tasks、requirement_specs、technical_designs、agent_runs、tool_calls、approval_requests、event_logs 基础表。
```

### 6.5 建立 schemas、错误结构和 API 响应规范

建议新增：

```text
modules/platform-api/src/cloudhelm_platform_api/
├── schemas/
│   ├── common.py
│   ├── project.py
│   ├── task.py
│   ├── requirement.py
│   ├── design.py
│   ├── agent_run.py
│   ├── tool_call.py
│   ├── approval.py
│   └── event_log.py
└── api/
    ├── errors.py
    └── deps.py
```

要求：

- 通用成功响应、分页响应和错误响应与 `docs/15-detailed-design/03-api-detail.md` 对齐。
- DTO 必须有字段说明、必要枚举、输入校验和示例。
- 错误响应必须包含 `code`、`message`、`detail`、`trace_id`。
- 路由函数不直接写 SQL。

完成后在总流程中勾选：

```markdown
- [x] 建立 API、schemas、services、repositories、models 分层。
```

### 6.6 实现 repositories 与 services

建议结构：

```text
modules/platform-api/src/cloudhelm_platform_api/
├── repositories/
│   ├── __init__.py
│   ├── project_repository.py
│   ├── task_repository.py
│   ├── requirement_repository.py
│   ├── design_repository.py
│   ├── agent_run_repository.py
│   ├── tool_call_repository.py
│   ├── approval_repository.py
│   └── event_log_repository.py
└── services/
    ├── __init__.py
    ├── project_service.py
    ├── task_service.py
    ├── requirement_service.py
    ├── design_service.py
    ├── agent_run_service.py
    ├── tool_call_service.py
    ├── approval_service.py
    └── event_service.py
```

要求：

- Repository 只处理数据库访问。
- Service 负责业务规则、状态变更和事件写入。
- 创建 Project 写入 `ProjectCreated`。
- 创建 Task 写入 `TaskCreated`，初始 `status=created`、`current_phase=Created`。
- 暂停、恢复、取消 Task 必须更新任务状态并写事件。
- Requirement / Design 创建、审批、退回必须写事件。
- Approval approve / reject 必须写事件。
- 所有写操作在同一事务内完成业务记录和事件记录，避免状态与事件不一致。

### 6.7 实现 Project API 和 Task API

建议新增：

```text
modules/platform-api/src/cloudhelm_platform_api/api/projects.py
modules/platform-api/src/cloudhelm_platform_api/api/tasks.py
```

至少实现：

```text
POST   /api/projects
GET    /api/projects
GET    /api/projects/{project_id}

POST   /api/tasks
GET    /api/tasks
GET    /api/tasks/{task_id}
POST   /api/tasks/{task_id}/pause
POST   /api/tasks/{task_id}/resume
POST   /api/tasks/{task_id}/cancel
```

要求：

- 列表接口支持 `limit` 和 `cursor` 或明确的分页占位实现。
- 创建任务必须校验 `project_id` 存在。
- 状态变更必须校验合法状态，不允许取消已完成任务等无效流转。
- 每个状态变更写入 `event_logs`。

完成后在总流程中勾选：

```markdown
- [x] 实现 Project API 和 Task API。
```

### 6.8 实现 Requirement / Design API

建议新增：

```text
modules/platform-api/src/cloudhelm_platform_api/api/requirements.py
modules/platform-api/src/cloudhelm_platform_api/api/designs.py
```

至少实现：

```text
POST   /api/tasks/{task_id}/requirements
GET    /api/tasks/{task_id}/requirements
GET    /api/requirements/{requirement_id}
POST   /api/requirements/{requirement_id}/approve
POST   /api/requirements/{requirement_id}/request-changes

POST   /api/tasks/{task_id}/technical-designs
GET    /api/tasks/{task_id}/technical-designs
GET    /api/technical-designs/{design_id}
POST   /api/technical-designs/{design_id}/approve
POST   /api/technical-designs/{design_id}/request-changes
```

要求：

- M2 不自动生成 Requirement 或 Design，但允许真实保存用户或后续 Agent 提供的结构化内容。
- `acceptance_criteria_json`、`constraints_json`、`openapi_json`、`db_schema_json` 必须保存为真实 JSON 字段。
- 审批动作更新状态并写入事件。

完成后在总流程中勾选：

```markdown
- [x] 实现 Requirement / Design API。
```

### 6.9 实现 Agent Run、Tool Call、Approval API

建议新增：

```text
modules/platform-api/src/cloudhelm_platform_api/api/agent_runs.py
modules/platform-api/src/cloudhelm_platform_api/api/tool_calls.py
modules/platform-api/src/cloudhelm_platform_api/api/approvals.py
```

至少实现：

```text
GET    /api/tasks/{task_id}/agent-runs
GET    /api/agent-runs/{run_id}

GET    /api/tasks/{task_id}/tool-calls
GET    /api/tool-calls/{tool_call_id}

GET    /api/approvals
GET    /api/approvals/{approval_id}
POST   /api/approvals/{approval_id}/approve
POST   /api/approvals/{approval_id}/reject
```

M2 可增加内部或开发用创建接口，但必须在文档中说明调用方和风险，不能伪装成 Agent 已经自动运行。

要求：

- 查询结果来自数据库。
- ToolCall 必须包含工具名、风险等级、状态、参数摘要或脱敏字段。
- L3/L4 Approval 决策必须写入事件。

完成后在总流程中勾选：

```markdown
- [x] 实现 Agent Run、Tool Call、Approval、Event Stream API。
```

### 6.10 实现 Event Timeline 与事件流

建议新增：

```text
modules/platform-api/src/cloudhelm_platform_api/api/events.py
```

至少实现：

```text
GET /api/tasks/{task_id}/timeline
GET /api/tasks/{task_id}/events/stream
```

要求：

- Timeline 从 `event_logs` 按 `created_at` 排序返回。
- SSE 或流式端点必须只读取真实事件；如果 M2 暂不做实时推送，可先实现带心跳的轮询式事件流，并在文档和 `PROJECT_PROGRESS.md` 明确边界。
- 每次任务状态变化写入 `event_logs`。

完成后在总流程中勾选：

```markdown
- [x] 每次任务状态变化写入 `event_logs`。
```

### 6.11 同步共享契约和 API 文档

修改：

```text
packages/shared-contracts/openapi/cloudhelm.openapi.yaml
packages/shared-contracts/schemas/events/task-event.schema.json
packages/shared-contracts/schemas/tools/tool-risk-level.schema.json
docs/08-api/*.md
docs/15-detailed-design/03-api-detail.md
docs/15-detailed-design/04-data-detail.md
README.md
modules/platform-api/README.md
```

要求：

- OpenAPI 覆盖 M2 已实现接口、请求体、响应体、错误结构。
- Event schema 增加 M2 真实事件类型建议或枚举。
- 文档说明 M2 不包含 Agent 自动执行和 Tool Gateway 真实执行。
- 如 API 路径、字段或错误码与设计文档冲突，先更新设计文档再实现。

完成后在总流程中勾选：

```markdown
- [x] 同步更新 `docs/08-api/` 和数据表文档。
```

### 6.12 测试与验证

至少新增或更新：

```text
modules/platform-api/tests/
├── test_health.py
├── test_projects_api.py
├── test_tasks_api.py
├── test_requirement_design_api.py
├── test_agent_tool_approval_api.py
└── test_event_timeline_api.py
```

必须验证：

- Alembic migration 可应用。
- `POST /api/projects` 写入真实项目。
- `POST /api/tasks` 写入真实任务并产生 `TaskCreated` 事件。
- pause / resume / cancel 产生对应事件。
- Requirement / Design 创建和审批产生事件。
- Approval approve / reject 产生事件。
- Timeline 能按任务返回真实事件。
- `/health` 仍通过。

建议命令：

```powershell
docker compose -f infra/docker-compose.dev.yml up -d postgres
cd modules/platform-api
$env:CLOUDHELM_DATABASE_URL='postgresql+psycopg://cloudhelm:cloudhelm_dev@127.0.0.1:15432/cloudhelm'
uv run alembic upgrade head
uv run pytest
```

如果测试数据库不可用，必须记录阻塞和未验证范围，不得把 M2 标记完成。

## 7. 完成后的同步动作

M2 所有任务完成后必须：

1. 更新 `docs/14-roadmap/03-implementation-milestone-flow.md`，将 M2 下所有任务打钩。
2. 更新 `PROJECT_PROGRESS.md`，记录：
   - 已创建或修改的文件。
   - 数据库迁移和 API 实现范围。
   - 已执行命令和结果。
   - 未完成或阻塞项。
   - 下一步 M3。
3. 重写 `PROJECT_PLAN.md`，生成 M3“控制台任务主流程”的详细计划。
4. 同步 `README.md`、`modules/platform-api/README.md`、`docs/08-api/`、`docs/15-detailed-design/` 和共享契约。
5. 确认版本号已同步为 `0.2.0`，并说明本阶段属于兼容新增能力。

## 8. M2 完成判定

只有全部满足才算 M2 完成：

- PostgreSQL 开发配置存在且可启动。
- Alembic migration 可创建并应用核心表。
- `projects`、`tasks`、`requirement_specs`、`technical_designs`、`agent_runs`、`tool_calls`、`approval_requests`、`event_logs` 基础表存在。
- API、schemas、services、repositories、models 分层清晰。
- Project API 和 Task API 使用真实数据库。
- Requirement / Design API 使用真实数据库。
- Agent Run、Tool Call、Approval、Event Timeline API 返回真实数据库记录。
- 每次任务状态变化写入 `event_logs`。
- OpenAPI 和相关 docs 已同步。
- `uv run pytest` 通过，且测试覆盖核心写入与事件记录。
- `PROJECT_PROGRESS.md` 记录验证命令和结果。
- 总排期流程中 M2 的具体任务已打钩。

## 9. 风险与处理

- 如果 Docker 或 PostgreSQL 不可用：记录阻塞，不把数据库能力标记为完成。
- 如果 Alembic autogenerate 与设计文档不一致：先修正 model 或 migration，再继续。
- 如果 SQLAlchemy JSON/UUID 字段在测试数据库和 PostgreSQL 行为不同：以 PostgreSQL 为准，测试说明差异。
- 如果 API 设计与 `docs/15-detailed-design/03-api-detail.md` 冲突：先更新设计文档和共享契约，再写代码。
- 如果事件写入和业务写入不能保持事务一致：暂停实现并调整 service/repository 边界。
- 如果为了赶进度只返回静态对象或内存列表：该能力不得标记完成，必须回滚或改为真实数据库实现。
