# 测试与验收矩阵细化

> 来源：设计书 17、22 章  
> 目的：把 MVP 验收标准转成可执行测试项和答辩演示证据。

## 0. 当前验收边界

- M1-M6 当前闭环止于：Project/Task → Requirement/Design/Plan → 真实本地
  workspace 文件修改 → pytest/JUnit → Review → Bandit/pip-audit → branch/commit
  → `provider=local` 的等价 PR record。
- M7-1 的 Environment、profile-only RemoteTarget 和 machine-auth heartbeat 已
  实现；M7-2B1/B2 的 RepositoryBinding、Candidate API、第一道审批和无副作用
  reconcile job 也已实现。M7-2C 已交付 PostgreSQL 权威的 Redis/Celery
  dispatcher、worker claim/lease/heartbeat、retry、补投、stale reclaim 和真实
  reconcile handler。M7-2D 已交付 CIRun、Deployment、ServiceInstance 数据、
  repository、严格共享契约和第二道 L3 Approval 数据库组合门禁。受控 candidate
  ref 发布、真实 CI、Release / Deploy 和 M8
  远端监控/SRE 尚未进入完成判定；相应测试项仍标记为“规划”，不得用静态数据或
  假返回冒充。
- M6 的 `sandbox.*` 使用 allowlist 本地目录和受控 `subprocess`，不是 Docker
  sandbox。Docker CPU/内存/PID/网络隔离属于后续边界。

## 1. M1-M6 自动化测试矩阵

|模块|黑盒/集成重点|白盒重点|当前工具|
|---|---|---|---|
|platform-api|状态码、响应结构、错误码、`trace_id`、分页、状态流转、Artifact/PR API|service/repository、事务、事件、副作用幂等、数据库迁移与并发门禁|pytest + TestClient + PostgreSQL|
|orchestrator|M4/M6 正常路径、等待审批、返工与终态拒绝|显式状态机合法/非法迁移、回退路径|pytest|
|agent-runtime|八类结构化输出、受控 auth/profile recipe、HTTP SSE Responses|风险不可降级、重试、完整 ResponseItem、工具 call/output 配对、逐请求 usage|pytest|
|tool-gateway|Repo/Scaffold/Test/Security/Git 工具结果、审批拦截|Pydantic 参数校验、角色 allowlist、工作区边界、命令 profile、超时、脱敏与审计|pytest|
|control-console|Task 切换、审批动作、SSE 重连/去重、M6 证据展示|旧请求/旧 SSE/旧 timer 门禁、Timeline 稳定排序、数据转换|Node test + TypeScript build|
|shared-contracts|FastAPI OpenAPI 与共享 YAML 精确一致|全部 JSON Schema 可加载，工具/Agent/Artifact 字段与实现一致|pytest + PyYAML + jsonschema|
|sample-repo-python|`/health`、`/metrics`、auth/profile 验收、pytest/JUnit|路由、存储、认证错误分支、Bandit 与 pip-audit 结果|pytest + Bandit + pip-audit|

### 1.1 M7-M10 已实现与规划测试矩阵

|模块|状态与测试项|工具|
|---|---|---|
|sandbox-runner|容器创建、只读挂载、命令超时、CPU/内存/PID/网络限制、清理|pytest + Docker|
|workflow-engine|M7-2C 已实现 `none` job 的 PostgreSQL dispatch/claim/lease/heartbeat/retry/reclaim、重复 delivery、Redis restart 补投和 prefork hard-crash；外部 operation resolver/unknown 恢复仍规划|pytest + PostgreSQL + WSL Redis/Celery prefork|
|deployment-controller|ReleasePlan、不可变 digest、Compose 渲染、健康检查、rollback candidate/request 与幂等；不执行 restart/rollback|pytest + Docker Compose|
|remote-agent|Linux staging/demo heartbeat、capabilities、service status、受限日志、operation 幂等和断线恢复；无 RemoteSession/restart/rollback|pytest + 远端 fixture|
|monitoring-collector|Prometheus/Loki 查询、告警转换、Incident 事件|pytest + 真实观测栈|
|desktop|Tauri、server profile、SQLite/credential store、sequence sync、角色化 UI、Windows/Linux 安装升级|Rust/Node test + Playwright + clean VM|
|identity-access|bootstrap、login/refresh/logout、device/session、role/scope、resource capabilities、SoD、审计|pytest + PostgreSQL + Desktop E2E|
|project portability|adapter schema、通用 renderer、standalone/managed 双路径、生命周期隔离|JSON Schema + Compose + Linux E2E|

