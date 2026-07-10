# 云舵 CloudHelm

CloudHelm 是面向毕业设计演示的多 Agent DevOps 系统。本仓库当前已完成 **M5：Tool Gateway 与本地工具层**，在 M4 结构化编排基础上接入本地工具统一入口、风险等级、审批拦截、调用限流、审计记录和控制台 ToolCall 展示。

> 当前版本：`0.4.1`
> 当前范围：控制台可通过真实 Platform API 创建 Project/Task，启动 M4 编排，并展示 M5 ToolCall 的参数摘要、风险等级、状态、输出摘要、错误码和审批关联。M5 只执行本地受控 Repo/Sandbox/Git 工具，不执行远端 SSH、远端部署、CI/CD 或监控告警。

`0.4.1` 补齐了 M1-M5 审计发现的状态一致性问题：设计/计划返工会级联失效旧产物与审批，计划审批会同步更新 DevelopmentPlan，Tool Gateway 只接受 running AgentRun，Git commit 拒绝目录级 pathspec，控制台事件监听与共享 Event schema 已覆盖 M2-M5 实际事件。

## 目录结构

```text
apps/
  control-console/        # React + TypeScript 控制台，M4 展示 Agent 编排闭环
modules/
  platform-api/           # FastAPI 平台 API，M5 提供数据、事件、编排和工具入口
  agent-runtime/          # Requirement / Architect / Planner 结构化输出运行时
  orchestrator/           # M4 显式状态机与编排边界
  tool-gateway/           # M5 工具注册、策略、审计和本地工具实现
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

M4 默认使用 `CLOUDHELM_AGENT_PROVIDER=local_structured`，该 provider 基于真实 Task / Requirement / Design 输入生成结构化草案，并通过 Pydantic 校验。若切换到 `openai_compatible`，必须提供 `CLOUDHELM_LLM_MODEL`、`CLOUDHELM_LLM_API_BASE` 和 `CLOUDHELM_LLM_API_KEY`；默认使用 Responses API，并支持 `CLOUDHELM_LLM_REASONING_EFFORT=max`。用户指定 `gpt-5.6-sol` 时模型字符串会原样透传给兼容端点；旧服务可将 `CLOUDHELM_LLM_API_MODE` 改为 `chat_completions`。缺配置、HTTP 失败或响应结构无效都会写入失败 AgentRun 和 EventLog。

## Tool Gateway

```powershell
cd modules/tool-gateway
uv run pytest
```

M5 默认工具包括 `requirement.normalize`、`design.render_markdown`、`repo.*`、`sandbox.*`、`git.*` 和 `approval.request_remote_action`。其中 `approval.request_remote_action` 只用于验证 L3 审批拦截，不执行远端动作。Tool Gateway 默认按任务或 AgentRun 执行 60 秒 60 次的单实例滑动窗口限流，参数可通过环境变量调整。

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
npm.cmd test
npm.cmd run build
```

## 控制台 M5 主流程

- Project Sidebar：`GET /api/projects`、`POST /api/projects`。
- Task Board：`GET /api/tasks?project_id=...`、`POST /api/tasks`、`pause`、`resume`、`cancel`。
- M4 编排：`POST /api/tasks/{task_id}/start`、`POST /api/tasks/{task_id}/run-next`。
- Task Detail：读取 Requirement、Technical Design、DevelopmentPlan、AgentRun、ToolCall、Approval、Orchestration State 和 Timeline。
- ToolCall 列表：展示真实 `tool_calls` 的工具名、参数摘要、风险等级、状态、输出摘要、错误码、幂等键和审批 ID，不展示完整敏感参数。
- SSE：优先连接 `GET /api/tasks/{task_id}/events/stream`；当前仍基于 `event_logs` 回放已有事件并追加 heartbeat，控制台在任务操作后重新读取 Timeline。

## 共享契约

- `packages/shared-contracts/openapi/cloudhelm.openapi.yaml`
- `packages/shared-contracts/schemas/agents/*.schema.json`
- `packages/shared-contracts/schemas/events/task-event.schema.json`
- `packages/shared-contracts/schemas/tools/*.schema.json`

OpenAPI 覆盖当前已实现接口；Agent 输出 schema 约束 Requirement / Architect / Planner 的结构化输出；工具 schema 描述 M5 ToolCallRequest、ToolCallResult、Repo/Sandbox/Git/Requirement/Design Tool 契约和风险等级。

## 环境变量

复制根目录 `.env.example` 后按本机环境调整。当前本地开发变量包括：

```env
CLOUDHELM_ENV=development
CLOUDHELM_VERSION=0.4.1
CLOUDHELM_API_HOST=127.0.0.1
CLOUDHELM_API_PORT=18080
CLOUDHELM_TOOL_RATE_LIMIT_CALLS=60
CLOUDHELM_TOOL_RATE_LIMIT_WINDOW_SECONDS=60
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
- `informations/m5-tool-gateway/official-references.md`

## 当前未实现能力

M5 不实现 Coder / Tester / Reviewer / Security / Release / Deploy / SRE Agent 的完整自动开发闭环，不创建远端 PR，不执行远端部署、监控告警或完整桌面端壳。Sandbox Tool 当前使用本地受控目录 + subprocess 超时，Docker 隔离留到 M6 前置增强。
