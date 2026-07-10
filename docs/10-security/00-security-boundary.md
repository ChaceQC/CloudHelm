# 安全边界

> 来源：[设计书 14.1](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：定义代码、Git、生产、密钥、数据库、部署、工具和成本的安全边界。
## 基线要求

- Agent 默认没有生产权限。
- 代码修改只允许发生在 sandbox worktree。
- 密钥不落日志，高风险数据库和部署动作必须审批。

## M5 本地工具边界

- Platform API 通过 `CLOUDHELM_TOOL_WORKSPACE_ROOTS` 配置允许根目录；未配置时默认拒绝 Repo、Sandbox、Git 工作区。Repo Tool 再使用 `Path.resolve()` 与 `relative_to()` 限制在对应 `workspace_root` 内，并拒绝 `.env`、私钥、证书、`.git`、依赖目录和构建产物。
- Sandbox Tool 使用命令数组和环境变量白名单，不允许 shell 字符串、高危命令、全局安装、网络扫描或后台常驻服务。
- Git Tool 只允许本地 `status`、`diff`、`switch -c`、显式路径 `commit`；不允许 push、force reset、clean、rebase、tag release。
- ToolCall 数据库参数只保存脱敏快照；文件正文只保留长度和 hash，Token、Cookie、密码、Bearer 凭据和私钥块不得进入参数、结果或输出摘要。
- Tool Gateway 审计主体由服务端生成并保存在 `audit_json`，调用方不能伪造参数 hash、风险、幂等键或终态。
- L3/L4 工具只创建审批请求，不执行远端副作用。

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