## 2. 集成测试矩阵

|编号|阶段|场景|步骤|通过标准|
|---|---|---|---|---|
|IT-001|M2 已实现|创建项目|`POST /api/projects`|返回 `201`；`projects` 与 `ProjectCreated` 有记录|
|IT-002|M2 已实现|创建任务|`POST /api/tasks`|返回 `201`；初始 `created / Created`；写入 `TaskCreated`，不自动启动编排|
|IT-003|M4 已实现|需求规格化|start 后运行 Requirement|生成当前 Task 的 RequirementSpec 和 AC|
|IT-004|M4 已实现|技术设计|运行 Architect|受控 auth/profile recipe 生成对应 TechnicalDesign、OpenAPI、DB schema|
|IT-005|M4 已实现|设计与计划审批|批准当前产物后继续推进|只接受当前 AgentRun 创建的最新版产物；过期审批返回稳定 `409`|
|IT-006|M6 已实现|代码修改|Coder 按 recipe 调用 Repo Tool|Task workspace 产生非空、未截断且 changed files 一致的真实 patch|
|IT-007|M6 已实现|测试运行|Tester 调用 `test.run_pytest`|真实退出码和 JUnit 统计一致，生成 TestReport/JUnit Artifact|
|IT-008|M6 已实现|代码审查|Reviewer 读取完整、未截断的安全投影 diff、changed files 与 AC|缺少、截断或路径不一致时返回 `blocked`；领域必需路径/marker 缺失时返回 `changes_requested`；raw patch 只用于 Artifact/Git 门禁，证据充分才生成通过的 ReviewReport|
|IT-009|M6 已实现|安全扫描|Security 调用 Bandit 与 pip-audit|区分 finding、依赖漏洞、工具/网络基础设施失败并生成 SecurityReport|
|IT-010|M6 已实现|本地 PR 收尾|Git Tool 创建 branch/commit/format patch|生成可应用 patch、commit 和 `provider=local`、`url=null` 的等价 PR record|
|IT-017|M4-M6 已实现|Task 主会话与缓存证据|连续运行普通 Agent|同一 root conversation/cache key；turn 有序；逐请求 usage 可审计，命中只依据供应商 usage|
|IT-018|M4-M6 会话/权限原语已实现；执行调度后续|显式 child conversation 持久化与隔离|running Task/AgentRun 调用内部唯一 spawn 入口；顺序与并发触发 active 上限；尝试暂停后 spawn、父 child 提前结束、遗留写角色、跨 Task root、终态 child、递归越权和策略漂移重放|只新增独立 child；默认拒绝 depth>1 和第 7 个 active child；并发配额不超限；parent/role/fork/status 正确；Tool Gateway 强制 active lineage 工具交集并审计拒绝；完成必须叶子优先且无 active AgentRun；父线程只收到非空、脱敏、≤4000 字符的最终通知；不把真实 child provider 执行、wait-all、steer/queue 或 thread UI 写成已交付|
|IT-019|M2-M6 已实现|测试数据库隔离|并行启动两个 Platform API pytest 会话|分别创建 `cloudhelm_test_<pid>_<uuid>`，均不重置开发库，结束后删除临时库|
|IT-020|M4 已实现|重复推进门禁|两个调用基于同一 `expected_phase` 请求 start/run-next|Task 行锁串行化；阶段已变化的请求返回 `409 orchestration_phase_changed`|
|IT-011|M7-2B2 已实现|Release candidate 审批|`POST /api/tasks/{task_id}/release-candidate` 请求 `{}`，随后处理 L2 Approval|Candidate、Approval 与内部 reconcile job 同事务创建；首次 `201`、幂等 `200`；PR、commit、binding snapshot/hash、受控 ref、幂等键和 request hash 均由服务端派生；`requested_by_agent_run_id` 固定为 PR creator；缺 creator、额外字段、通用 Approval 保留 action、自批、过期/hash/PR/Binding 漂移均被稳定拒绝；审批前无 push/CI/外部副作用；并发锁等待时间不早于记录创建时间|
|IT-011D|M7-2D 已实现|CI/部署数据底座|在 WSL PostgreSQL 执行三表合法状态、SQL 三值逻辑、JSON literal null、敏感 health key/raw log、userinfo/多重 `@`、FK、部分唯一键、分页、真实 `FOR UPDATE`、`create_many` 整批回滚、七组并发竞争和 Alembic 往返|`20260716_0009`、ORM、repository、Pydantic/JSON Schema 属性与可表达生命周期精确一致；running/passed CIRun 具有 run identity；rollback request 具有完整审批/operation/health/引用；第二道 Approval 固定 `approve_deployment + deployment + L3`；定向 `75 passed`、Platform API `407 passed, 1 skipped`、独立临时库 `0008 -> head -> 0008 -> head/check`；无新增未来 API/事件/外部副作用|
|IT-012|M7 规划|真实 CI 与不可变制品|candidate 发布后对固定 workflow/ref 发起唯一 `workflow_dispatch`|workflow 不监听 push；同一 candidate 只有一个有效 run；run/job/commit/JUnit/security/SBOM/scan/OCI digest 可追溯，CI 无 SSH/Compose/Remote Agent/restart/部署命令|
|IT-021|M7-1 已实现|Remote Agent machine heartbeat|对受控 profile 注册的 Linux target 执行合法、跨 target、过期、撤销、scope、顺序/并发重放、超大 body、fingerprint 漂移和新旧 key 心跳|online/offline/recovery 正确；nonce 覆盖完整时间窗；credential/完整 endpoint/原始 validation input 不泄露；fingerprint/capabilities 可审计；周期离线 worker 与项目级 SSE 仍属后续 M7|
|IT-022|M7 规划|部署审批与单次恢复|Release Agent 请求 staging，审批提交后并发 worker/重复消息自动恢复|Approval L3 绑定 ReleasePlan/digest/target/hash；过期/已消费/hash 漂移拒绝；PostgreSQL claim 保证只执行一次 operation；`run-next` 仅人工恢复|
|IT-023|M7-2C `none` 已实现；external 规划|worker hard-crash 恢复|真实 prefork worker claim `release_candidate_reconcile` 后 SIGKILL 进程组并等待 lease 过期；后续外部 handler 还需查询同一 operation|`none` job 安全回 pending 且 attempt 不重复；未来 external unknown 必须进入 recovery_required，不盲目重放|
|IT-024|M7 规划|Agent 化远端部署|第二道审批后调用 Controller/Linux Remote Agent|危险 Compose 拒绝；config/pull/RepoDigests/up/health 真实执行，生成 DeploymentResult/ServiceInstance；不执行 restart/rollback|
|IT-025|M7 规划|受限远端日志|控制台读取 Remote Agent service logs|限制时间、行数、字节并脱敏；不提供自由 query/终端|
|IT-026|M7 规划|真实远端 E2E|精确 commit 从 Gitea CI 部署到 Linux staging|DeploymentHealthy、MonitoringRegistered、Task=Monitoring、证据和清理记录完整|
|IT-027|M7 规划|健康失败与回滚边界|制造 `/health` 失败并请求 rollback|只保存 DeploymentUnhealthy、rollback candidate/request；无 restart/rollback operation|
|IT-028|M7 规划|增强能力裁剪|尝试创建 production、Kubernetes target、RemoteSession 或终端|M7 API/schema/UI 不暴露对应生产入口，能力保持增强版|
|IT-013|M8 规划|集中日志查询|控制台通过 Loki 查询服务日志|返回按 project/environment/service 聚合的远端业务日志|
|IT-014|M8 规划|指标查询|查询 service_up/error_rate|返回真实指标|
|IT-015|M8 规划|告警处理|触发服务不可用|ProjectAlertFired 和 Incident|
|IT-016|M8 规划|SRE 分析|触发 SRE Agent|生成 IncidentAnalysis 和 RunbookProposal|
|IT-029|M7 规划|Desktop 退出后 continuation|提交无需新审批的 CI/部署步骤后退出客户端|Ops Hub worker 继续，EventLog/WorkflowJob/heartbeat 更新；到审批 gate 后持久等待|
|IT-030|M7-2C 已实现|Redis 重启补投|使用自动创建/删除的 `127.0.0.1:16380/15` 隔离 Redis，在故障期间创建 pending WorkflowJob，恢复后运行真实 prefork worker|PostgreSQL durable dispatcher 补投；job 只 claim 一次并 succeeded；共享开发 Redis 不被 flush/stop|
|IT-031|M7/M10 规划|Ops Hub installation 生命周期|在干净 Linux 安装/升级/备份/恢复/卸载中心设施，并部署/卸载业务项目|每套中心设施只 bootstrap 一次；Ops Hub/审计保留，业务 volume 与平台 volume 不互删，PostgreSQL 可恢复|
|IT-031A|M7 开发基线|WSL 原生 Docker 依赖基线|在 Ubuntu 24.04 WSL2 中执行发行版、Docker daemon、Compose、用户权限和仓库挂载预检；连续执行两次 keepalive 启动；仅启动 `docker-compose.dev.yml` 的 PostgreSQL/Redis；等待至少 60 秒后从 Windows/WSL 两侧检查并运行 Platform API 回归|仅存在一个 keepalive；发行版保持 Running；PostgreSQL healthy；Redis PONG；Windows `15432` 可达；Platform API 回归通过；发行版路径和 named-volume 隔离模型有记录；本项只证明 `desktop-dev` 依赖基线，不代表 Ops Hub profile 完成|
|IT-031B|M7 规划|WSL 最小 Ops Hub profile 预演|`infra/ops-hub` profile 实现后，以独立 Compose project 在 WSL 启动 Platform、worker、PostgreSQL、Redis 和最小配套组件；关闭发起请求的客户端并验证 continuation、审批等待、heartbeat 和 Redis 重启补投|`/health`、`/ready`、worker heartbeat、WorkflowJob 和 EventLog 证据完整；客户端退出后无需新审批的步骤继续；该 WSL 预演不替代 IT-031 的干净 Linux TLS、bootstrap、备份恢复和卸载验收|
|IT-032|M7/M10 规划|Adapter 删除与 standalone|删除 `cloudhelm.project.yaml`、`cloudhelm.env.schema.json` 后按 README 构建/启动|业务项目 health、测试、数据保留均通过且不访问 CloudHelm|
|IT-033|M7 规划|通用 renderer|同一 project schema 渲染 managed Compose，并输入 privileged/host network/socket/越界 mount|合法 manifest 使用固定 digest；危险配置稳定拒绝；无项目专用模板|
|IT-034|M10 规划|同 commit 双路径|同一 commit 分别 standalone 与 managed 部署|API/health/配置/持久化核心行为一致，证据链关联同一 commit/manifest hash|
|IT-035|M9 规划|用户/RBAC|Developer、Reviewer、Operator、Approver、Auditor、Viewer 使用相同 Desktop/API；分别创建 system/project/environment binding|页面/按钮符合 `(role,scope)`；environment binding 只能读取直接关联的脱敏 Project/Task/CI 摘要，独立详情 API 返回 403；System Owner 也不能自批|
|IT-036|M9 规划|Auth/session 安全|bootstrap、refresh rotation、旧 token 重用、禁用用户、撤销 device/binding|最后 owner 不变量成立；token family 撤销；permission version 与审计事件正确|
|IT-037|M9 规划|Desktop 离线 sequence|长时间断线、管理员撤权、事件保留期内/外重连；actor 与受影响 user 不同|security/project snapshot watermark + incremental + SSE 无丢失/重复/旧覆盖；`/api/me` 只按 subject user；游标按 Ops Hub/user/stream/scope 分区；过期游标重建；高风险 intent 不自动重放|
|IT-038|M10 规划|Windows/Linux 安装|干净 Windows 11 安装 NSIS；Linux 运行 AppImage/安装 `.deb`|无 Docker/PostgreSQL/Redis 前置；登录、SQLite、credential、sidecar、升级/卸载通过|
|IT-039|M9/M10 规划|凭据边界|登录、crash、日志、SQLite/Artifact 扫描|access/refresh token、device private key、machine secret 均不出现在 SQLite、日志、crash report 或普通 API|
|IT-040|M7/M10 规划|Remote Target bootstrap 生命周期|在另一台干净 Linux 目标安装 Docker/Compose、Remote Agent、采集器和 machine credential，并注册既有 Ops Hub；同机 demo 再执行一次|目标安装不创建 Platform/PostgreSQL/Redis/用户体系；两条 bootstrap 的 manifest、credential、数据目录和卸载互不影响|
|IT-041|M9 规划|Desktop/Local Runtime device|新/已有/revoked Desktop 登录；Local Runtime pairing/session challenge 正常、过期、重放、错误 proof、失败超限和撤销|Desktop/Local Runtime 均使用 Ed25519 proof，服务端只存 public key；revoked public id 不原地恢复；Local Runtime 短期 token 无 refresh，撤销后调用失效|
|IT-042|M9 规划|Design 职责分离|人类修改、Agent 重写、version/hash 漂移和不同 reviewer 审批|审批绑定 design id/version/content hash；最后修改者或 AgentRun 人类发起者返回 403；漂移返回 409；其他 reviewer 可按 scope 决定|

