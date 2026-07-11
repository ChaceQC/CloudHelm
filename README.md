# 云舵 CloudHelm

CloudHelm 是面向毕业设计演示的多 Agent DevOps 系统。本仓库当前已完成 **M5：Tool Gateway 与本地工具层**，在 M4 结构化编排基础上接入本地工具统一入口、风险等级、审批拦截、调用限流、审计记录和控制台 ToolCall 展示。

> 当前版本：`0.4.3`
> 当前范围：控制台可通过真实 Platform API 创建 Project/Task，启动 M4 编排，并展示 M5 ToolCall 的脱敏参数摘要、审计 hash、风险等级、状态、输出摘要、错误码和审批关联。M5 只执行平台允许目录内的本地 Repo/Sandbox/Git 工具，不执行远端 SSH、远端部署、CI/CD 或监控告警。

`0.4.3` 完成 Task 级 Agent conversation 与真实 Prompt Cache 纠偏：Requirement、Architect、Planner 跨独立 API 请求复用同一 root conversation，完整保存并回放 message、encrypted reasoning、工具项和审批上下文；只有显式 spawn 才创建 child conversation。AgentRun 记录逐请求供应商 usage，控制台按 Gemini 浅色主题展示 turn、input/cache/output token、请求次数、response ID 和 cache key。

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

M4 默认使用 `CLOUDHELM_AGENT_PROVIDER=local_structured`，该 provider 基于真实 Task / Requirement / Design 输入生成结构化草案，并通过 Pydantic 校验。若切换到 `openai_compatible`，必须提供 `CLOUDHELM_LLM_MODEL`、`CLOUDHELM_LLM_API_BASE` 和 `CLOUDHELM_LLM_API_KEY`；默认使用 HTTP SSE Responses API。当前真实流程将兼容端点提供的 `gpt-5.6-sol` 模型字符串与 `CLOUDHELM_LLM_REASONING_EFFORT=xhigh` 原样透传，同时发送 `codex_cli_rs/...` User-Agent、稳定 thread headers 和完整 Task conversation 历史。瞬时 HTTP/网络错误和无效结构化响应默认最多尝试 3 次；耗尽后写入失败 AgentRun，并把可恢复任务暂停在原业务阶段。

## Tool Gateway

```powershell
cd modules/tool-gateway
uv run pytest
```

M5 默认工具包括 `requirement.normalize`、`design.render_markdown`、`repo.*`、`sandbox.*`、`git.*` 和 `approval.request_remote_action`。其中 `approval.request_remote_action` 只用于验证 L3 审批拦截，不执行远端动作。文件、命令和 Git 工具只能访问 `CLOUDHELM_TOOL_WORKSPACE_ROOTS` 配置的目录；空数组默认拒绝。Tool Gateway 默认按任务或 AgentRun 执行 60 秒 60 次的单实例滑动窗口限流。

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
- ToolCall 列表：展示真实 `tool_calls` 的工具名、脱敏参数摘要、审计 JSON、风险等级、状态、输出摘要、错误码、幂等键和审批 ID，不展示原始文件正文或凭据。
- SSE：连接 `GET /api/tasks/{task_id}/events/stream`；端点每次回放已有事件后关闭，控制台按固定退避自动重连、按 event id 去重，并在新事件出现时同步刷新详情和左侧 Task Board。

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
CLOUDHELM_VERSION=0.4.3
CLOUDHELM_API_HOST=127.0.0.1
CLOUDHELM_API_PORT=18080
CLOUDHELM_TOOL_RATE_LIMIT_CALLS=60
CLOUDHELM_TOOL_RATE_LIMIT_WINDOW_SECONDS=60
CLOUDHELM_TOOL_WORKSPACE_ROOTS=[]
CLOUDHELM_DATABASE_URL=postgresql+psycopg://cloudhelm:cloudhelm_dev@127.0.0.1:15432/cloudhelm
CLOUDHELM_AGENT_PROVIDER=local_structured
CLOUDHELM_LLM_REASONING_EFFORT=xhigh
CLOUDHELM_LLM_REASONING_SUMMARY=auto
CLOUDHELM_LLM_REASONING_CONTEXT=all_turns
CLOUDHELM_LLM_EXPLICIT_CACHE_BREAKPOINT=false
CLOUDHELM_LLM_USER_AGENT=codex_cli_rs/0.0.0 (CloudHelm)
CLOUDHELM_LLM_MAX_ATTEMPTS=3
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
- `informations/m4-agent-context/codex-responses-context.md`
- `informations/m5-tool-gateway/official-references.md`

## 当前未实现能力

M5 不实现 Coder / Tester / Reviewer / Security / Release / Deploy / SRE Agent 的完整自动开发闭环，不创建远端 PR，不执行远端部署、监控告警或完整桌面端壳。Sandbox Tool 当前使用本地受控目录 + subprocess 超时，Docker 隔离留到 M6 前置增强。
