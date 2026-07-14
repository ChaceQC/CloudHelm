# 云舵 CloudHelm

CloudHelm 是面向毕业设计演示的多 Agent DevOps 系统。本仓库当前已完成
**M6：本地代码实现、测试与等价 PR 闭环**。系统在已审批 DevelopmentPlan
基础上，由 Scaffold、Coder、Tester、Reviewer、Security 经统一 Tool Gateway
真实修改受控 sample repo、运行 pytest 与安全扫描、创建本地 branch/commit，
并持久化 Artifact 和 `provider=local` 的 PR record。

> 当前版本：`0.5.1`
> 当前范围：控制台可创建 Project/Task，完成 Requirement/Design/Plan 审批，
> 再逐步推进本地开发闭环并展示真实 diff、测试、review、安全结果和 PR
> record。M6 不执行远端 push、真实 GitHub/Gitea PR、CI/CD、SSH、部署或监控。

普通 Requirement、Architect、Planner、Scaffold、Coder、Tester、Reviewer、
Security 角色跨独立 API 请求复用同一 Task root conversation，完整保存并回放
message、encrypted reasoning、工具 call/output 和审批上下文；只有显式 spawn
内部服务才创建 child conversation。M1-M6 已实现默认深度 1、active child 上限
6、父 AgentRun/conversation 绑定、父子角色工具权限交集、最终摘要门禁和 Task
取消级联。read-heavy 并行、共享写状态串行或隔离是项目开发协作规则；当前产品
尚无真实 child AgentRun/provider 调度、wait-all、通用 steer/queue 或独立
thread 管理 UI。一次 Agent 工具循环可包含多次 provider 请求和工具调用，但只
提交一个逻辑 turn。

## 目录结构

```text
apps/
  control-console/        # React + TypeScript 控制台，展示 M6 证据和本地 PR record
modules/
  platform-api/           # FastAPI 平台 API、M6 单步工作流、Artifact/PR 持久化
  agent-runtime/          # 八类普通 Agent、稳定输出协议和 Provider 工具循环
  orchestrator/           # M4/M6 显式状态机与编排边界
  tool-gateway/           # 本地 Repo/Test/Security/Git 工具、策略和审计
packages/
  shared-contracts/       # OpenAPI、事件 schema、工具风险等级 schema、Agent 输出 schema
infra/                    # 本地 PostgreSQL Docker Compose 与后续部署配置
examples/                 # M6 sample repo、演示 issue 和后续演示脚本
tests/                    # 后续跨模块集成测试和 E2E 测试
informations/             # 官方资料、命令来源和阶段性调研摘要
docs/                     # 设计文档与里程碑流程
```

## 后端：platform-api

PowerShell 先统一 UTF-8：

```powershell
$env:PYTHONIOENCODING='utf-8'
$OutputEncoding=[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new()
```

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

pytest 默认不会清空 `CLOUDHELM_DATABASE_URL` 指向的 `cloudhelm` 开发库，而是
在同一 PostgreSQL 实例创建会话级随机数据库
`cloudhelm_test_<pid>_<uuid>`，迁移、测试后再删除。运行测试的数据库用户需有
创建/删除测试数据库权限。只有复用明确的专用 test 数据库时才设置
`CLOUDHELM_TEST_DATABASE_URL`，并同时设置
`CLOUDHELM_TEST_ALLOW_SCHEMA_RESET=true`；显式模式会重建该测试库的
`public` schema，数据库名必须包含独立 `test` 段。

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

默认使用 `CLOUDHELM_AGENT_PROVIDER=local_structured`。该 provider 当前只支持
受控 auth/profile demo issue 与 CloudHelm 自身 M4 编排核验 recipe，并基于真实
Task、已审批需求/设计/计划、execution recipe 和工具结果生成严格结构化输出；
其他领域在 Architect 阶段返回稳定 `409 unsupported_local_recipe`，不会生成
固定伪设计或固定实现计划。
切换 `openai_compatible` 时必须提供模型、API base 和临时注入的 Key；默认使用
HTTP SSE Responses API、`reasoning.effort=xhigh`、Codex User-Agent、稳定
thread headers、完整 Task conversation 历史和供应商 usage。瞬时 HTTP/网络
错误和无效结构化响应执行有界重试；耗尽后记录失败 AgentRun 并暂停可恢复 Task。

## Tool Gateway

```powershell
cd modules/tool-gateway
uv run pytest
```

默认工具包括 `requirement.normalize`、`design.render_markdown`、`scaffold.*`、
`repo.*`、`sandbox.*`、`test.*`、`security.*`、`git.*` 和
`approval.request_remote_action`。文件、命令和 Git 工具只能访问服务端
allowlist；M6 sample fixture/workspace 会由固定配置加入有效根目录，HTTP 请求
不能传入任意本机根目录。Tool Gateway 默认按 Task 或 AgentRun 执行 60 秒 60 次
的单实例滑动窗口限流。

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

## 控制台 M6 主流程

