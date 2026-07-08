# 云舵 CloudHelm

CloudHelm 是面向毕业设计演示的多 Agent DevOps 系统。本仓库当前已完成 **M3：控制台任务主流程**，在 M2 真实数据库 API 与事件底座之上接入 Project Sidebar、Task Board、Task Detail、Timeline、ToolCall 和 Approval 基础交互。

> 当前版本：`0.2.1`
> 当前范围：控制台可通过真实 Platform API 创建 Project/Task，执行任务暂停、恢复、取消，查看真实 Requirement、Technical Design、AgentRun、ToolCall、Approval 和 Event Timeline 数据或空状态。M3 不实现 Agent 自动执行、Tool Gateway 真实工具执行、Git PR、远端部署或监控业务逻辑。

## 目录结构

```text
apps/
  control-console/        # React + TypeScript 控制台任务主流程，后续接入 Tauri
modules/
  platform-api/           # FastAPI 平台 API，M2 提供真实数据库 API
packages/
  shared-contracts/       # OpenAPI、事件 schema、工具风险等级 schema
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

## 控制台 M3 主流程

M3 控制台入口：

- Project Sidebar：`GET /api/projects`、`POST /api/projects`。
- Task Board：`GET /api/tasks?project_id=...`、`POST /api/tasks`、`pause`、`resume`、`cancel`。
- Task Detail：读取 Requirement、Technical Design、AgentRun、ToolCall、Approval 和 Timeline。
- SSE：优先连接 `GET /api/tasks/{task_id}/events/stream`；M2 SSE 只回放已有事件并追加 heartbeat，因此 M3 同时使用刷新/重连式 Timeline 读取。

M3 不展示静态假任务、假 AgentRun、假 ToolCall 或假审批。

## 共享契约

M3 继续复用 M2 共享契约：

- `packages/shared-contracts/openapi/cloudhelm.openapi.yaml`
- `packages/shared-contracts/schemas/events/task-event.schema.json`
- `packages/shared-contracts/schemas/tools/tool-risk-level.schema.json`

OpenAPI 覆盖当前已实现接口；事件 schema 包含真实事件类型；工具风险等级 schema 明确当前只记录 ToolCall 和 ApprovalRequest，真实 Tool Gateway 执行留到后续阶段。

## 环境变量

复制根目录 `.env.example` 后按本机环境调整。当前本地开发变量包括：

```env
CLOUDHELM_ENV=development
CLOUDHELM_VERSION=0.2.1
CLOUDHELM_API_HOST=127.0.0.1
CLOUDHELM_API_PORT=18080
CLOUDHELM_DATABASE_URL=postgresql+psycopg://cloudhelm:cloudhelm_dev@127.0.0.1:15432/cloudhelm
VITE_CLOUDHELM_API_BASE_URL=http://127.0.0.1:18080
```

## informations 资料归档

`informations/` 只保存官方链接、检索日期、摘要、采用结论和少量必要摘录。禁止保存真实密钥、Token、Cookie、账号密码、真实服务器管理入口、许可证不明的大段代码或第三方文档全文。

资料入口：

- `informations/README.md`
- `informations/m1-foundation/official-references.md`
- `informations/m2-data-api/official-references.md`
- `informations/m3-control-console/official-references.md`

## 当前未实现能力

M3 不实现 Agent 自动生成、LangGraph 编排、Tool Gateway 真实工具执行、Git PR、远端部署、监控告警或完整桌面端壳。上述能力将在 M4 及后续里程碑按 `PROJECT_PLAN.md` 和 `docs/14-roadmap/03-implementation-milestone-flow.md` 逐步实现。
