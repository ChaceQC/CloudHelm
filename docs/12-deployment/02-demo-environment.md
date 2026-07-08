# 答辩演示环境

> 来源：[设计书 16 章](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：定义部署拓扑、运行组件和演示/扩展路径。
## 验收关注点

- 本地 Docker Compose 能启动核心平台依赖。
- 远端 demo 主机能运行 Remote Agent、Docker Compose 和监控采集组件。
- 控制台能展示远端服务状态、日志、指标和部署版本。

## 设计书摘录

### 16.3 演示环境

答辩演示建议使用本机或局域网单机部署：

```text
Windows Host
  - Tauri Control Console
  - Docker Desktop
  - Linux containers
      - PostgreSQL
      - Redis
      - FastAPI
      - Tool Servers
      - Gitea
      - Prometheus / Grafana
      - Loki / Alertmanager

Remote Linux Server / VM
  - Remote Agent
  - Docker Compose
  - Deployed Sample Project
  - node_exporter / cAdvisor / log collector
```