- Project Sidebar：`GET /api/projects`、`POST /api/projects`。
- Task Board：`GET /api/tasks?project_id=...`、`POST /api/tasks`、`pause`、`resume`、`cancel`。
- M4 编排：`POST /api/tasks/{task_id}/start`、`POST /api/tasks/{task_id}/run-next`。
- M6 本地开发：读取 `GET /api/tasks/{task_id}/local-development`，再调用
  `start` / `run-next` 每次推进一个 Scaffold、Coder、Tester、Reviewer、
  Security 或 Git 收尾动作。
- Task Detail：读取 Requirement、Technical Design、DevelopmentPlan、AgentRun、ToolCall、Approval、Orchestration State 和 Timeline。
- ToolCall 列表：展示真实 `tool_calls` 的工具名、脱敏参数摘要、审计 JSON、风险等级、状态、输出摘要、错误码、幂等键和审批 ID，不展示原始文件正文或凭据。
- Evidence：从 Artifact API 展示 diff、JUnit/TestReport、ReviewReport、
  SecurityReport；从 PR record API 展示 base/head、commit、changed files、
  diff stat 和四类门禁 Artifact 引用。
- SSE：连接 `GET /api/tasks/{task_id}/events/stream`；端点每次回放已有事件后关闭，控制台按固定退避自动重连、按 event id 去重，并在新事件出现时同步刷新详情和左侧 Task Board。

## 共享契约

- `packages/shared-contracts/openapi/cloudhelm.openapi.yaml`
- `packages/shared-contracts/schemas/agents/*.schema.json`
- `packages/shared-contracts/schemas/artifacts/*.schema.json`
- `packages/shared-contracts/schemas/events/task-event.schema.json`
- `packages/shared-contracts/schemas/tools/*.schema.json`

FastAPI OpenAPI 与共享 YAML 反序列化后必须精确一致。Agent 输出 schema
覆盖八类普通 Agent；Artifact schema 约束安全引用和本地 PR record；工具 schema
描述 ToolCallRequest/Result 以及 Repo/Scaffold/Test/Security/Git 契约。

## M6 sample repo

`examples/sample-repo-python` 是只读源 fixture，提供真实 FastAPI `/health`、
`/metrics`、pytest、Dockerfile、Compose 和认证/个人资料 demo issue。可独立验证：

```powershell
cd examples/sample-repo-python
uv lock --check
uv run pytest -q
```

Platform API 的 Scaffold 步骤把 fixture 复制到 Task 独立 workspace 并初始化
baseline Git；Coder 不直接修改源 fixture。

## 环境变量

复制根目录 `.env.example` 后按本机环境调整。当前本地开发变量包括：

```env
CLOUDHELM_ENV=development
CLOUDHELM_VERSION=0.5.1
CLOUDHELM_API_HOST=127.0.0.1
CLOUDHELM_API_PORT=18080
CLOUDHELM_TOOL_RATE_LIMIT_CALLS=60
CLOUDHELM_TOOL_RATE_LIMIT_WINDOW_SECONDS=60
CLOUDHELM_TOOL_WORKSPACE_ROOTS=[]
CLOUDHELM_TOOL_MAX_TIMEOUT_SECONDS=300
CLOUDHELM_TOOL_MAX_OUTPUT_CHARS=50000
CLOUDHELM_M6_SAMPLE_REPO_ROOT=D:/path/to/CloudHelm/examples/sample-repo-python
CLOUDHELM_M6_RECIPE_ROOT=D:/path/to/CloudHelm/examples/sample-repo-python/demo-issues
CLOUDHELM_M6_WORKSPACE_ROOT=D:/path/to/CloudHelm/output/m6-workspaces
CLOUDHELM_ARTIFACT_ROOT=D:/path/to/CloudHelm/output/artifacts
CLOUDHELM_ARTIFACT_PREVIEW_BYTES=65536
CLOUDHELM_M6_BRANCH_PREFIX=codex
CLOUDHELM_DATABASE_URL=postgresql+psycopg://cloudhelm:cloudhelm_dev@127.0.0.1:15432/cloudhelm
# CLOUDHELM_TEST_DATABASE_URL=postgresql+psycopg://cloudhelm:cloudhelm_dev@127.0.0.1:15432/cloudhelm_test
CLOUDHELM_TEST_ALLOW_SCHEMA_RESET=false
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
- `informations/m6-code-test-pr/official-references.md`

## 当前未实现能力

M6 不实现 Release / Deploy / SRE Agent、真实远端 PR、CI/CD、SSH、远端部署、
监控告警或完整桌面端壳。Sandbox 当前使用本地受控目录 + subprocess 超时，
没有 Docker 的 CPU、内存、PID 和网络隔离；M7 在接入远端 staging/demo 前
继续收敛 Docker/远端执行边界。

当前失败恢复只覆盖能够进入应用异常处理的错误和已有幂等证据。Platform API
进程在终态写入前被强制终止时，`pending/running` AgentRun/ToolCall 尚无
lease、heartbeat 或 stale reclaim，需依据数据库与工作区证据人工核验；M6
不宣称 hard crash 后自动恢复。
