# 答辩演示环境

> 来源：[设计书 16 章](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：定义部署拓扑、运行组件和演示/扩展路径。
## 验收关注点

- Linux Ops Hub installation 能启动中心控制面；最终用户 Desktop 不依赖
  Docker、PostgreSQL 或 Redis。
- 远端 demo 主机能运行 Remote Agent、Docker Compose 和监控采集组件。
- 控制台在 M7 展示远端服务状态、受限日志和部署版本；集中指标属于 M8 验收。

## 设计书摘录

### 16.3 演示环境

答辩演示建议使用一个可安装 Desktop 和一台常在线 Linux 主机。Desktop 可以在
Windows 或 Linux；Docker/PostgreSQL/Redis 不安装到最终用户桌面：

```text
Windows/Linux Desktop
  - CloudHelm Desktop
  - Local Runtime sidecar
  - SQLite cache / draft / sequence
  - OS credential store

Linux Demo Host
  - cloudhelm-ops Compose project
      - TLS ingress
      - Platform API / Orchestrator / Agent Runtime / Tool Gateway
      - Workflow Engine / Deployment Controller
      - PostgreSQL / Redis
      - Gitea / act_runner / OCI registry
      - M8: Prometheus / Grafana / Loki / Alertmanager
  - cloudhelm-remote-agent.service
  - cloudhelm-project-<project-key> Compose project
  - cloudhelm-observability Compose project
```

答辩允许 Ops Hub、Remote Agent、观测栈和业务项目位于同一 Linux 主机，但它们
仍使用独立 network、volume、credential、备份和卸载流程。演示必须覆盖 Desktop
退出后无需新审批的服务端流程继续，以及重新登录后按 event sequence 补齐。
