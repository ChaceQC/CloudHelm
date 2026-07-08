# 本地开发部署

> 来源：[设计书 16 章](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：定义部署拓扑、运行组件和演示/扩展路径。
## 验收关注点

- 本地 Docker Compose 能启动核心平台依赖。
- 远端 demo 主机能运行 Remote Agent、Docker Compose 和监控采集组件。
- 控制台能展示远端服务状态、日志、指标和部署版本。

## M1 本地最小工程命令

M1 暂不启动完整 Docker Compose，只验证平台 API、控制台和共享契约的最小工程基线。

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

Windows PowerShell 如拦截 `npm.ps1`，使用 `npm.cmd`。Tauri 桌面壳在控制台主流程阶段接入；当前 M1 只验证 React/TypeScript 骨架。

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
