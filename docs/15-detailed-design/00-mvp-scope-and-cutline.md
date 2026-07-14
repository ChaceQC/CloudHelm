# MVP 范围细化与裁剪线

> 来源：设计书 5.2、16、17、18、22 章  
> 目的：把 CloudHelm 的毕设范围压缩到可实现、可演示、可验收的闭环。

## 0. M1-M6 落地状态

M1-M6 已完成本地代码闭环：Project/Task、Requirement/Design/Plan、审批、
受控 sample workspace 修改、pytest/JUnit、Review、Bandit/pip-audit、
branch/commit 和本地等价 PR record。

当前 Orchestrator 是 Python 显式状态机；Tool Gateway 的“sandbox”是 allowlist
本地目录与受控 `subprocess`。LangGraph、独立 Docker sandbox、真实远端
PR/CI、Release / Deploy、Remote Agent、监控与 SRE 仍是后续 MVP 阶段目标，
不能写成 M1-M6 已交付能力。

M6 的失败恢复覆盖能够进入应用错误处理的异常和已有幂等证据；进程 hard crash
后的 active 记录 lease/stale reclaim 尚未实现，也不属于 M1-M6 完成判定。

## 0.1 M7 固定裁剪线

M7 只实现一台或少量已受控 **Linux staging/demo** 目标上的 Remote Agent +
Docker Compose 部署闭环，固定语义如下：

- 第一道人工作为 release candidate approval，绑定 M6 PullRequestRecord、精确
  commit、受控 Gitea candidate ref 和 request hash；审批前不允许 push candidate
  ref 或触发 CI。
- Gitea workflow 不监听 push，只能由 Platform API 对固定 workflow、精确 ref
  和结构化 inputs 发起唯一 `workflow_dispatch`。CI 只执行 test、security、
  build 和 artifact publish，禁止 SSH、Compose 上线、Remote Agent 调用、服务
  重启或其他部署动作。
- CI manifest、PullRequestRecord、ReleasePlan 和 Deployment 必须绑定同一
  commit 与不可变 OCI index/platform manifest digest，禁止只凭可变 tag 部署。
- 第二道人工作为 deployment approval，绑定 CIRun、manifest、digest、
  ReleasePlan、Environment、RemoteTarget 和 request hash；审批事务本身不触发
  远端副作用，审批后仍需显式推进。
- M7 不执行服务 restart 或 rollback；健康失败只保存 rollback candidate /
  rollback request。production、Kubernetes、RemoteSession/交互终端均为增强版。
- 部署健康后写 `MonitoringRegistered` 并把 Task 交接到 `Monitoring`；真实
  Prometheus/Loki/Alertmanager、告警和 SRE 闭环由 M8 完成，M7 不提前写 `Done`。

## 1. MVP 一句话目标

MVP 只追求一个完整闭环：

```text
开发者输入功能目标
  -> Requirement / Architect / Planner 生成结构化需求和方案
  -> Coder / Tester / Reviewer 在受控本地 workspace 完成代码修改和验证
  -> 生成 branch / commit / PR 或等价 PR 记录
  -> release candidate 审批后以唯一 workflow_dispatch 生成不可变 CI 制品
  -> deployment 审批后由 Release / Deploy Agent 经 Remote Agent 部署到远端 staging/demo
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
|工具调用|Agent 通过 Tool Gateway 调用当前阶段已注册工具；deploy/monitor 在后续阶段接入|`tool_calls` 记录|
|本地隔离开发|M6 在 Task 独立 workspace + 受控 subprocess 中读写代码、运行测试；最终目标为 Docker sandbox|diff、测试报告、命令输出|
|Git/PR 闭环|能创建 branch、commit、PR；如果没有真实 Git 服务，至少生成等价 PR record|Gitea PR 或 `pull_request_record`|
|Agent 化远端部署|M7 经 release candidate 与 deployment 两道审批，把不可变 OCI digest 部署到 Linux staging/demo Remote Agent|`release_candidates`、`ci_runs`、`deployments`、远端 `/health`、Release / Deploy Agent 运行记录|
|远端状态回传|M7 Remote Agent 回传心跳、服务状态和受限直读日志；健康后写 `MonitoringRegistered` 交接 M8|控制台远端状态页、受限日志流、Task `Monitoring`|
|监控告警|M8 接入真实 Prometheus/Loki 或经文档确认的成熟等价方案，产生远端业务告警|`project_alerts` / Incident|
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
|服务 restart / rollback|M7 只生成 rollback candidate/request，不执行 restart 或 rollback；执行能力留到增强版并重新走独立审批|
|production 部署|M7 只部署 staging/demo，production 配置、迁移和回滚均为增强版|
|RemoteSession / 交互终端|M7 只提供固定 diagnostics 和受限直读日志；会话、任意命令和终端接管为增强版|
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

- 控制台原型（M6 为 React 浏览器控制台，完整 Tauri 壳在后续演示阶段完成）。
- FastAPI 平台服务。
- 编排器（M1-M6 为显式状态机；只有后续异步图执行确有需要时再引入
  LangGraph，不把框架名作为完成条件）。
- 至少 5 个 Agent：Requirement、Architect、Coder、Tester、Reviewer。
- 至少 7 个工具组：Requirement、Design、Repo、Sandbox、Git、Deploy、Monitoring。
- PostgreSQL schema 和迁移。
- Docker Compose 本地依赖环境；独立 Docker sandbox 按后续隔离设计验收。
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
|部署闭环|M6 精确 commit 经 release candidate 审批、唯一 `workflow_dispatch`、不可变制品和 deployment 审批后，由 Release / Deploy Agent 部署到 Linux demo|
|监控运维|远端异常能触发告警并生成 SRE 分析|
|安全观测|审批、审计、指标、日志、trace 有基本展示|
