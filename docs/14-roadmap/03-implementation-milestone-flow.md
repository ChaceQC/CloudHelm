# CloudHelm 总排期流程

> 来源：`云舵 CloudHelm 毕设设计书.md`、`docs/14-roadmap/00-graduation-plan.md`、`docs/15-detailed-design/00-mvp-scope-and-cutline.md`、`AGENTS.md`  
> 目的：按功能闭环先后将 CloudHelm 拆成 M0、M1、M2...，作为后续实现、验收和打钩更新的总流程。

## 1. 使用规则

- 本文件是项目总流程，不替代 `PROJECT_PLAN.md`。
- `PROJECT_PLAN.md` 只写当前或下一步要落实的详细计划，必须从本总流程中选取下一个未完成里程碑生成。
- 后续每个阶段的 `PROJECT_PLAN.md` 都必须达到 M1 计划的详细程度，至少包含参考文档、预检步骤、文件清单、任务拆分、命令示例、验证方式、打钩位置、完成判定和风险处理。
- 每完成一个可验证任务后，应先更新 `PROJECT_PROGRESS.md`，再在本文件中把对应复选框从 `[ ]` 改为 `[x]`。
- 当某个 M 阶段下的任务全部完成后，该阶段视为完成，并进入下一个 M 阶段。
- 若功能范围、顺序或验收标准变化，必须同步更新本文件、`AGENTS.md` 和 `PROJECT_PROGRESS.md`。

## 2. 总览

|阶段|主题|目标|依赖|
|---|---|---|---|
|M0|项目治理与排期基线|建立协作规范、进度记录、总排期和下一步计划机制|设计书、docs、AGENTS|
|M1|Monorepo 骨架与最小工程|创建源码目录、最小 API、最小控制台和共享契约|M0|
|M2|数据模型、API 与事件底座|实现 Project、Task、Requirement、Design、Event 基础数据流|M1|
|M3|控制台任务主流程|实现需求输入、任务看板、任务详情、事件流和审批入口|M2|
|M4|Agent 编排与规格化闭环|实现需求规格化、技术设计、任务拆分和状态机推进|M2、M3|
|M5|Tool Gateway 与本地工具层|实现工具统一入口、风险等级、审计、Repo/Sandbox/Git 工具|M4|
|M6|本地代码实现、测试与 PR 闭环|让 Agent 真实修改 sample repo、测试、审查并生成 PR|M5|
|M7|Ops Hub 常驻控制面、CI 与远端部署|Linux Ops Hub 持续推进精确 commit、两道审批、唯一 CI、通用项目契约和 staging/demo 部署|M6|
|M8|远端监控、告警与 SRE 分析|采集日志指标告警，生成 incident 分析和 runbook 建议|M7|
|M9|Desktop、用户/RBAC 与安全产品化|实现 Tauri、Local Runtime、SQLite/credential、离线同步、用户分层权限和平台安全加固|M7、M8|
|M10|跨平台发行与最终验收|完成 Windows/Linux 安装、Ops Hub 运维、独立/受管双路径、答辩证据和最终版本|M1-M9|

## 3. 里程碑任务

### M0 项目治理与排期基线

- [x] 完善 `AGENTS.md`，明确 UTF-8、注释、接口文档、完整实现、进度更新和安全规则。
- [x] 创建 `PROJECT_PROGRESS.md`，记录每次设计、实现、测试和部署调整。
- [x] 明确 `PROJECT_PLAN.md` 只用于下一步详细执行计划，不保存总项目规划。
- [x] 创建本总排期流程文档。
- [x] 更新 `docs/README.md` 和 `docs/14-roadmap/README.md`，加入本流程入口。
- [x] 根据本总流程生成 M1 的 `PROJECT_PLAN.md`。

完成判定：协作规则、进度记录、总排期和下一阶段计划都已存在。

### M1 Monorepo 骨架与最小工程

