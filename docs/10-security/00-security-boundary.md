# 安全边界

> 来源：[设计书 14.1](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：定义代码、Git、生产、密钥、数据库、部署、工具和成本的安全边界。
## 基线要求

- Agent 默认没有生产权限。
- 代码修改只允许发生在 sandbox worktree。
- 密钥不落日志，高风险数据库和部署动作必须审批。

## 设计书摘录

### 14.1 安全边界

|领域|约束|
|---|---|
|代码修改|只能在 sandbox worktree 中修改|
|Git 操作|必须走 branch + commit + PR|
|生产环境|Agent 默认无生产 SSH 权限|
|密钥|通过 scoped temporary token 获取，禁止明文写入日志|
|数据库|destructive migration 必须人工审批|
|部署|Release / Deploy Agent 是部署编排入口；Git / CI 提供可追踪产物，Tool Gateway、审批和 Deployment Controller 控制实际远端变更|
|工具调用|全部记录 tool_calls 和 event_logs|
|权限|按 Agent 角色发放最小权限|
|成本|按 project / task / agent 设置 token 和资源预算|
