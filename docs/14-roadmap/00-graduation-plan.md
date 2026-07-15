# 毕设阶段计划

> 来源：[设计书 18 章](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：概述 M0-M10 阶段；详细任务、勾选状态和当前指针以
> [03-implementation-milestone-flow.md](03-implementation-milestone-flow.md)
> 为唯一总排期清单。

## 执行顺序

```text
M0  文档、范围与治理
M1  Monorepo 与最小工程
M2  数据模型、API 与事件底座
M3  控制台任务主流程
M4  Agent 编排与结构化输出
M5  Tool Gateway 与本地工具
M6  本地代码、测试与 PR 等价闭环
M7  Ops Hub 常驻控制面、CI 与远端部署
M8  监控、告警与 SRE
M9  Desktop、用户/RBAC 与安全产品化
M10 跨平台发行与最终验收
```

## 阶段边界

### M0-M6：当前已完成基线

- M1-M3：FastAPI、PostgreSQL/Alembic、Vite/React 控制台和共享契约。
- M4：显式状态机、Requirement/Architect/Planner、Task root conversation。
- M5：Tool Gateway、风险/审批/审计和本地受控工具。
- M6：固定 sample repo 的真实 diff、pytest/JUnit、Review、Bandit/pip-audit、
  branch/commit/format patch 和本地等价 PR record。

当前控制台仍是 Web/Vite，Sandbox 仍是 allowlist workspace + subprocess；
Tauri 安装包、Docker sandbox、真实 child 调度、远端 CI/部署和监控不属于
M1-M6 已交付能力。

### M7：Ops Hub、CI 与部署

- Linux Ops Hub 持续运行 Platform、Agents、Workflow、PostgreSQL/Redis。
- 精确 commit 经 release candidate approval、唯一 `workflow_dispatch`、不可变
  OCI digest、ReleasePlan 和 deployment approval 后由 Remote Agent 部署。
- 正常 continuation 由服务端 WorkflowJob/worker 自动推进；`run-next` 只调试/
  演示/人工恢复。
- `cloudhelm.project.yaml`、`cloudhelm.env.schema.json` 与通用安全 renderer
  保证受管项目也可删除 Adapter 后独立运行。

### M8：监控与 SRE

- Prometheus、Loki、Alertmanager、Monitoring Collector。
- ProjectAlert、Incident、SRE 分析与 runbook proposal。
- Desktop 退出后监控、告警和分析继续。

### M9：Desktop 与用户权限

- Tauri、Local Runtime、运行时 Ops Hub profile。
- Desktop SQLite、OS credential store、snapshot + event sequence + SSE。
- User、Device、Session、Role、Permission、system/project/environment binding。
- Desktop 按 effective permissions/resource capabilities 展示功能，API 重新鉴权。
- System Owner 也不能绕过职责分离。

### M10：发行与最终验收

- Windows NSIS setup `.exe` 与 `CloudHelm.exe`。
- Linux AppImage 与 `.deb`。
- Ops Hub bootstrap、升级、备份恢复和卸载。
- standalone/managed 双路径、Adapter 删除、干净环境安装和最终 E2E。
- 完成答辩材料并标记 `v1.0.0`。

---