- [x] 创建 `apps/`、`modules/`、`packages/`、`infra/`、`examples/`、`tests/`、`informations/` 根目录。
- [x] 初始化 `apps/control-console` 最小 Tauri/React 或 React/TypeScript 控制台骨架。
- [x] 初始化 `modules/platform-api` 最小 FastAPI 工程，提供真实 `/health`。
- [x] 初始化 `packages/shared-contracts`，放置 Task 状态、事件 schema、工具风险等级等共享契约起点。
- [x] 创建根目录 `README.md`、`.gitignore`、`.env.example`。
- [x] 记录 M1 启动、检查或构建命令，不能只创建空目录。

完成判定：最小控制台、最小 API、共享契约、资料归档入口和基础配置存在，并能通过基础启动或检查。

### M2 数据模型、API 与事件底座

- [x] 实现 projects、tasks、requirement_specs、technical_designs、agent_runs、tool_calls、approval_requests、event_logs 基础表。
- [x] 建立 API、schemas、services、repositories、models 分层。
- [x] 实现 Project API 和 Task API。
- [x] 实现 Requirement / Design API。
- [x] 实现 Agent Run、Tool Call、Approval、Event Stream API。
- [x] 每次任务状态变化写入 `event_logs`。
- [x] 同步更新 `docs/08-api/` 和数据表文档。

完成判定：能通过真实 API 创建项目和任务，并持久化事件日志。

### M3 控制台任务主流程

- [x] 实现 Project Sidebar。
- [x] 实现 Task Board 和 Task Detail。
- [x] 实现需求输入表单，并调用真实 Task API。
- [x] 展示 Requirement Spec、Acceptance Criteria、Technical Design 的真实后端数据结构。
- [x] 接入事件流，展示 Agent Timeline、Tool Calls、Event Log。
- [x] 实现 Design Review Panel 和 Approval Panel 的基础交互。

完成判定：控制台能创建任务、查看任务状态变化和任务详情，不使用静态假数据冒充完成。

### M4 Agent 编排与规格化闭环

- [x] 实现 Orchestrator 状态机：Created -> Requirement -> Design -> Planning -> Waiting Approval。
- [x] 实现 Requirement Agent，输出需求规格和验收标准。
- [x] 实现 Architect Agent，输出 ADR、OpenAPI 草案、DB schema 草案和风险点。
- [x] 实现 Planner Agent，输出开发任务图和风险说明。
- [x] 定义并验证结构化输出 schema。
- [x] 控制台支持审批或要求修改需求/方案。
- [x] 实现每个 Task 唯一 root conversation，普通 Agent 跨 API 请求共享完整 ResponseItem 历史和同一 cache key。
- [x] 完成 Instructions v3、encrypted reasoning、工具 call/output、审批上下文和显式 subagent conversation 持久化/父子隔离原语（不含真实 child 执行调度）。
- [x] 使用 `gpt-5.6-sol` / `xhigh`、Codex User-Agent 和 HTTP SSE 通过真实五轮缓存与三角色审批完整流程。

完成判定：输入真实需求后，系统能在同一 Task 主会话中生成结构化需求、技术方案和开发计划，进入并完成审批；真实供应商 usage 能证明后续 turn 命中 Prompt Cache。

### M5 Tool Gateway 与本地工具层

- [x] 实现 Tool Gateway 参数校验、权限判断、风险等级、限流和审计记录。
- [x] 实现 Requirement Tool 和 Design Tool。
- [x] 实现 Repo Tool，支持真实读取和写入 worktree。
- [x] 实现 Sandbox Tool，支持本地受控目录命令执行、超时和 artifact 收集；
  M6 已评估并保留受控 subprocess，M7 前继续评估 Docker/远端执行隔离。
- [x] 实现 Git Tool，支持 diff、branch、commit。
- [x] 控制台展示 tool_calls 的工具名、参数摘要、风险等级、状态和输出摘要。

完成判定：Agent 工具调用必须经过 Tool Gateway，且 `tool_calls` 有完整记录。

