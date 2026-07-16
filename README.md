# 云舵 CloudHelm

CloudHelm 是面向毕业设计演示的多 Agent DevOps 系统。本仓库已完成
**M1-M6**，并完成 M7-0/M7-1 与 M7-2A/B1/B2 已交付切片，包括
**Environment + RemoteTarget + machine-auth heartbeat**、数据底座、
RepositoryBinding PUT/GET，以及 ReleaseCandidate、第一道审批和 reconcile
WorkflowJob 原子创建。当前已实现系统在已审批
DevelopmentPlan 基础上，由 Scaffold、Coder、Tester、Reviewer、Security 经统一
Tool Gateway 真实修改受控 sample repo、运行 pytest 与安全扫描、创建本地
branch/commit，并持久化 Artifact 和 `provider=local` 的 PR record。

> 当前版本：`0.5.1`
> 当前范围：控制台可创建 Project/Task，完成 Requirement/Design/Plan 审批，
> 再逐步推进本地开发闭环并展示真实 diff、测试、review、安全结果和 PR
> record；Platform API 还可登记 staging/demo Environment、受控 RemoteTarget
> 与 RepositoryBinding，Remote Agent 可通过 HMAC 上报心跳；Candidate POST
> 严格接受 `{}` 并原子创建第一道 L2 Approval 和无外部副作用的 reconcile
> WorkflowJob，GET 执行 active-first 查询。durable worker、真实 Gitea CI、
> 远端部署和监控仍未交付。

正式产品目标已经调整为：

```text
Windows/Linux CloudHelm Desktop
  -> HTTPS / REST / SSE
  -> 常在线 Linux CloudHelm Ops Hub
  -> Remote Agent
  -> 独立业务项目
```

- Desktop 使用 Tauri + React，Windows 必须交付 NSIS setup `.exe` 和
  `CloudHelm.exe`，Linux 必须交付 AppImage 与 `.deb`。
- Desktop 最终用户安装不依赖 Docker、PostgreSQL、Redis 或 Python；本地
  SQLite 只保存 server profile、UI 设置、草稿、缓存和事件 sequence，凭据进入
  OS credential store。
- Ops Hub 常驻 Linux，承载 Platform API、Orchestrator、Agent Runtime、Tool
  Gateway、Workflow Engine、Deployment Controller、PostgreSQL 和 Redis。
- Ops Hub installation 每套中心设施执行一次；每台受管 Linux 目标另行执行只含
  Docker/Compose、Remote Agent、采集器和 machine credential 的 bootstrap。
- 多个用户通过 user/device/session、system/project/environment scoped RBAC 和
  职责分离访问同一 Ops Hub；Desktop 只做体验门禁，API 每次重新鉴权。
- Desktop 首次登记和 Local Runtime 使用独立短期 Ed25519 device challenge；
  Local Runtime 只取得短期 device-bound token。EventLog 区分 actor 与 subject，
  Desktop cursor 按 Ops Hub/user/stream/scope 分区。
- Agent 生成的业务项目必须可独立构建、测试、部署和运行；删除
  `cloudhelm.project.yaml` 与 `cloudhelm.env.schema.json` 后仍不依赖 CloudHelm
  SDK、平台数据库或控制台。

上述 Desktop、用户/RBAC、Ops Hub 安装 profile、事件离线同步和通用项目
renderer 当前均为规划，不能作为已实现能力展示。

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
  platform-api/           # FastAPI 平台 API、M6 工作流与 M7-2B2 Candidate/Approval 入口
  agent-runtime/          # 八类普通 Agent、稳定输出协议和 Provider 工具循环
  orchestrator/           # M4/M6 显式状态机与编排边界
  tool-gateway/           # 本地 Repo/Test/Security/Git 工具、策略和审计
  remote-agent/           # M7-1 runtime 端点、credential file 与签名 heartbeat
  local-runtime/          # 规划：随 Desktop 分发的本机 workspace/Git/test sidecar
  workflow-engine/        # 规划：Ops Hub durable job、dispatcher、worker 与恢复
  deployment-controller/  # 规划：通用项目契约渲染与 Remote Agent 部署
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

以下 PostgreSQL/Redis 命令只用于 **CloudHelm 仓库贡献者开发与集成测试**，
不是最终 Desktop 用户的安装前置条件。Windows 开发机统一使用 Ubuntu 24.04
WSL2 内的原生 Docker Engine/Compose，不依赖 Docker Desktop。先保持 WSL 运行
并启动依赖：

1. 先按
   [`docs/12-deployment/05-ops-hub-installation.md`](docs/12-deployment/05-ops-hub-installation.md)
   执行 WSL/Docker 预检和可重复执行的单 keepalive 启动。
2. 再执行：

```powershell
wsl -d Ubuntu-24.04 -u cloudhelm -- bash -lc @"
cd '/mnt/d/graduation project'
docker compose -f infra/docker-compose.dev.yml \
  --profile optional up -d postgres redis
docker compose -f infra/docker-compose.dev.yml \
  --profile optional ps
"@
```

当前开发机发行版数据位于 `D:\WSL\Ubuntu-24.04`。该位置仅是本地环境记录；
完整 WSL/Ops Hub 开发说明见
`docs/12-deployment/05-ops-hub-installation.md`。

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

M7 当前 Platform API 还提供：

```text
POST/GET /api/projects/{project_id}/environments
GET      /api/environments/{environment_id}
POST/GET /api/environments/{environment_id}/remote-targets
POST     /api/remote-agents/heartbeat
PUT/GET  /api/projects/{project_id}/repository-binding
POST/GET /api/tasks/{task_id}/release-candidate
```