## 2.1 M4 conversation/cache 专项通过标准

- 白盒前缀：第 N+1 次 Responses `input` 的开头必须严格等于此前已提交的完整
  ResponseItem 历史，包含 developer/user、assistant final answer、返回的
  `reasoning.encrypted_content`、工具 call/output 和审批上下文。
- 稳定前缀：Base Instructions、`cloudhelm_agent_output_v1`、model、reasoning
  配置和 `prompt_cache_key` 跨普通角色保持不变。
- 真实五轮：使用 `gpt-5.6-sol` / `xhigh`、Codex User-Agent 和 HTTP SSE；
  input token 逐轮递增，第 2-5 轮 `cached_input_tokens > 0`，且只记录供应商 usage。
- 完整流程：Project → Task → Requirement → Architect → 人工设计审批 →
  Planner → 人工计划审批；人工审批由测试执行者代为完成并保留 Approval/EventLog。
- 事务失败：在业务产物和 conversation turn 已准备后注入晚期失败，最终不得保留
  产物、conversation 或 `AgentRunCompleted`，只保留失败 AgentRun 与失败事件。
- 显式断点：本地契约必须发送官方 `prompt_cache_options` /
  `prompt_cache_breakpoint` 形态；兼容端点拒绝时记录真实 HTTP 错误，不静默删字段。
