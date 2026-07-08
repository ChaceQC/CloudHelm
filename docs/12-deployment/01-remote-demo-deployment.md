# 远端业务项目演示部署

> 来源：[设计书 16 章](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：定义部署拓扑、运行组件和演示/扩展路径。
## 验收关注点

- 本地 Docker Compose 能启动核心平台依赖。
- 远端 demo 主机能运行 Remote Agent、Docker Compose 和监控采集组件。
- 控制台能展示远端服务状态、日志、指标和部署版本。

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
/opt/cloudhelm/projects/sample-repo-python/
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
5. Deployment Controller 生成 compose 文件和 .env。
6. Remote Agent 拉取 compose 文件和镜像 tag。
7. 远端执行 docker compose up -d。
8. 远端执行 health check。
9. Prometheus / Loki 开始采集该版本运行数据。
10. 控制台展示远端服务状态、日志、指标和部署版本。
```
