# 云舵 CloudHelm

CloudHelm 是面向毕业设计演示的多 Agent DevOps 系统。本仓库当前已完成 **M4：Agent 编排与规格化闭环**，在 M2 真实数据库 API 与 M3 控制台主流程之上，实现 Requirement / Architect / Planner 的最小可验收编排。

> 当前版本：`0.3.0`
> 当前范围：控制台可通过真实 Platform API 创建 Project/Task，启动和推进 M4 编排，生成并展示真实持久化的 Requirement Spec、Technical Design、Development Plan、AgentRun、Approval 和 Event Timeline。M4 不执行代码修改、Tool Gateway 真实工具调用、Git PR、远端部署或监控告警。

## 目录结构

```text
apps/
  control-console/        # React + TypeScript 控制台，M4 展示 Agent 编排闭环
modules/
  platform-api/           # FastAPI 平台 API，M4 提供数据、事件和编排入口
  agent-runtime/          # Requirement / Architect / Planner 结构化输出运行时
  orchestrator/           # M4 显式状态机与编排边界
packages/
  shared-contracts/       # OpenAPI、事件 schema、工具风险等级 schema、Agent 输出 schema
infra/                    # 本地 PostgreSQL Docker Compose 与后续部署配置
examples/                 # 后续演示仓库、演示 issue 和脚本
tests/                    # 后续跨模块集成测试和 E2E 测试
informations/             # 官方资料、命令来源和阶段性调研摘要
docs/                     # 设计文档与里程碑流程
```

## 后端：platform-api

先启动本地 PostgreSQL：

```powershell
docker compose -f infra/docker-compose.dev.yml up -d postgres
docker compose -f infra/docker-compose.dev.yml ps
```

再迁移数据库并运行测试：

```powershell
cd modules/platform-api
$env:CLOUDHELM_DATABASE_URL='postgresql+psycopg://cloudhelm:cloudhelm_dev@127.0.0.1:15432/cloudhelm'
uv run alembic upgrade head
uv run pytest
uv run uvicorn cloudhelm_platform_api.main:app --host 127.0.0.1 --port 18080
```

启动后可验证：

```powershell
Invoke-RestMethod http://127.0.0.1:18080/health
```

## Agent Runtime 与 Orchestrator

```powershell
cd modules/agent-runtime
uv run pytest

cd ..\orchestrator
uv run pytest
```

M4 默认使用 `CLOUDHELM_AGENT_PROVIDER=local_structured`，该 provider 基于真实 Task / Requirement / Design 输入生成结构化草案，并通过 Pydantic 校验。若切换到 `openai_compatible`，必须提供 `CLOUDHELM_LLM_MODEL`、`CLOUDHELM_LLM_API_BASE` 和 `CLOUDHELM_LLM_API_KEY`；缺配置时 API 会返回明确错误并写入失败 AgentRun 和 EventLog。

## 前端：control-console

Windows PowerShell 如果拦截 `npm.ps1`，使用 `npm.cmd`：

```powershell
cd apps/control-console
npm.cmd install
$env:VITE_CLOUDHELM_API_BASE_URL='http://127.0.0.1:18080'
npm.cmd run dev
```

构建验证：

```powershell
cd apps/control-console
npm.cmd run build
```

## 控制台 M4 主流程

- Project Sidebar：`GET /api/projects`、`POST /api/projects`。
- Task Board：`GET /api/tasks?project_id=...`、`POST /api/tasks`、`pause`、`resume`、`cancel`。
- M4 编排：`POST /api/tasks/{task_id}/start`、`POST /api/tasks/{task_id}/run-next`。
- Task Detail：读取 Requirement、Technical Design、DevelopmentPlan、AgentRun、ToolCall、Approval、Orchestration State 和 Timeline。
- SSE：优先连接 `GET /api/tasks/{task_id}/events/stream`；当前仍基于 `event_logs` 回放已有事件并追加 heartbeat，控制台在任务操作后重新读取 Timeline。

## 共享契约

- `packages/shared-contracts/openapi/cloudhelm.openapi.yaml`
- `packages/shared-contracts/schemas/agents/*.schema.json`
- `packages/shared-contracts/schemas/events/task-event.schema.json`
- `packages/shared-contracts/schemas/tools/tool-risk-level.schema.json`

OpenAPI 覆盖当前已实现接口；Agent 输出 schema 约束 Requirement / Architect / Planner 的结构化输出；工具风险等级 schema 明确当前只记录 ToolCall 和 ApprovalRequest，真实 Tool Gateway 执行留到 M5。

## 环境变量

复制根目录 `.env.example` 后按本机环境调整。当前本地开发变量包括：

```env
CLOUDHELM_ENV=development
CLOUDHELM_VERSION=0.3.0
CLOUDHELM_API_HOST=127.0.0.1
CLOUDHELM_API_PORT=18080
CLOUDHELM_DATABASE_URL=postgresql+psycopg://cloudhelm:cloudhelm_dev@127.0.0.1:15432/cloudhelm
CLOUDHELM_AGENT_PROVIDER=local_structured
VITE_CLOUDHELM_API_BASE_URL=http://127.0.0.1:18080
```

## informations 资料归档

`informations/` 只保存官方链接、检索日期、摘要、采用结论和少量必要摘录。禁止保存真实密钥、Token、Cookie、账号密码、真实服务器管理入口、许可证不明的大段代码或第三方文档全文。

资料入口：

- `informations/README.md`
- `informations/m1-foundation/official-references.md`
- `informations/m2-data-api/official-references.md`
- `informations/m3-control-console/official-references.md`
- `informations/m4-agent-orchestration/official-references.md`

## 当前未实现能力

M4 不实现 Coder / Tester / Reviewer / Security / Release / Deploy / SRE Agent 的真实执行，不执行 Tool Gateway 工具、Git PR、远端部署、监控告警或完整桌面端壳。上述能力将在 M5 及后续里程碑按 `PROJECT_PLAN.md` 和 `docs/14-roadmap/03-implementation-milestone-flow.md` 逐步实现。