### M6 本地代码实现、测试与 PR 闭环

- [x] 准备 `examples/sample-repo-python`，包含 FastAPI `/health`、`/metrics`、pytest 和 Dockerfile。
- [x] 实现 Scaffold Agent。
- [x] 实现 Coder Agent，真实修改 sample repo。
- [x] 实现 Tester Agent，真实运行 pytest 并生成测试报告。
- [x] 实现 Reviewer Agent，检查 diff 与验收标准。
- [x] 实现 Security Agent，默认运行 Bandit 与 pip-audit；Semgrep / Trivy
  保留为后续可配置扫描器和镜像门禁。
- [x] 创建 branch、commit、PR 或等价 PR record。
- [x] 控制台展示 diff、测试报告、安全扫描、审查结论和 PR 链接/记录。

完成判定：能从功能需求生成真实代码变更、测试报告、审查结论和 PR/等价记录。

### M7 Ops Hub 常驻控制面、CI 与远端部署

- [x] 完成 M7-0 细化设计、总体设计书/API/Data/Workflow/Testing 同步和官方资料归档。
- [x] 冻结 Desktop / Local Runtime / Linux Ops Hub / Remote Agent / 独立业务
  项目边界、三类存储、用户/RBAC 规划和 M7-M10 责任划分；本项仅代表文档完成。
- [x] 完成 M7-2A 数据底座：实现 ProjectRepositoryBinding、ReleaseCandidate、
  WorkflowJob 与资源绑定 Approval 的 migration、ORM、数据库约束、共享 OpenAPI
  和前端 Approval 类型；完成 downgrade/upgrade 往返、真实负约束和全量回归。
  本项不代表 RepositoryBinding/Candidate service/API 或 Workflow Engine 已完成。
- [ ] 实现 M7-2B server-controlled RepositoryProfile、Binding PUT/GET、
  ReleaseCandidate 原子创建、第一道 L2 Approval、binding 漂移失效和 Task-first
  并发门禁。
- [ ] 实现 CIRun、Deployment、ServiceInstance 数据与 migration。
- [ ] 实现 M7-2C Redis + Celery durable Workflow Engine，包括 dispatch、claim、
  lease、heartbeat、补投和 side-effect-aware stale reclaim。
- [ ] 建立 Linux `ops-hub` 最小 installation/bootstrap，包含 TLS ingress、
  Platform/Workers、PostgreSQL/Redis、Gitea/runner/registry、服务凭据、持久卷和
  最小备份；每套中心设施只执行一次，M7 不创建真实 user/device/session。
- [ ] 建立独立 Remote Target / Environment bootstrap，只安装 Docker/Compose、
  Remote Agent、采集器和 machine credential，并注册到既有 Ops Hub。
- [ ] 正常远端流程由服务端 WorkflowJob/worker 自动 continuation；`run-next`
  只保留调试、答辩逐步展示或人工恢复入口。
- [ ] 接入真实 Gitea/Remote operation resolver，使外部状态可收敛为 succeeded、
  failed、安全重排或 recovery_required。
- [x] 实现 Environment / RemoteTarget API、machine authentication 和
  Remote Agent online/offline/recovery 心跳。
- [ ] 建立固定版本的 Gitea Actions、act_runner 和 registry；CI 只执行
  test/security/build/artifact，workflow 不监听 push，输出不可变 OCI digest。
- [ ] 实现严格空对象的 candidate POST，绑定最新版 PullRequestRecord、完整
  commit、binding snapshot/hash、candidate ref 和 request hash，并原子创建第一道
  L2 Approval；`remote-deployment/start` 不重复创建审批，审批前禁止 push 和 CI。
- [ ] 审批通过后发布受控 ref，复核 ref 指向精确 commit，并执行唯一
  `workflow_dispatch`。
- [ ] 准备远端 Linux staging/demo 主机和 Docker Compose 环境。
- [ ] 实现 Remote Agent operation store、Compose policy、实际 digest 复核、
  服务状态、受限日志和 diagnostics。
