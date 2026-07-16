# Ops Hub 常驻安装与 Remote Target Bootstrap

> 目标：远端 Agents 运维系统在 Desktop 退出后保持在线，并能持续执行已持久化的
> CI、部署、监控和 Agent 工作流。

## 1. 安装 profile

### `desktop-dev`

供仓库贡献者开发和测试：

- Desktop/Web 控制台。
- 本地 Platform API。
- Docker Compose PostgreSQL/Redis。
- 本地 workspace 和测试工具。

该 profile 不是正式产品完成判定。

### Windows 开发机的 WSL Linux 依赖基线

Windows 仓库开发时，Ops Hub 的 Linux 行为统一在 Ubuntu 24.04 WSL2 中开发和
测试，不依赖 Docker Desktop。当前验证环境为：

```text
发行版：Ubuntu-24.04
WSL 版本：WSL2
发行版数据：D:\WSL\Ubuntu-24.04
Linux 用户：cloudhelm
容器运行时：Ubuntu 内原生 Docker Engine + Docker Compose v2
仓库挂载：/mnt/d/graduation project
```

该路径是当前开发机记录，不是产品硬编码。其他开发者可以使用不同磁盘目录。
WSL 原生 Docker named volume 默认位于同一发行版 VHD 的 `/var/lib/docker`；
隔离要求是使用不同 Compose project、named volume、network、credential 和
卸载入口，不能把“同一 VHD”误写成数据混用。若验收需要物理磁盘隔离，必须显式
配置独立 bind mount、独立 VHD 或独立 Linux 主机。

首次启动和每次环境变更后先执行预检，验证发行版、D 盘 VHD、普通用户 Docker
权限、daemon、Compose 和仓库挂载，而不是只根据历史容器状态判断环境可用：

```powershell
$Distro = 'Ubuntu-24.04'
$LinuxUser = 'cloudhelm'
$WslVhd = 'D:\WSL\Ubuntu-24.04\ext4.vhdx'

wsl.exe --status
wsl.exe --list --verbose

if (-not (Test-Path -LiteralPath $WslVhd)) {
  throw "WSL VHD not found: $WslVhd"
}

wsl.exe -d $Distro -u $LinuxUser -- bash -lc @'
set -euo pipefail
grep -qi 'wsl2' /proc/sys/kernel/osrelease
test -d '/mnt/d/graduation project'
id -nG | grep -qw docker
systemctl is-active --quiet docker
docker info >/dev/null
docker compose version
docker compose \
  -f '/mnt/d/graduation project/infra/docker-compose.dev.yml' \
  config --quiet
'@

if ($LASTEXITCODE -ne 0) {
  throw 'WSL/Docker preflight failed.'
}
```

WSL 在没有前台 Linux 进程时可能进入 `Stopped`，导致容器端口随之消失。开发
测试前用 Windows PowerShell 保证只存在一个隐藏 keepalive：

```powershell
$Distro = 'Ubuntu-24.04'
$LinuxUser = 'cloudhelm'

function Get-CloudHelmWslKeepaliveClient {
  $Matching = @(
    Get-CimInstance Win32_Process -Filter "Name='wsl.exe'" |
      Where-Object {
        $_.CommandLine -like "*-d $Distro*" -and
        $_.CommandLine -like "*-u $LinuxUser*" -and
        $_.CommandLine -like '*sleep infinity*'
      }
  )
  $MatchingIds = @(
    $Matching | ForEach-Object { [int]$_.ProcessId }
  )

  # 一次 wsl.exe 调用会生成 parent/child 两个同命令行进程；
  # 这里只返回没有匹配 parent 的根 client，避免把一次启动误计为两个。
  $Matching |
    Where-Object {
      $MatchingIds -notcontains [int]$_.ParentProcessId
    }
}

$KeepaliveClients = @(Get-CloudHelmWslKeepaliveClient)

if ($KeepaliveClients.Count -eq 0) {
  Start-Process `
    -FilePath "$env:SystemRoot\System32\wsl.exe" `
    -ArgumentList @(
      '-d', $Distro,
      '-u', $LinuxUser,
      '--', 'env', 'CLOUDHELM_WSL_KEEPALIVE=1',
      'sleep', 'infinity'
    ) `
    -WindowStyle Hidden
} elseif ($KeepaliveClients.Count -gt 1) {
  $KeepaliveClients |
    Sort-Object CreationDate |
    Select-Object -Skip 1 |
    ForEach-Object {
      Stop-Process -Id $_.ProcessId -ErrorAction Stop
    }
}

