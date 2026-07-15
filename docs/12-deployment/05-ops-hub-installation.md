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