- 外部 provider 与真实缓存测试需要临时注入 API base/key；未注入时允许显式
  skip，但不能把 skip 计为默认回归通过或伪造缓存命中。

## 3. E2E 演示脚本

### 3.1 M1-M6 当前可执行演示

前置条件：

- 本地 PostgreSQL 已启动并完成迁移。
- `examples/sample-repo-python` 和受控 M6 workspace 根目录可用。
- 控制台能连接 Platform API。

步骤：

1. 在控制台创建或选择 `sample-repo-python` Project。
2. 创建 auth/profile Task，确认返回 `201` 和 `created / Created`。
3. 启动 M4，逐步展示 Requirement、Architect、设计审批、Planner 和计划审批。
4. 启动 M6 本地开发，展示 Scaffold 创建 Task 独立 workspace。
5. 展示 Coder 真实修改文件以及非空 diff。
6. 展示 Tester 的 pytest 退出码、JUnit 计数和 AC 映射。
7. 展示 Reviewer 对完整安全投影 diff、changed files 与 AC 的符合度检查，并
   展示 raw Artifact SHA 与 Git 门禁引用而非敏感正文。
8. 展示 Security 的 Bandit/pip-audit 结果和剩余风险。
9. 展示本地 branch、commit、可应用 format patch 和等价 PR record。
10. 从 Artifact/PR API 与控制台交叉核验同一 evidence set。
11. 展示 Timeline、AgentRun、ToolCall、Approval 和 EventLog 可追溯链。