- [ ] 实现 Release / Deploy Agent 的 ReleasePlan、第二道部署审批、部署执行和
  健康检查；实现者不得自批。
- [ ] 实现 `cloudhelm.project.yaml`、`cloudhelm.env.schema.json`、共享 JSON
  Schema、manifest hash 和固定通用安全 renderer；移除项目专用模板依赖。
- [ ] 实现 Deployment Controller 的通用 renderer、TLS client 和幂等 operation
  查询。
- [ ] 实现 CI Tool、Deploy Tool 和 Remote Control Tool 的固定 schema、风险、
  审批恢复和审计；M7 Remote Control Tool 只提供 status、受限 logs 和固定
  diagnostics。
- [ ] 使用固定 OCI digest、远端 env profile / credential store 和通用 rendered
  Compose 执行真实远端部署；M7 不自动回滚。
- [ ] 扩展 Orchestrator、Workflow Engine 与 SSE，使服务端自动推进并在成功后
  进入 Monitoring。
- [ ] 控制台展示 CI、ReleasePlan、两道审批、部署版本、Remote Agent、服务健康
  和 M7 受限日志。
- [ ] 完成真实 Gitea CI + registry + Linux staging E2E，并保存 manifest、
  Approval、DeploymentResult、health、timeline 和清理证据。
- [ ] 验证 Desktop 退出后无需新审批的流程继续、Redis 重启由 PostgreSQL 补投、
  业务项目卸载不影响 Ops Hub。
- [ ] 验证删除两个 CloudHelm Adapter 后业务项目 standalone 运行，同一 commit
  standalone/managed 核心行为一致。

M7 不包含 remote session、WebSocket terminal、服务重启、metrics、Loki
集中日志、告警分析或自动回滚。metrics、集中日志、告警和 runbook proposal
进入 M8；交互式远程接管属于 M8 之后的增强版。

完成判定：Linux Ops Hub 在 Desktop 退出后持续运行；精确 M6 commit 经 release
candidate 审批、唯一真实 CI、不可变 digest、ReleasePlan 和 L3 deployment
approval 后只执行一次远端 operation；示例项目在 Linux staging/demo `/health`
成功并进入 Monitoring，且 standalone/managed 边界和完整证据可追溯。

### M8 远端监控、告警与 SRE 分析

- [ ] 部署或接入 Prometheus、Loki、Alertmanager 或设计书允许的等价真实采集链路。
- [ ] 实现 Monitoring Tool：query_metrics、search_logs、list_alerts、get_recent_deployments。
- [ ] 实现 ProjectAlert / Incident 数据流。
- [ ] 实现 SRE Agent 告警分析。
- [ ] 生成 runbook proposal。
- [ ] 对重启服务、回滚版本等动作接入审批。
- [ ] 验证 Desktop 退出后监控、告警和 SRE 分析继续，重连后事件可补齐。

完成判定：远端异常能触发告警或 incident，SRE Agent 能基于日志、指标和部署记录给出分析与建议。

### M9 Desktop、用户/RBAC 与安全产品化

- [ ] 将 `apps/control-console` 接入 Tauri v2，建立 Windows/Linux Desktop 壳。
- [ ] 实现 `modules/local-runtime` sidecar、本机 workspace allowlist、device
  identity、Git/test/tool 通道。
- [ ] 实现运行时 Ops Hub server profile，不再只依赖编译时
  `VITE_CLOUDHELM_API_BASE_URL`。
- [ ] 实现 Desktop SQLite 独立 migration，只保存 profile、UI 设置、草稿、
  cache 和 event sequence。
- [ ] 将 access/refresh token、Ed25519 device private key 保存到 OS credential
  store/Stronghold，完成日志/SQLite/crash report 扫描。
- [ ] 实现 users、devices、device_pairing_challenges、user_sessions、
  session_refresh_tokens、invitations、roles、permissions、role_permissions、
  role_bindings 和 permission version migration/API。