for ($Attempt = 1; $Attempt -le 20; $Attempt++) {
  Start-Sleep -Milliseconds 500
  $KeepaliveClients = @(Get-CloudHelmWslKeepaliveClient)
  if ($KeepaliveClients.Count -eq 1) {
    break
  }
}

if ($KeepaliveClients.Count -ne 1) {
  throw (
    'Expected one keepalive client, found ' +
    $KeepaliveClients.Count
  )
}
```

随后只在 WSL 原生 Docker 中启动仓库依赖：

```powershell
wsl -d Ubuntu-24.04 -u cloudhelm -- bash -lc @"
cd '/mnt/d/graduation project'
docker compose -f infra/docker-compose.dev.yml \
  --profile optional up -d postgres redis
docker compose -f infra/docker-compose.dev.yml \
  --profile optional ps
docker exec cloudhelm-postgres-dev \
  pg_isready -U cloudhelm -d cloudhelm
docker exec cloudhelm-redis-dev redis-cli ping
"@

Start-Sleep -Seconds 60

if (
  -not (
    Test-NetConnection `
      127.0.0.1 `
      -Port 15432 `
      -InformationLevel Quiet
  )
) {
  throw 'PostgreSQL port 15432 is not reachable from Windows.'
}
```

通过标准：

- `Ubuntu-24.04` 状态为 `Running`。
- PostgreSQL health 为 `healthy`。
- Redis 返回 `PONG`。
- Windows 侧 Platform API 测试可通过 `127.0.0.1:15432` 访问 PostgreSQL。
- WSL 停止、容器重启和数据卷位置都必须记录，不使用历史通过数替代当前验证。

M7-2C 起 Celery worker 也在该 WSL 基线中运行。2026-07-16 已使用官方安装器把
`uv 0.11.29` 安装到 `/home/cloudhelm/.local/bin`。为避免 Windows/Linux wheel
混用，WSL 使用独立环境：

```text
UV_PROJECT_ENVIRONMENT=/home/cloudhelm/.cache/cloudhelm/workflow-engine-venv
```

验证命令：

```powershell
wsl -d Ubuntu-24.04 -u cloudhelm `
  --cd "/mnt/d/graduation project/modules/workflow-engine" -- `
  env UV_PROJECT_ENVIRONMENT=/home/cloudhelm/.cache/cloudhelm/workflow-engine-venv `
  UV_LINK_MODE=copy `
  /home/cloudhelm/.local/bin/uv sync --frozen --all-groups

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

Redis stop/start 集成使用临时 `cloudhelm-redis-workflow-test` container 和
`127.0.0.1:16380`，验证 broker 不可用时 PostgreSQL job 保持 pending、Redis
恢复后 dispatcher 补投、prefork worker 只 claim 一次并收敛 succeeded；同一
集成组还会 SIGKILL 独立 prefork 进程组并验证过期 `none` job 安全回排。fixture
强制使用 DB 15，自动创建/删除临时 container，保留共享开发 PostgreSQL/Redis。

开发测试结束时可以只停止 CloudHelm keepalive，不影响其他发行版会话：

```powershell
$KeepaliveClients = @(Get-CloudHelmWslKeepaliveClient)
$KeepaliveClients | ForEach-Object {
  Stop-Process -Id $_.ProcessId -ErrorAction Stop
}

for ($Attempt = 1; $Attempt -le 20; $Attempt++) {
  Start-Sleep -Milliseconds 500
  if (@(Get-CloudHelmWslKeepaliveClient).Count -eq 0) {
    break
  }
}

if (@(Get-CloudHelmWslKeepaliveClient).Count -ne 0) {
  throw 'CloudHelm WSL keepalive is still running.'
}
```

需要同时停止整个发行版时再执行：

```powershell
wsl.exe --terminate Ubuntu-24.04
```

`infra/docker-compose.dev.yml` 仍只是仓库开发依赖，不等于正式 `ops-hub`
installation。正式 M7 安装验收继续要求独立 Linux VM/主机、TLS ingress、
服务凭据、备份和常驻 worker 证据。

### `ops-hub`

常在线 Linux 运维控制面：

```text
TLS ingress
platform-api
orchestrator
agent-runtime workers
tool-gateway / policy / audit
workflow-engine scheduler/workers
deployment-controller
postgresql
redis
artifact storage
gitea / act_runner / OCI registry（内置或受控外接）
```

M8 增加 monitoring collector、Prometheus、Loki、Alertmanager 和 SRE workers。

### `demo-all-in-one`

一台 Linux 主机同时承载：

- `cloudhelm-ops` Compose project。
- `cloudhelm-remote-agent.service`。
- telemetry collectors。
- 一个或多个独立业务项目 Compose project。

该 profile 适合答辩，但仍必须保持 network、volume、credential 和生命周期隔离。

## 2. 两条独立安装链

日常部署链要求 Deployment Controller 调用一个已经在线且已认证的 Remote Agent，
因此中心设施安装和目标主机注册都不能依赖同一条业务项目部署链，否则形成自举
循环。

### 2.1 Ops Hub installation/bootstrap

每套 CloudHelm 中心设施执行一次，可使用受控安装脚本、cloud-init 或人工执行的
固定安装流程。它只负责：

1. 安装 TLS ingress、Platform API、Orchestrator/Workers、Tool Gateway、
   Workflow Engine、Deployment Controller、PostgreSQL、Redis 和 artifact storage。
2. 安装或受控外接 Gitea、act_runner 和 OCI registry。
3. 创建专用服务用户、持久卷、备份/恢复目录和 systemd/Compose 启动入口。
4. 写入 M7 服务间凭据并验证 `/health`、`/ready`、worker/scheduler heartbeat、
   持久化和备份。

Ops Hub installation 不以业务 Project 或 Environment 为单位重复执行。
M7 继续使用当前受控网络/认证边界，不创建真实用户、Desktop device 或 session。
M9 实现 identity bootstrap endpoint、一次性 token、首个 `system_owner` 和
Desktop device/session；M10 安装向导调用该已实现能力。

### 2.2 Remote Target / Environment bootstrap

每台受管 Linux 目标独立执行，可使用受控安装脚本、cloud-init，或单独审批的固定
bootstrap SSH profile。它只负责：

1. 安装或验证 Docker Engine/Compose 等目标运行时。
2. 安装 `cloudhelm-remote-agent.service` 和采集器。
3. 写入目标独立的 TLS trust、machine credential 和注册信息。
4. 向既有 Ops Hub 注册 Environment/RemoteTarget，并验证 heartbeat、版本与能力。

该流程不得安装 Platform API、PostgreSQL、Redis、Gitea/registry、用户 pairing
或 Ops Hub 备份体系。完成后，普通业务项目部署只验证目标能力并发布独立业务
Compose project。

### 2.3 `demo-all-in-one`

答辩 profile 可以在同一 Linux 主机先执行 Ops Hub installation，再执行 Remote
Target bootstrap，但必须保留两套 manifest、credential、服务单元、数据目录和
卸载入口；卸载目标 Agent 不得隐式卸载 Ops Hub，反之亦然。

## 3. 计划目录

```text
infra/
  ops-hub/
    compose.yaml
    .env.example
    install.sh
    upgrade.sh
    backup.sh
    restore.sh
    uninstall.sh
    cloudhelm-ops-hub.service
  remote-agent/
    install.sh
    upgrade.sh
    uninstall.sh
    cloudhelm-remote-agent.service
```

本轮只规划目录，不创建脚本或生产配置。

M7 只要求形成可运行的最小 `ops-hub` profile，以及注册到既有 Ops Hub 的 Remote
Target / Environment bootstrap，支撑真实 CI/部署 E2E。M10 完成 Ops Hub 的安装、
升级、备份/恢复、卸载和兼容检查；Remote Target 则完成安装、升级、卸载、重新
注册和 operation/release 数据保留验证，并归档答辩发行证据。

## 4. 网络与凭据

- 对外只暴露 TLS ingress。
- PostgreSQL、Redis、worker、Docker socket 和内部管理端口不得暴露公网。
- Desktop 使用用户/device credential。
- Local Runtime 使用独立 device credential。
- Controller 与 Remote Agent 使用 machine credential/mTLS 或独立签名。
- 业务项目 secret 从项目 env profile/credential store 注入，不复用 Ops Hub
  数据库密码或 machine secret。

## 5. Compose project 隔离

```text
cloudhelm-ops
cloudhelm-project-<project-slug>
cloudhelm-observability
```

要求：

- 独立 network。
- 独立 named volume。
- 独立 env/credential 文件。
- 独立升级、备份和卸载流程。
- 业务项目卸载不删除 Ops Hub 或审计数据。
- Ops Hub 升级不得重建业务项目数据卷。
- Remote Agent 只允许操作已经注册、审批并绑定 manifest/digest 的业务 project。

## 6. 常在线行为

Desktop 退出后继续：

- WorkflowJob dispatch、claim、lease、heartbeat 和 retry。
- 已批准 CI 与部署步骤。
- Remote Agent heartbeat、service status 和受限日志。
- M8 monitoring、alert 和 SRE proposal。
- EventLog、Approval wait、审计和通知。

停止：

- 需要本机 workspace 的 Local Runtime 步骤。
- 需要新人工审批或新交互输入的步骤。

## 7. 基础运维门禁

常在线并不等于生产级高可用，但最小 Ops Hub 必须具备：

- systemd/Compose restart policy。
- Platform API `/health` 与 `/ready`。
- worker/scheduler heartbeat。
- WorkflowJob pending/lease/dispatcher lag 检查。
- PostgreSQL 持久卷和备份/恢复脚本。
- Redis 重启后由 PostgreSQL job 补投。
- Remote Agent offline 检测。
- 磁盘空间、证书到期和备份失败提示。
- 版本兼容与升级前检查。

完整 dashboard、HA、production、Kubernetes 和自动故障转移仍属于增强版。

## 8. 安装验收

### 8.1 M7 安装与常驻执行

1. 在干净 Linux VM 执行 M7 Ops Hub installation 后，中心组件、数据库、worker、
   TLS ingress 和服务凭据在线；此阶段不宣称已创建真实 user/device/session。
2. 在另一台干净 Linux 目标执行 Remote Target bootstrap，只安装目标运行时、
   Remote Agent 和采集器，并成功注册到既有 Ops Hub。
3. `demo-all-in-one` 在同机执行两条安装链时，manifest、credential、数据目录和
   卸载入口仍可独立验证。
4. 通过当前受控客户端/API 提交一个无需新审批的服务端流程，然后关闭客户端；
   worker 继续执行并写 EventLog，高风险步骤停在 pending approval。
5. 重启 Redis 后 pending WorkflowJob 由 PostgreSQL 补投。
6. 重启 Ops Hub 后 Remote Agent 自动恢复 heartbeat。
7. 部署/卸载业务项目不影响 Ops Hub；卸载 Remote Agent 也不删除 Ops Hub 数据。
8. 执行 PostgreSQL 备份并在隔离环境恢复。

### 8.2 M9/M10 identity 与 Desktop 集成

1. 安装向导调用 identity bootstrap，使用一次性 token 创建首个 owner、Desktop
   device/session，并验证第二次调用稳定冲突。
2. Desktop 使用 Ed25519 challenge proof 登录；Local Runtime 完成 pairing 和短期
   device session。
3. Desktop 提交任务后退出；无需新审批的服务端步骤继续，高风险步骤持久等待。
4. Desktop 重连后按 user-control/project sequence 补齐全部状态和权限变化。