### 3.2 M7-M10 后续演示

M7 的受控 candidate ref/真实 CI、两道审批、Linux staging 发布、Remote Agent
和 `MonitoringRegistered`，以及 M8 的集中日志/指标、告警和 SRE 分析在对应
里程碑完成后追加。M9 再追加多用户/RBAC、Desktop 离线同步，M10 追加真实
Windows/Linux 安装、Ops Hub bootstrap/备份恢复和 standalone/managed 双路径；
当前不纳入 M1-M6 演示通过结论。

## 4. M1-M6 验收标准映射

|设计书验收点|测试编号|演示证据|
|---|---|---|
|控制台创建功能开发任务|IT-002|任务创建页面、API 返回|
|任务状态实时变化|IT-002 至 IT-010、IT-017 至 IT-020|Task Timeline / SSE|
|Requirement Agent 生成规格|IT-003|RequirementSpec 页面|
|Architect Agent 生成技术设计|IT-004|Design Review 页面|
|开发者审批或修改方案|IT-005|Approval 记录|
|Agent 读取和修改示例仓库|IT-006|diff|
|Agent 在受控本地执行区运行测试|IT-007|TestReport / JUnit；M6 为受控 subprocess|
|系统生成 diff|IT-006|Diff Viewer|
|系统创建 branch 和 commit|IT-010|Git 记录|
|系统创建 PR 或等价记录|IT-010|M6 为本地 PR record，真实远端 PR 属于 M7|
|Reviewer Agent 给出审查结论|IT-008|ReviewReport|
|工具调用记录可查看|全流程|Tool Calls 面板|
|M1-M6 风险审批|IT-005、IT-009|设计/计划 Approval 与安全门禁记录|
|M1-M6 事件写入 event_logs|IT-001 至 IT-010|event_logs 查询|
|普通 Agent 共享 Task 主会话|IT-017|Agent Timeline、AgentRun usage、数据库 root conversation|
|只有显式内部 spawn 服务才创建子会话|IT-018|SubagentSpawned/Completed/Stopped 事件、父子记录、配额与工具权限交集审计|
|测试数据库不破坏开发库|IT-019|随机临时数据库名与测试后清理结果|
|重复点击不跨阶段推进|IT-020|阶段漂移 `409` 与唯一目标产物|

