# 项目定位与命名

> 来源：[设计书 1-2 章](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：说明 CloudHelm 的项目边界、命名含义和总体定位。
## 阅读要点

- CloudHelm 不是单纯聊天机器人，而是面向真实软件工程流程的多 Agent DevOps 平台。
- MVP 重点打通：本地 Agent 开发、真实 CI 制品、Release / Deploy Agent 经两道
  审批执行远端部署，以及远端业务项目监控运维。
- M7 固定使用 Gitea `workflow_dispatch`、不可变 OCI digest、Remote Agent 和
  Docker Compose 部署到 Linux staging / demo；CI 不执行部署。
- 关键闭环是 `Observe -> Plan -> Implement -> Verify -> Review -> Deploy -> Monitor -> Remediate -> Learn`。

## 设计书摘录

## 1. 项目名称

**云舵 CloudHelm：面向本地开发、Agent 执行远程部署与实时运维的多 Agent DevOps 平台**

简称：

**CloudHelm / 云舵**

推荐论文题目：

> **云舵：面向本地开发、Agent 执行远程部署与实时运维的多 Agent DevOps 平台设计与实现**

### 1.1 命名含义

“云舵”中的“云”代表远端服务器、云端部署环境和远程运行的业务项目；“舵”代表控制、调度、接管、审批、回滚和运维决策。整个名称强调：开发者在本地控制台中像驾驶员一样掌舵，通过 Agent、工具系统和远程控制平面，由 Release / Deploy Agent 把本地隔离环境中完成的软件开发结果安全地部署到远端环境，并持续监控和运维远端业务项目。

英文名 **CloudHelm** 中的 “Helm” 有“船舵、掌舵”的含义，同时也与
Kubernetes 生态中的 Helm 形成未来扩展联想，适合表达本项目“本地控制、Agent
执行远端部署、持续运维”的系统定位；该命名不代表 M7 使用 Kubernetes，K8s
属于生产扩展版。

---

## 2. 项目定位

本项目不是一个简单的聊天机器人，也不是“多个 Agent 互相聊天写代码”的演示系统，而是一个面向真实软件工程流程的 **本地开发、Agent 执行远程部署、实时监控与自动运维平台**。

系统的核心目标是打通三类场景：

1. **本地 Agent 开发**：开发者不是直接手写代码，而是在本机通过桌面控制台向 Agents 提出产品目标、功能需求、技术约束、验收标准和修改意见；Agents 在本地 Git worktree 与 Docker sandbox 中完成需求分析、架构设计、代码生成、测试、重构、文档和 PR。
2. **Agent 执行远程部署**：M6 形成的精确 commit 先经过 release candidate
   approval，随后才允许发布受控 Gitea ref，并由 Platform API 通过唯一固定
   workflow 的 `workflow_dispatch` 触发 CI。CI 只负责测试、安全扫描、构建和
   发布带不可变 OCI digest 的制品，不执行远端部署。Release / Deploy Agent
   生成 ReleasePlan 后还必须经过独立的 deployment approval，才可经 Tool
   Gateway、Deploy Tool、Deployment Controller 和 Remote Agent 部署到 Linux
   staging / demo 的 Docker Compose 环境。SSH 只用于单独审批后的固定只读诊断；
   production、Kubernetes 和 GitOps 属于增强版或生产扩展版。
3. **实时监控运维**：运维对象是 **已经由 Agent 部署到远端环境的业务项目**，包括该项目的进程、容器、服务、日志、指标、告警、发布版本和运行健康状态；这些数据实时回传到控制台，由 SRE Agent / Release Agent 进行分析、建议修复或触发审批。

系统目标是把软件生产过程抽象成一条可审计、可暂停、可回滚、可人工接管的自治流水线：

```text
Observe -> Plan -> Implement -> Verify -> Review -> Deploy -> Monitor -> Remediate -> Learn
```

毕设阶段不追求完整的 7×24 生产级全自动运维，而是实现一个可落地的 MVP：

```text
功能需求 / 迭代目标 / Issue / 告警输入
    -> Orchestrator 拆解任务
    -> Planner / Architect Agents 生成开发方案
    -> Coder / Tester / Reviewer Agents 在 Docker Sandbox 中实现功能
    -> 自动运行测试 / 安全扫描
    -> 生成 Git branch / commit / PR
    -> Reviewer Agent 审查
    -> 人类审批或拒绝 release candidate
    -> 发布受控 Gitea ref
    -> Platform API 通过固定 workflow_dispatch 触发 CI
    -> CI 运行测试 / 安全扫描 / 构建并产出不可变 OCI digest
    -> Release / Deploy Agent 生成 ReleasePlan
    -> 人类独立审批或拒绝 deployment
    -> Remote Agent 执行远程 Linux staging / demo Docker Compose 部署
    -> 远程监控 Agent 实时采集该业务项目的日志、指标和告警
    -> 全流程事件审计
```

M7 的完成边界止于 staging / demo 部署、健康验证和向 Monitoring 状态交接。
production、Kubernetes、自动回滚和交互式远程终端保留为后续增强能力。

---
