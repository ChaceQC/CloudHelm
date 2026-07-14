# modules

本目录保存 CloudHelm 后端与平台能力模块。当前 M6 已落地：

- `platform-api`：FastAPI、PostgreSQL、Alembic、Agent/Tool/Artifact/PR API。
- `orchestrator`：M4 需求设计状态机和 M6 本地开发状态机。
- `agent-runtime`：Requirement、Architect、Planner、Scaffold、Coder、Tester、
  Reviewer、Security 八类普通 Agent。
- `tool-gateway`：Requirement、Design、Repo、Scaffold、Sandbox、Test、
  Security、Git 和审批占位工具的统一策略与审计入口。

`sandbox-runner`、`remote-agent`、`deployment-controller`、
`monitoring-collector` 等远端模块仍按后续里程碑实现；当前本地 Sandbox 使用
受控目录与 `subprocess`，不等同于独立容器沙箱。
