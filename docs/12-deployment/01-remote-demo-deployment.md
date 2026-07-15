# 远端业务项目演示部署

> 来源：[设计书 16 章](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：定义部署拓扑、运行组件和演示/扩展路径。
## 验收关注点

- Linux Ops Hub 在 Desktop 退出后保持在线。
- 远端 demo 主机能运行 Remote Agent、Docker Compose 和监控采集组件。
- 控制台在 M7 展示远端服务状态、受限日志和部署版本；集中指标属于 M8 验收。

## 目标拓扑

```text
Windows/Linux Desktop
  -> HTTPS
  -> cloudhelm-ops
       Platform API / Orchestrator / Agents / Tool Gateway
       Workflow Engine / Deployment Controller
       PostgreSQL / Redis
       Gitea / act_runner / OCI registry（内置或受控外接）
  -> cloudhelm-remote-agent.service
  -> cloudhelm-project-<project-key>
```

Ops Hub、Remote Agent、观测栈和业务项目使用独立 Compose project、network、
volume、credential、升级和卸载流程。业务项目卸载不得删除 Ops Hub 或审计数据。

## 设计书摘录

### 16.2 远端业务项目演示部署

答辩时建议准备一个真实远端部署目标，可以是云服务器、局域网 Linux 虚拟机或另一台主机。

```text
Remote Linux Server / VPS
  - Docker Engine
  - Docker Compose
  - remote-agent.service
  - node_exporter
  - cAdvisor
  - Grafana Alloy / Fluent Bit
  - sample business project
      - api service
      - worker service，可选
      - frontend service，可选
      - /health
      - /metrics
```

远端业务项目目录示例：

```text
/opt/cloudhelm/projects/<project-key>/
├── releases/
│   ├── 20260707-001/
│   └── 20260707-002/
├── current -> releases/20260707-002
├── docker-compose.yml
├── .env
├── logs/
└── rollback.json
```

远端部署流程：

```text
1. CI 构建镜像并推送到 registry。
2. Release / Deploy Agent 读取 CI 产物并生成 release plan。
3. Release / Deploy Agent 通过 Tool Gateway 发起部署请求。
4. 用户在控制台审批部署 staging。
5. Deployment Controller 根据 `cloudhelm.project.yaml`、
   `cloudhelm.env.schema.json` 和固定 schema 使用通用安全 renderer 生成固定
   OCI digest 的 Compose；secret
   只使用远端 env profile / systemd credential / `_FILE` 引用。
6. Remote Agent 拉取 `repository@sha256:...` 并复核 registry/RepoDigests。
7. 远端执行 `docker compose config`、`pull`、`up -d --wait`。
8. 远端执行独立 HTTP health check。
9. Platform API 注册 ServiceInstance 和 MonitoringRegistered。
10. 控制台展示远端服务状态、M7 受限日志和部署版本；M8 再接集中监控。
```

上述业务项目必须同时提供 standalone Dockerfile/Compose/README/migration。
删除两个 CloudHelm adapter 文件后，项目仍能独立构建、测试、部署和运行。
