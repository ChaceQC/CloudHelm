# 远端业务项目运维技术栈

> 来源：[设计书 5.3](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：按 MVP、增强版、生产扩展版拆分远端运维能力。
## 版本策略

- MVP：一台 Ubuntu/Linux 远端主机 + Docker Compose + SSH/Remote Agent + Prometheus/Loki。
- 增强版：preview 环境、反向代理、Trace、Runbook 自动化、安全网络。
- 生产扩展版：Kubernetes/K3s、GitOps、Helm/Kustomize、OPA/Kyverno、OpenBao、OpenTofu。

## 设计书摘录

### 5.3 远端业务项目运维技术选型

远端业务项目运维能力建议分成三个版本：MVP、增强版、生产扩展版。

#### 5.3.1 MVP 版本

|能力|技术选型|说明|
|---|---|---|
|远端环境|一台 Ubuntu 云服务器 / Linux 虚拟机|作为 staging / demo 环境|
|应用运行方式|Docker Engine + Docker Compose|每个业务项目一个 compose project|
|部署方式|SSH + Ansible Playbook|CI 构建后通过 SSH 到远端执行部署脚本|
|远程控制|Remote Agent + SSH fallback|默认走平台 Remote Agent，Agent 不可用时用 SSH 只读诊断|
|远程终端|WebSocket + xterm.js|桌面端打开远程业务项目所在主机的受控终端|
|服务状态|`docker compose ps` / `systemctl status`|查询业务项目服务运行状态|
|日志|Docker logs + Grafana Alloy / Fluent Bit -> Loki|按 project / environment / service 打标签|
|主机指标|node_exporter -> Prometheus|采集远端主机基础资源|
|容器指标|cAdvisor -> Prometheus|采集业务容器资源和重启状态|
|接口探活|blackbox_exporter / Uptime Kuma|HTTP 健康检查和可用性记录|
|告警|Alertmanager|业务服务不可用、错误率、资源过高、部署失败|
|错误追踪|Sentry，可选|如果示例业务项目是 Web 应用，可接入 Sentry SDK|
|回滚|Docker image tag / compose 文件版本回退|记录上一个成功 release，支持审批后回滚|

MVP 的核心不是管理很多云资源，而是让开发者指导 Agents 在本地隔离环境中完成业务项目开发，再由 Release / Deploy Agent 基于 CI 产物和人工审批把开发结果完整部署到远端，并对这个远端业务项目做可视化运维。

#### 5.3.2 增强版

|能力|技术选型|说明|
|---|---|---|
|多环境|staging / production / preview env|每个 PR 可以部署 preview，每个 main 分支部署 staging|
|部署平台参考|Coolify / Dokploy / CapRover|参考 Git 到远端容器服务的部署体验|
|容器管理参考|Portainer|参考容器状态、日志、重启、环境变量管理|
|反向代理|Traefik / Caddy|自动路由、HTTPS、蓝绿 / 灰度入口|
|链路追踪|OpenTelemetry Collector + Tempo / Jaeger|采集业务项目请求链路|
|自动 Runbook|Rundeck / StackStorm / Windmill|把重启、清缓存、回滚、扩容封装为可审批动作|
|安全连接|WireGuard / Headscale|控制平面和远端节点之间建立安全网络|

#### 5.3.3 生产扩展版

|能力|技术选型|说明|
|---|---|---|
|集群运行|Kubernetes / K3s|远端业务项目以 Deployment / Service / Ingress 运行|
|GitOps|Argo CD / Flux CD|远端环境只接受 Git 仓库中的部署声明|
|包管理|Helm / Kustomize|管理业务项目部署模板|
|策略控制|OPA / Kyverno|限制危险部署、权限、镜像来源|
|密钥管理|OpenBao / External Secrets Operator|远端环境不保存明文密钥|
|云资源管理|OpenTofu / Terraform|声明式创建云服务器、网络、数据库、集群|
