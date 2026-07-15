# 后续生产扩展

> 来源：[设计书 16 章](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：定义部署拓扑、运行组件和演示/扩展路径。
## 验收关注点

- Linux Ops Hub 和 Remote Target 两条安装生命周期已独立完成并可升级/回滚。
- 远端业务项目可以从 Docker Compose 平滑演进到 Kubernetes/GitOps。
- 身份、权限、密钥、观测和 sandbox 可以替换为生产级组件而不破坏现有契约。

## 设计书摘录

### 16.4 后续生产扩展

如果继续扩展为真实平台：

1. 使用 Kubernetes 部署远端业务项目。
2. 使用 Argo CD 管理 GitOps。
3. 使用 OpenBao 管理密钥。
4. 使用 OPA 做工具权限策略。
5. 使用独立 sandbox pool 执行 Agent 任务。

本文件描述 M10 之后的扩展，不是当前 M7-M10 完成判定。M7-M10 仍使用
Linux Ops Hub + Docker Compose + Remote Agent，并以 scoped RBAC、TLS、备份恢复、
签名安装包和独立/受管项目双路径完成毕设验收。

---
