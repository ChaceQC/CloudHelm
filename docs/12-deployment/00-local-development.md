# 仓库贡献者本地开发部署

> 来源：[设计书 16 章](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：定义部署拓扑、运行组件和演示/扩展路径。
## 验收关注点

- 本地 Docker Compose 能启动仓库开发所需依赖。
- 与远端联调时，Linux 目标能运行 Remote Agent 和 Docker Compose；监控采集链
  属于 M8。
- 控制台在 M7 展示远端服务状态、受限日志和部署版本；集中指标属于 M8。

本文件只描述 CloudHelm 源码贡献者的 Windows 开发环境。正式 Desktop 安装不
要求 Docker/PostgreSQL/Redis；正式控制面部署在常在线 Linux Ops Hub，见
[04-desktop-packaging-installation.md](04-desktop-packaging-installation.md) 和
[05-ops-hub-installation.md](05-ops-hub-installation.md)。

Windows PowerShell 运行本仓库命令前统一设置 UTF-8：

```powershell
$env:PYTHONIOENCODING='utf-8'
$OutputEncoding=[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new()
```

## M1 本地最小工程命令

M1 阶段未启动完整 Docker Compose，只验证平台 API、控制台和共享契约的最小
工程基线；该段保留用于追溯最初启动方式。

### Platform API

```powershell
cd modules/platform-api
uv run pytest
uv run uvicorn cloudhelm_platform_api.main:app --host 127.0.0.1 --port 18080
Invoke-RestMethod http://127.0.0.1:18080/health
```

### Control Console

```powershell
cd apps/control-console
npm.cmd install
$env:VITE_CLOUDHELM_API_BASE_URL='http://127.0.0.1:18080'
npm.cmd run dev
npm.cmd run build
```

Windows PowerShell 如拦截 `npm.ps1`，使用 `npm.cmd`。M1 当时只验证
React/TypeScript 骨架；当前 M6 仍以浏览器控制台完成真实闭环，Tauri、
Local Runtime 与 Desktop SQLite 进入 M9，Windows/Linux 真实安装包与干净环境
验收进入 M10。

## M2 本地数据库与 API 命令

M2 开始需要本地 PostgreSQL。开发环境使用 `infra/docker-compose.dev.yml`，
示例凭据只用于本地开发，不代表真实服务器凭据。Windows 开发机先按
[Ops Hub 常驻安装与 Remote Target Bootstrap](05-ops-hub-installation.md)
完成 WSL/Docker 预检和单 keepalive，再执行：

```powershell
wsl -d Ubuntu-24.04 -u cloudhelm -- bash -lc @"
cd '/mnt/d/graduation project'
docker compose -f infra/docker-compose.dev.yml up -d postgres
docker compose -f infra/docker-compose.dev.yml ps
"@
cd modules/platform-api
$env:CLOUDHELM_DATABASE_URL='postgresql+psycopg://cloudhelm:cloudhelm_dev@127.0.0.1:15432/cloudhelm'
uv run alembic upgrade head
uv run pytest
uv run uvicorn cloudhelm_platform_api.main:app --host 127.0.0.1 --port 18080
```

### Platform API 测试数据库隔离

`uv run pytest` 不会重建上面 `CLOUDHELM_DATABASE_URL` 指向的 `cloudhelm`
开发库。默认夹具只借用同一 PostgreSQL 实例，以 `cloudhelm_test` 为基名创建
会话级随机数据库：

```text
cloudhelm_test_<pid>_<uuid>
```

测试会在该临时库执行 Alembic，并在 pytest 会话结束后删除。并行测试会话使用
不同数据库；运行测试的 PostgreSQL 用户需要具备创建/删除测试数据库的权限。

如需复用明确的专用测试库，必须同时提供独立 test 数据库名和破坏性重建确认：

```powershell
$env:CLOUDHELM_TEST_DATABASE_URL='postgresql+psycopg://cloudhelm:cloudhelm_dev@127.0.0.1:15432/cloudhelm_test'
$env:CLOUDHELM_TEST_ALLOW_SCHEMA_RESET='true'
uv run pytest -q
Remove-Item Env:CLOUDHELM_TEST_DATABASE_URL
Remove-Item Env:CLOUDHELM_TEST_ALLOW_SCHEMA_RESET
```

显式模式会重建目标测试库的 `public` schema；数据库名必须包含独立 `test`
段，不得指向 `cloudhelm` 开发库。缺少确认时测试在迁移前终止。

M2 当时的 Redis 服务仅通过 Compose profile 预留；M7-2C 起由 Workflow
Engine 作为 Celery broker 使用：

```powershell
wsl -d Ubuntu-24.04 -u cloudhelm -- bash -lc @"
cd '/mnt/d/graduation project'
docker compose -f infra/docker-compose.dev.yml \
  --profile optional up -d redis
"@
```

Redis 只负责消息投递，不保存 WorkflowJob 业务事实。

## M7-2C Workflow Engine WSL 开发与故障测试

Celery worker 统一在 Ubuntu 24.04 WSL2 中运行。WSL 用户环境已使用官方安装器
安装 `uv 0.11.29` 到 `/home/cloudhelm/.local/bin`。Windows 与 Linux wheel
不同，不共享仓库内 `.venv`；WSL 固定使用：

```text
/home/cloudhelm/.cache/cloudhelm/workflow-engine-venv
```

首次同步：

```powershell
wsl -d Ubuntu-24.04 -u cloudhelm `
  --cd "/mnt/d/graduation project/modules/workflow-engine" -- `
  env UV_PROJECT_ENVIRONMENT=/home/cloudhelm/.cache/cloudhelm/workflow-engine-venv `
  UV_LINK_MODE=copy `
  /home/cloudhelm/.local/bin/uv sync --frozen --all-groups
```

启动三个独立进程：

```bash
uv run cloudhelm-workflow-engine dispatcher

uv run celery \
  -A cloudhelm_workflow_engine.celery_app:celery_app \
  worker \
  --queues cloudhelm.workflow \
  --pool prefork \
  --concurrency 1 \
  --hostname 'cloudhelm-workflow@%h' \
  --loglevel INFO

uv run cloudhelm-workflow-engine reclaimer
```

执行普通与真实 Redis restart 测试：

```powershell
wsl -d Ubuntu-24.04 -u cloudhelm `
  --cd "/mnt/d/graduation project/modules/workflow-engine" -- `
  env UV_PROJECT_ENVIRONMENT=/home/cloudhelm/.cache/cloudhelm/workflow-engine-venv `
  /home/cloudhelm/.local/bin/uv run pytest -q -m "not workflow_integration"

wsl -d Ubuntu-24.04 -u cloudhelm `
  --cd "/mnt/d/graduation project/modules/workflow-engine" -- `
  env UV_PROJECT_ENVIRONMENT=/home/cloudhelm/.cache/cloudhelm/workflow-engine-venv `
  CLOUDHELM_RUN_WORKFLOW_INTEGRATION=1 `
  /home/cloudhelm/.local/bin/uv run pytest -q -m workflow_integration
```

restart 用例使用临时 `cloudhelm-redis-workflow-test` container 和独立端口
`127.0.0.1:16380`、DB 15；fixture 强制校验该隔离目标并自动创建/删除。集成组
同时验证 Redis stop/start 补投和真实 prefork 进程组 hard-crash 后 `none` job
lease 回排；共享 `cloudhelm-postgres-dev`/`cloudhelm-redis-dev` 保持运行。正式 Ops Hub
installation/bootstrap 仍是独立的后续验收，不把本节开发基线写成正式安装。

## M6 sample repo 与本地工作区

M6 继续把 PostgreSQL 作为 Platform API 持久化依赖，但代码、测试、安全扫描
和 Git 副作用发生在 Task 独立本地 workspace。源 fixture 可先独立验证：

```powershell
cd examples/sample-repo-python
uv lock --check
uv run pytest -q
```

Platform API 默认从仓库根目录派生下列路径，也可通过环境变量覆盖：

```powershell
$env:CLOUDHELM_M6_SAMPLE_REPO_ROOT='D:\path\to\CloudHelm\examples\sample-repo-python'
$env:CLOUDHELM_M6_RECIPE_ROOT='D:\path\to\CloudHelm\examples\sample-repo-python\demo-issues'
$env:CLOUDHELM_M6_WORKSPACE_ROOT='D:\path\to\CloudHelm\output\m6-workspaces'
$env:CLOUDHELM_ARTIFACT_ROOT='D:\path\to\CloudHelm\output\artifacts'
$env:CLOUDHELM_ARTIFACT_PREVIEW_BYTES='65536'
$env:CLOUDHELM_M6_BRANCH_PREFIX='codex'
```

这些根目录只由服务端读取；控制台、HTTP 请求和模型均不能指定任意路径。输出
目录被 `.gitignore` 排除，源 fixture 不包含嵌套 `.git`。Scaffold 步骤负责复制
fixture、初始化独立 `main` baseline 和 Task branch。

M6 测试与安全命令使用 Tool Gateway 受控 subprocess：命令数组、正向 profile、
环境变量白名单、超时、输出上限和进程清理均由工具层执行。该方案不具备 Docker
CPU、内存、PID 和网络隔离；M7 远端部署前再评估一次性 Docker sandbox。

当前幂等与恢复覆盖能够进入应用错误处理的 Provider、CLI、文件系统和数据库
异常。Platform API 进程在终态写入前被强制终止时，active AgentRun/ToolCall
尚无 lease/heartbeat/stale reclaim；M6 不把 hard crash 自动恢复列为已交付
能力，现阶段需依据数据库和工作区证据人工核验。

## 设计书摘录

### 16.1 本地开发部署

历史目标曾计划把完整平台依赖放在本机 Compose。当前正式产品拓扑已调整为
Desktop + Linux Ops Hub；以下清单只作为 contributor/all-in-one demo 的参考，
不得解释为最终用户安装方式：

```text
docker-compose.dev.yml
  - postgres
  - redis
  - platform-api
  - orchestrator-worker
  - tool-gateway
  - repo-tool
  - git-tool
  - sandbox-tool
  - deploy-tool
  - remote-control-tool
  - gitea
  - prometheus
  - grafana
  - loki
  - alertmanager
  - langfuse
```