### 4.1 M7-M10 规划验收映射

|设计书验收点|测试编号|计划证据|
|---|---|---|
|release candidate 审批前无发布/CI|IT-011|ReleaseCandidate + ApprovalRequest|
|真实 CI 由唯一 workflow_dispatch 触发且只生成不可变制品|IT-012|run/job/artifact/manifest/digest 与 workflow 静态检查|
|L3 部署动作进入审批且单次消费|IT-022|ApprovalRequest + waiting/resumed ToolCall|
|Release / Deploy Agent 部署到远端 staging/demo|IT-024、IT-026|DeploymentHealthy + E2E timeline|
|Remote Agent 回传心跳和状态|IT-021|RemoteTarget + heartbeat EventLog|
|M7 控制台查看受限直读日志|IT-025|Remote Agent logs panel|
|M7 不执行 restart/rollback|IT-027|rollback candidate/request，且无远端执行 operation|
|production/Kubernetes/RemoteSession 为增强版|IT-028|M7 API/schema/UI 裁剪检查|
|M7 健康部署交接 Monitoring|IT-026|MonitoringRegistered + Task `Monitoring`|
|M8 控制台查看集中日志、指标|IT-013、IT-014|Loki Logs / Metrics panel|
|远端异常触发告警|IT-015|Alert / Incident|
|SRE Agent 给出分析|IT-016|IncidentAnalysis|
|Desktop 退出后服务端继续|IT-029、IT-030|WorkflowJob/EventLog/worker 证据|
|Ops Hub 可安装、升级和恢复|IT-031|bootstrap/backup/restore/uninstall 报告|
|Windows WSL 开发依赖可复现|IT-031A|预检输出、单 keepalive、Compose health、端口和 Platform API 回归记录|
|WSL 最小 Ops Hub 预演|IT-031B|profile health、worker heartbeat、continuation 和 Redis 补投证据|
|业务项目可独立剥离|IT-032、IT-034|Adapter 删除与双路径 E2E|
|通用 renderer 无项目专用模板|IT-033|schema/Compose policy 测试|
|用户分层权限、设备配对和职责分离|IT-035、IT-036、IT-041、IT-042|角色 Desktop/API、401/403、自批拒绝、pairing/撤销证据|
|Desktop sequence 离线补齐|IT-037|security/project snapshot、actor/subject event、SSE 记录|
|Ops Hub 与 Remote Target 安装生命周期分离|IT-031、IT-040|两台干净 VM 或同机隔离 profile 的安装/卸载证据|
|Windows/Linux 安装发行|IT-038、IT-039|安装包、checksum、干净 VM 与凭据扫描|

