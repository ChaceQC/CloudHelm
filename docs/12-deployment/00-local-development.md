# 本地开发部署

> 来源：[设计书 16 章](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：定义部署拓扑、运行组件和演示/扩展路径。
## 验收关注点

- 本地 Docker Compose 能启动核心平台依赖。
- 远端 demo 主机能运行 Remote Agent、Docker Compose 和监控采集组件。
- 控制台能展示远端服务状态、日志、指标和部署版本。

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
React/TypeScript 骨架；当前 M6 仍以浏览器控制台完成真实闭环，完整 Tauri
桌面壳保留给后续演示阶段。

## M2 本地数据库与 API 命令

M2 开始需要本地 PostgreSQL。开发环境使用 `infra/docker-compose.dev.yml`，
示例凭据只用于本地开发，不代表真实服务器凭据。

```powershell
docker compose -f infra/docker-compose.dev.yml up -d postgres
docker compose -f infra/docker-compose.dev.yml ps
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

M2 的 Redis 服务仅通过 Compose profile 预留：

```powershell
docker compose -f infra/docker-compose.dev.yml --profile optional up -d redis
```

当前生产代码路径未使用 Redis。

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

推荐使用 Docker Compose：

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
