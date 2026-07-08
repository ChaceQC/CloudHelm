# MVP 范围细化与裁剪线

> 来源：设计书 5.2、16、17、18、22 章  
> 目的：把 CloudHelm 的毕设范围压缩到可实现、可演示、可验收的闭环。

## 1. MVP 一句话目标

MVP 只追求一个完整闭环：

```text
开发者输入功能目标
  -> Requirement / Architect / Planner 生成结构化需求和方案
  -> Coder / Tester / Reviewer 在本地 sandbox 完成代码修改和验证
  -> 生成 branch / commit / PR 或等价 PR 记录
  -> Release / Deploy Agent 审批后部署示例业务项目到远端 staging/demo
  -> 回传远端服务状态、日志、指标、告警
  -> SRE Agent 输出 incident 分析和 runbook 建议
```

## 2. 必做能力

|能力|MVP 要求|验收证据|
|---|---|---|
|项目与任务管理|能创建 Project、Task，查看任务详情和时间线|控制台截图、API 返回、`tasks` / `event_logs` 记录|
|需求规格化|Requirement Agent 输出 `requirement_spec` 和 `acceptance_criteria`|结构化 JSON、Markdown 展示|
|技术设计|Architect Agent 输出 ADR、OpenAPI 草案、DB schema 草案、风险说明|`technical_designs` 记录、设计审查页面|
|任务编排|Orchestrator 按状态机推进任务，支持失败重试、暂停、审批|状态流转日志|
|工具调用|Agent 通过 Tool Gateway 调用 repo、sandbox、git、deploy、monitor 等工具|`tool_calls` 记录|
|本地隔离开发|在 Docker sandbox / worktree 中读写代码、运行测试|diff、测试报告、命令输出|
|Git/PR 闭环|能创建 branch、commit、PR；如果没有真实 Git 服务，至少生成等价 PR record|Gitea PR 或 `pull_request_record`|
|Agent 化远端部署|Release / Deploy Agent 部署一个 sample repo 到远端 staging/demo|`deployments` 记录、远端 `/health` 成功、Release / Deploy Agent 运行记录|
|远端状态回传|Remote Agent 回传心跳、服务状态、日志|控制台远端状态页、日志流|
|监控告警|Prometheus/Loki 或替代 mock 能产生远端业务告警|`project_alerts` / Incident|
|SRE 分析|SRE Agent 基于日志、指标、部署记录输出分析和 runbook|incident analysis、runbook proposal|
|审计与审批|L3/L4 动作进入审批，工具调用有审计|`approval_requests`、`tool_calls`、`event_logs`|

## 3. 明确不做或只做设计说明的能力

|能力|MVP 裁剪线|
|---|---|
|多租户与组织权限|不做完整 RBAC，只保留单用户/演示用户和角色化工具权限|
|生产级 Kubernetes|只保留设计文档和接口预留，MVP 用 Docker Compose|
|Argo CD / Flux GitOps|只做后续扩展说明，不实现真实同步控制器|
|OpenBao / 动态密钥|只做本地加密配置或环境变量引用，生产密钥管理作为扩展|
|复杂成本计费|只记录 token / cost 字段，不做账单系统|
|插件市场|只保留 Tool Server 注册接口，不实现市场|
|自动生产回滚|只允许生成回滚建议，真实生产回滚必须人工审批或不演示|
|多云资源创建|不接 Terraform/OpenTofu，远端主机手动准备|

## 4. 演示项目建议

MVP 建议只准备一个示例业务项目：

```text
examples/sample-repo-python/
├── backend FastAPI
│   ├── /health
│   ├── /metrics
│   ├── 初始缺少 auth/profile
│   └── pytest
├── frontend React，可选
├── Dockerfile
├── docker-compose.yml
└── demo-issues/
```

推荐演示需求：

```text
为示例项目增加用户注册、登录和个人资料接口；
要求使用 FastAPI、PostgreSQL、JWT；
需要 pytest 覆盖注册、登录、读取资料；
部署到 staging 后能通过 /health，并能在控制台查看日志与指标。
```

## 5. 交付物边界

### 软件交付物

- Tauri 控制台原型。
- FastAPI 平台服务。
- LangGraph 编排器。
- 至少 5 个 Agent：Requirement、Architect、Coder、Tester、Reviewer。
- 至少 7 个工具组：Requirement、Design、Repo、Sandbox、Git、Deploy、Monitoring。
- PostgreSQL schema 和迁移。
- Docker Compose 本地开发环境。
- Remote Agent 或等价远端采集服务。

### 文档交付物

- 系统需求与总体架构。
- 模块设计与接口设计。
- Agent 与 Tool Gateway 设计。
- 数据库设计。
- 部署与测试说明。
- 演示脚本与验收矩阵。

## 6. 阶段完成判定

|阶段|完成判定|
|---|---|
|基础平台|控制台能创建任务，后端能持久化，事件流能展示|
|Agent 编排|需求到设计到计划能自动推进，失败可见|
|工具系统|工具调用经过 Gateway，风险等级和审计可见|
|代码闭环|能对 sample repo 生成 diff、测试报告、PR|
|部署闭环|PR 合并或等价动作后，Release / Deploy Agent 能部署到远端 demo|
|监控运维|远端异常能触发告警并生成 SRE 分析|
|安全观测|审批、审计、指标、日志、trace 有基本展示|