- [ ] 实现一次性 identity bootstrap token、首个 `system_owner` 和首个 Desktop
  device/session；第二次 bootstrap 稳定拒绝。
- [ ] 实现 `system_owner`、`project_developer`、`project_reviewer`、
  `environment_operator`、`deployment_approver`、`auditor`、`viewer` 精确
  permission/scope。
- [ ] 实现 effective permissions、resource `allowed_actions`、最后 owner
  不变量、refresh rotation/reuse 检测、Desktop/Local Runtime challenge proof、
  短期 device session 和职责分离。
- [ ] Desktop 按权限控制 route/button/shortcut/batch action；直接 HTTP 请求由
  API 重新鉴权。
- [ ] TechnicalDesign 保存当前版本的 user/AgentRun 修改者与 content hash，设计
  审批绑定 version/hash 并拒绝最后修改者或其 AgentRun 发起者自批。
- [ ] EventLog 增加 sequence/stream kind/project/aggregate/version/schema、
  user/device/session actor 与 subject user，实现用户控制流、project snapshot +
  incremental + SSE live tail 和 cursor reset。
- [ ] 完善 L3/L4 Approval、Semgrep/Trivy、audit/event/tool trace、平台指标、
  token/cost 与公网暴露面检查。

完成判定：不同用户在同一 Desktop/Ops Hub 中拥有正确功能，API 不能被绕过，
自批与 scope 越权稳定拒绝；Desktop 离线重连无事件丢失，凭据不进入 SQLite。

### M10 跨平台发行与最终验收

- [ ] 生成并验证 Windows NSIS setup `.exe` 与安装后的 `CloudHelm.exe`。
- [ ] 生成并验证 Linux AppImage 与 `.deb`；`.rpm` 可选。
- [ ] 完成安装、升级、卸载、checksum、SBOM、代码签名和签名 updater 验收。
- [ ] 在无 Docker/PostgreSQL/Redis 的干净 Windows/Linux 环境完成 Desktop smoke。
- [ ] 完成 Ops Hub bootstrap、upgrade、backup/restore、uninstall 和版本兼容检查。
- [ ] 完成 standalone/managed 双路径、Adapter 删除、Compose 生命周期隔离和最终
  真实 E2E。
- [ ] 编写完整 E2E 演示脚本。
- [ ] 按 `docs/15-detailed-design/07-testing-acceptance-matrix.md` 执行验收。
- [ ] 归档 requirement、design、diff、test report、security report、deployment result、incident analysis。
- [ ] 准备截图、录屏、测试报告和答辩讲解材料。
- [ ] 检查设计书与验收矩阵更新后的全部 MVP 验收点。
- [ ] 标记最终版本，例如 `v1.0.0`。

完成判定：Windows/Linux Desktop、Linux Ops Hub、用户/RBAC、CI/部署/监控、
standalone/managed 双路径和完整 E2E 均可复现，最终版本可用于答辩。

## 4. 当前下一步

当前 M0-M6 已完成，M1-M6 核验修复版本为 `0.5.1`。M7-0 设计闭环、
M7-1 `Environment + RemoteTarget + machine-auth heartbeat` 和 M7-2A 数据底座
已经完成；M7-2A 已通过数据库往返、真实负约束、OpenAPI 精确同步和 Platform
API 全量回归。

当前执行指针为 M7-2B：实现 RepositoryProfile/Binding API、ReleaseCandidate
原子创建、第一道审批、漂移失效和 Task-first 并发门禁；随后进入 M7-2C durable
Workflow Engine。

Ubuntu WSL 原生 Docker 当前只形成 PostgreSQL/Redis 开发依赖基线，对应
IT-031A；正式 `ops-hub` profile、IT-031B 预演、真实 CI、通用 renderer、
远端部署和干净 Linux IT-031 验收仍未完成。项目版本继续保持 `0.5.1`。
