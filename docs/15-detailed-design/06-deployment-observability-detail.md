# 部署与可观测性细化

> 来源：设计书 5.4、15、16 章  
> 目的：细化本地开发环境、远端演示环境、部署流程和监控采集路径。

## 1. 本地开发拓扑

```text
Windows Host
├── Tauri Control Console
├── Docker Desktop
└── docker-compose.dev.yml
    ├── postgres
    ├── redis
    ├── platform-api
    ├── orchestrator-worker
    ├── tool-gateway
    ├── mcp-toolservers
    ├── gitea
    ├── prometheus
    ├── grafana
    ├── loki
    └── langfuse，可选
```

## 2. 远端演示拓扑

```text
Remote Linux Server / VM
├── Docker Engine
├── Docker Compose
├── remote-agent.service
├── node_exporter
├── cAdvisor
├── Grafana Alloy / Fluent Bit
└── /opt/cloudhelm/projects/sample-repo-python
    ├── current -> releases/20260707-001
    ├── docker-compose.yml
    ├── release-metadata.json
    ├── logs/
    └── rollback.json
```

## 3. 部署制品

### ReleasePlan

```json
{
  "project_id": "uuid",
  "task_id": "uuid",
  "environment_id": "uuid",
  "remote_target_id": "uuid",
  "pull_request_record_id": "uuid",
  "ci_run_id": "uuid",
  "version": "20260707-001",
  "commit_sha": "40-or-64-char-full-sha",
  "image_ref": "registry.local/sample",
  "image_digest": "sha256:...",
  "env_profile_ref": "sample/staging-v1",
  "compose_template_revision": "sha256:...",
  "services": [
    {
      "name": "api",
      "image": "registry.local/sample-api@sha256:...",
      "health_url": "http://sample.local/health",
      "ports": ["8000:8000"]
    }
  ],
  "rollback_candidate": "20260706-002",
  "risk_level": "L3",
  "release_plan_sha256": "sha256:..."
}
```

### Rendered compose

Deployment Controller 生成或更新：

- `docker-compose.yml`
- release metadata。
- `rollback.json`

secret 不写入 ReleasePlan、Compose 或 Artifact。Remote Agent 只根据
`env_profile_ref` 从 systemd credential / `_FILE` / 受控 credential store 读取。

## 4. 部署步骤

```text
1. 用户批准绑定 PullRequestRecord、完整 commit、受控 ref 的 release candidate。
2. Git Tool 验证远端 ref，Platform API 使用固定 workflow id 执行
   `workflow_dispatch`。
3. CI 完成 test/security/build，推送镜像并发布 manifest/digest。
4. Release / Deploy Agent 校验 commit/digest 全链并创建 ReleasePlan。
5. Tool Gateway 为 `deploy.deploy_staging` 创建 L3 deployment approval。
6. 审批通过并显式推进后，workflow worker 调用 Deployment Controller。
7. Controller 渲染固定 digest 的 Compose 和 manifest hash。
8. Remote Agent 执行 `docker compose config` 和安全 policy。
9. 执行 pull，并用 registry/`RepoDigests`/平台 manifest 复核 digest。
10. 执行 `docker compose up -d --wait`。
11. 执行 `docker compose ps` 和资源 inspect。
12. 调用独立 HTTP `/health`。
13. Platform API 注册 service_instances 和 MonitoringRegistered。
14. Task 进入 Monitoring；M7 只保留 rollback candidate，不自动回滚。
```

## 5. 健康检查

|检查|命令/方式|通过标准|
|---|---|---|
|容器状态|`docker compose ps`|服务为 running/healthy|
|HTTP 健康|`GET /health`|2xx 且返回 ok|
|指标端点|`GET /metrics`|Prometheus 格式可解析|
|日志错误|Loki 查询 `level=error`|部署后短窗口无大量错误|
|Remote Agent 心跳|heartbeat timestamp|小于阈值，例如 60 秒|

## 6. 采集链路

```text
应用 stdout/file logs
  -> Grafana Alloy / Fluent Bit
  -> Loki
  -> Monitoring Collector
  -> ProjectLogReceived / ProjectAlertFired

应用 /metrics
  -> Prometheus
  -> Grafana dashboard / Alertmanager
  -> Monitoring Collector
  -> ProjectMetricUpdated

主机指标
  -> node_exporter
  -> Prometheus

容器指标
  -> cAdvisor
  -> Prometheus

可用性探测
  -> blackbox_exporter / Uptime Kuma
  -> Alertmanager
```

## 7. 指标命名建议

### 平台指标

- `cloudhelm_task_total`
- `cloudhelm_task_duration_seconds`
- `cloudhelm_agent_run_duration_seconds`
- `cloudhelm_tool_call_total`
- `cloudhelm_tool_call_failure_total`
- `cloudhelm_approval_wait_seconds`
- `cloudhelm_llm_token_total`
- `cloudhelm_llm_cost_usd_total`

### 远端业务指标

- `cloudhelm_project_service_up`
- `cloudhelm_project_http_error_rate`
- `cloudhelm_project_http_latency_p95`
- `cloudhelm_project_container_restart_total`
- `cloudhelm_project_deployment_total`
- `cloudhelm_project_alert_total`
- `cloudhelm_remote_agent_heartbeat_age_seconds`

标签建议：

```text
project_id
environment_id
deployment_id
service_id
service_name
release_version
commit_sha
```

## 8. 日志标签建议

```json
{
  "project_id": "uuid",
  "environment_id": "uuid",
  "deployment_id": "uuid",
  "service": "api",
  "release_version": "20260707-001",
  "commit_sha": "abc123",
  "level": "error"
}
```

## 9. 告警规则建议

|告警|条件|严重级别|
|---|---|---|
|ProjectServiceDown|`service_up == 0` 持续 1 分钟|critical|
|HighErrorRate|5xx 错误率 > 5% 持续 5 分钟|warning/critical|
|HighLatencyP95|P95 延迟 > 1s 持续 5 分钟|warning|
|ContainerRestartLoop|容器 5 分钟内重启次数 > 3|critical|
|DeploymentUnhealthy|部署后健康检查失败|critical|
|RemoteAgentOffline|心跳超过 60 秒|warning|

## 10. Trace 串联

一次任务应能通过 `trace_id` 串起：

```text
task_id
  -> workflow_run
  -> agent_run
  -> tool_call
  -> sandbox command
  -> git PR
  -> CI build
  -> deployment
  -> remote_agent operation
  -> health_check
  -> monitoring alert
```

## 11. 答辩演示准备清单

- 本地 compose 一键启动。
- Gitea 中存在 sample repo。
- 控制台能创建任务。
- 远端主机可 SSH 或 Remote Agent 在线。
- sample repo 有一个稳定旧版本和一个可部署新版本。
- Prometheus/Grafana/Loki 页面可打开。
- 准备一个可触发的故障：停止容器、制造 500、错误配置。
- 准备回滚目标 release。