## 5. 当前失败恢复验证边界

- 已覆盖：进入应用异常处理的 provider/CLI/文件系统错误、事务回滚、Task
  pause/cancel、ToolCall/Artifact/PR record 幂等重试。
- 未覆盖：Platform API 进程在终态持久化前被强制终止。当前
  `pending/running` AgentRun/ToolCall 没有 lease、heartbeat 或 stale reclaim，
  因此不得把“进程 hard crash 后自动恢复”写入 M6 通过结论。
- M7-2C 已对 `side_effect_class=none` 的 WorkflowJob 实现并验证
  claim/lease/heartbeat/stale reclaim，包括真实 prefork hard-crash 和 Redis
  restart；该结论不扩展到 M6 AgentRun/ToolCall。
- 外部 CI/deploy handler 只有在同一 Gitea/Remote operation resolver、unknown
  -> recovery_required 和人工恢复入口通过后，才允许把外部副作用 hard-crash
  边界标记为关闭。

## 6. 缺陷分级

|等级|说明|示例|
|---|---|---|
|P0|阻断主闭环|不能创建任务、状态机崩溃、部署完全不可用|
|P1|阻断关键演示步骤|无法生成 PR、审批无法恢复、远端日志不可见|
|P2|影响体验但可绕过|页面刷新不及时、某些字段显示不完整|
|P3|文案或低风险问题|错别字、非关键布局问题|

## 7. 答辩证据归档

每次完整 E2E 演示后保存：

```text
artifacts/demo-run-YYYYMMDD-HHMM/
├── requirement_spec.json
├── technical_design.md
├── openapi.yaml
├── db_schema.sql
├── diff.patch
├── format.patch
├── test_report.json
├── junit.xml
├── security_report.json
├── review_report.md
├── pull_request_record.json
├── screenshots/
└── timeline.json
```

M7 完成后追加 `release_candidate.json`、`ci_manifest.json`、
`release_plan.json`、两道审批记录、`deployment_result.json`、
`monitoring_registered.json` 和受限日志摘要；M8 再追加集中日志/指标证据和
`incident_analysis.md`。
