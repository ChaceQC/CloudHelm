# 权限模型

> 来源：`云舵 CloudHelm 毕设设计书.md`、M5 Tool Gateway 实现  
> 目的：定义 Agent、Tool Gateway、Policy 和 Approval 的最小权限边界。

## M5 最小权限规则

- Agent 不直接访问文件系统、Git、subprocess、Docker、SSH 或远端部署入口。
- Platform API 是 Tool Gateway 的事务入口，负责写入 `tool_calls`、`approval_requests` 和 `event_logs`。
- Tool Gateway 只负责工具声明、参数校验、风险等级、审批拦截、策略执行和结果摘要，不直接写数据库。
- Tool Policy 统一处理路径边界、敏感文件、命令 denylist、环境变量白名单和超时上限。
- L0/L1/L2 可在本地受控边界内执行并审计；L3/L4 必须进入审批，M5 不提供自动补执行。

## 角色边界

|角色|允许能力|禁止能力|
|---|---|---|
|Requirement / Architect / Planner Agent|读取需求、生成结构化输出、申请工具调用|绕过 Tool Gateway 直接执行命令或写文件|
|Tool Gateway|校验参数、执行本地低风险工具、形成审计摘要|直接写数据库、直接审批、连接生产环境|
|Platform API Service|在事务内写 ToolCall、Approval、Event|在路由函数中直接执行业务工具|
|用户 / 审批人|批准或拒绝审批请求|在 M5 通过审批后自动触发远端动作|

## 后续扩展

M6 需要在保持本模型的基础上增加 Docker sandbox 权限、代码实现 Agent 的工具白名单和 PR/等价记录权限；M7 才接入远端部署审批恢复流程。
