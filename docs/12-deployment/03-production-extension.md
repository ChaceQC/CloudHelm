# 后续生产扩展

> 来源：[设计书 16 章](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：定义部署拓扑、运行组件和演示/扩展路径。
## 验收关注点

- 本地 Docker Compose 能启动核心平台依赖。
- 远端 demo 主机能运行 Remote Agent、Docker Compose 和监控采集组件。
- 控制台能展示远端服务状态、日志、指标和部署版本。

## 设计书摘录

### 16.4 后续生产扩展

如果继续扩展为真实平台：

1. 使用 Kubernetes 部署远端业务项目。
2. 使用 Argo CD 管理 GitOps。
3. 使用 OpenBao 管理密钥。
4. 使用 OPA 做工具权限策略。
5. 使用独立 sandbox pool 执行 Agent 任务。

---