RemoteTarget 只接受服务端 profile key；heartbeat 使用六个必填 HMAC header、
PostgreSQL replay nonce 和 online/offline/recovery EventLog。完整契约与错误码见
`docs/08-api/07-environment-deployment-api.md`。

RepositoryBinding 同样只接受服务端 RepositoryProfile key；GET 只读取数据库
物化结果，响应和事件不返回 clone URL、credential ref 或 credential 内容。

Candidate POST 只接受严格 `{}`；服务端绑定最新版 open PullRequestRecord、
完整 commit 与 Binding snapshot/hash，首次创建返回 `201`，同一业务身份幂等
命中返回 `200`。Candidate、第一道 L2 Approval、`release_candidate_reconcile`
WorkflowJob 和事件在同一 PostgreSQL 事务中创建。approve/reject 会重新校验
PR、Binding、request hash、有效期和实现 AgentRun 自批门禁。M7-2B2 只持久化
pending job，不发布 ref、不触发 CI；dispatcher/worker 属于 M7-2C。

## Remote Agent M7-1

```powershell
cd modules/remote-agent
uv sync --frozen
uv run pytest -q
uv run cloudhelm-remote-agent serve --host 127.0.0.1 --port 9443
uv run cloudhelm-remote-heartbeat
```

Remote Agent 的 Platform API origin 强制 HTTPS，target id 必须为 UUID，machine
secret 只从权限受控 credential file 读取。当前只提供 health/version/capability
和 outbound heartbeat；Compose、部署、日志、diagnostics、restart、rollback 和
终端仍属于后续 M7/M8。

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

当前 `apps/control-console` 仍是 Vite + React Web 工程：没有 `src-tauri`、安装
程序、运行时 server profile、Desktop SQLite、OS credential store、登录或
effective permission UI。以下命令只验证现有 Web 控制台；Tauri 与跨平台安装
产物进入 M9/M10。

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

M4/M6 的 `run-next` 是当前真实实现。目标 Ops Hub 中，已经持久化且不需要新审批
的远端 CI、部署、监控和 Agent 步骤应由服务端 Workflow Engine 继续推进；
`run-next` 只保留为开发调试、答辩逐步演示或人工恢复入口。

## 共享契约

- `packages/shared-contracts/openapi/cloudhelm.openapi.yaml`
- `packages/shared-contracts/openapi/cloudhelm-remote-agent.openapi.yaml`
- `packages/shared-contracts/schemas/agents/*.schema.json`
- `packages/shared-contracts/schemas/artifacts/*.schema.json`
- `packages/shared-contracts/schemas/events/task-event.schema.json`
- `packages/shared-contracts/schemas/remote/*.schema.json`
- `packages/shared-contracts/schemas/tools/*.schema.json`

FastAPI OpenAPI 与共享 YAML 反序列化后必须精确一致。Agent 输出 schema
覆盖八类普通 Agent；Artifact schema 约束安全引用和本地 PR record；工具 schema
描述 ToolCallRequest/Result 以及 Repo/Scaffold/Test/Security/Git 契约；remote
schema 约束 Environment、RemoteTarget 与 heartbeat request/ack。当前事件 schema
还精确约束 `WorkflowJobQueued`、`ReleaseCandidateApprovalRequested`、
`ReleaseCandidateApproved` 和 `ReleaseCandidateRejected` 的 B2 payload。

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
CLOUDHELM_REMOTE_TARGET_PROFILES={}
CLOUDHELM_REMOTE_AGENT_CREDENTIALS={}
CLOUDHELM_REMOTE_AGENT_TIMESTAMP_TOLERANCE_SECONDS=300
CLOUDHELM_REMOTE_AGENT_NONCE_TTL_SECONDS=900
CLOUDHELM_REMOTE_AGENT_OFFLINE_TIMEOUT_SECONDS=60
CLOUDHELM_REMOTE_AGENT_HEARTBEAT_EVENT_INTERVAL_SECONDS=300
CLOUDHELM_REMOTE_AGENT_NEXT_HEARTBEAT_SECONDS=20
CLOUDHELM_REMOTE_AGENT_HEARTBEAT_MAX_BODY_BYTES=16384
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
- `informations/m7-ci-remote-deploy/official-references.md`
- `informations/m7-ci-remote-deploy/reference-projects.md`
- `informations/m7-desktop-ops-architecture/official-references.md`
- `informations/m7-desktop-ops-architecture/identity-access-references.md`

## 当前未实现能力

当前尚未实现 durable Workflow Engine、CIRun/Deployment/ServiceInstance、
Release / Deploy / SRE Agent、真实远端 PR、Gitea CI、远端 Compose deployment、
监控告警或完整桌面端壳。也尚未实现用户登录/RBAC、Local Runtime、正式 Ops Hub
安装/备份、project/env adapter schema、通用 renderer、Desktop 离线 sequence
同步和 Windows/Linux 安装包。Sandbox 当前使用本地受控目录 + subprocess 超时，
没有 Docker 的 CPU、内存、PID 和网络隔离；M7 在接入远端 staging/demo 前继续
收敛 Docker/远端执行边界。

当前失败恢复只覆盖能够进入应用异常处理的错误和已有幂等证据。Platform API
进程在终态写入前被强制终止时，`pending/running` AgentRun/ToolCall 尚无
lease、heartbeat 或 stale reclaim，需依据数据库与工作区证据人工核验；M6
不宣称 hard crash 后自动恢复。M7-2B2 的 WorkflowJob 目前也只有 PostgreSQL
持久化和事件，没有 dispatcher、claim、lease、heartbeat 或 stale reclaim；
这些由 M7-2C 实现。M7-1 的离线状态暂由 RemoteTarget list 或下一次 heartbeat
收敛，项目/环境事件查询与实时 SSE 尚未实现。
