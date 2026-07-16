# modules

本目录保存 CloudHelm 后端与平台能力模块。当前 M6 已落地，M7-1、M7-2A/B/C
已实现：

- `platform-api`：FastAPI、PostgreSQL、Alembic、Agent/Tool/Artifact/PR API，
  以及 M7-1 Environment、RemoteTarget、machine-auth 与 heartbeat 状态事件。
- `orchestrator`：M4 需求设计状态机和 M6 本地开发状态机。
- `agent-runtime`：Requirement、Architect、Planner、Scaffold、Coder、Tester、
  Reviewer、Security 八类普通 Agent。
- `tool-gateway`：Requirement、Design、Repo、Scaffold、Sandbox、Test、
  Security、Git 和审批占位工具的统一策略与审计入口。
- `remote-agent`：M7-1 的健康/版本/capability 查询和 machine-auth 签名
  heartbeat；部署、Compose、日志和 diagnostics 仍属于后续 M7 切片。
- `workflow-engine`：M7-2C Redis/Celery durable dispatcher、worker claim、
  lease/heartbeat、retry、stale reclaim，以及首个真实
  `release_candidate_reconcile` handler；PostgreSQL 是业务权威。

`sandbox-runner`、`deployment-controller`、`monitoring-collector` 等模块仍按
后续里程碑实现；当前本地 Sandbox 使用受控目录与 `subprocess`，不等同于
独立容器沙箱。
