# PROJECT_PLAN.md

本文件只记录当前下一步要落实的详细执行计划，不保存总项目规划。总流程和
打钩清单见 `docs/14-roadmap/03-implementation-milestone-flow.md`。

## 1. 下一实施阶段

完成当前 M1-M6 核验 Git 收口后的下一实施阶段为 M7：CI/CD 与远端部署闭环。

前置基线：M6 已完成并通过 2026-07-14 至 2026-07-15 的 M1-M6 全量核验，
当前项目版本为 `0.5.1`。本轮核验修复的跟踪文件已按子系统提交并同步
`origin/dev`；`informations/m7-ci-remote-deploy/` 属于下一阶段资料，不纳入
本轮基线。后续从该同步基线进入本计划的 M7 实施。该基线已经具备：

- 已审批最新版 DevelopmentPlan 驱动的 Scaffold、Coder、Tester、Reviewer、
  Security 本地开发闭环。
- Task root conversation、多轮工具 call/output、供应商 usage、Prompt Cache
  证据，以及显式 subagent conversation/权限/生命周期原语；不包含真实 child
  执行调度。
- Tool Gateway 工作区 allowlist、参数校验、风险分级、审计、限流、幂等、
  受控 subprocess、测试、安全扫描和 Git 工具。
- sample repo 真实 diff、pytest、Bandit、pip-audit、branch、commit 和
  `format_patch` Artifact。
- `artifacts`、`pull_request_records`、AgentRun workflow identity 和工具
  provider identity 的 PostgreSQL 持久化。
- `provider=local`、`url=null` 的本地等价 PR record，以及 diff/test/review/
  security 同一证据集约束。
- M6 Platform API、SSE 事件和控制台证据展示。

M7 不重复实现 M6 本地代码闭环，也不把本地 PR record 描述成远端 Git PR。
M7 负责把 M6 固化的精确 commit 作为 release candidate，经第一道审批发布受控
ref 并由真实 CI 生成不可变制品，再由 Release / Deploy Agent 生成 ReleasePlan，
经第二道 deployment approval 完成远端 staging/demo 部署。

版本影响：M7 新增模块、Agent、Tool、数据库表、状态机、API、远端协议和控制台
能力，属于兼容新增功能。完成后项目版本提升到 `0.6.0`；所有受影响模块版本、
migration、OpenAPI、JSON Schema、前端类型、配置和文档必须同步。

### 1.1 当前执行指针：M7-2

截至 2026-07-16：

- M7-0 细化设计与资料闭环已完成。
- M7-1 `Environment + RemoteTarget + machine-auth heartbeat` 已完成，包含
  migration、真实 PostgreSQL、Platform API、Remote Agent、共享 OpenAPI/JSON
  Schema、online/offline/recovery 事件与 Windows/Linux 测试。
- Roadmap 只勾选 Environment/RemoteTarget/machine-auth heartbeat；完整 M7 数据、
  CI、部署、Orchestrator/SSE、控制台和 E2E 继续保持未完成。

下一步固定为 M7-2：

```text
ProjectRepositoryBinding
  + ReleaseCandidate
  + WorkflowJob
  + Redis/Celery claim/lease/heartbeat/stale reclaim 基础
```

M7-2 创建或修改：

```text
modules/platform-api/migrations/versions/20260716_0008_create_m7_release_jobs.py
modules/platform-api/src/cloudhelm_platform_api/core/config.py
modules/platform-api/src/cloudhelm_platform_api/core/repository_config.py
modules/platform-api/src/cloudhelm_platform_api/models/
  approval.py
  project_repository_binding.py
  release_candidate.py
  workflow_job.py
modules/platform-api/src/cloudhelm_platform_api/schemas/
  approval.py
  project_repository_binding.py
  release_candidate.py
  workflow_job.py
modules/platform-api/src/cloudhelm_platform_api/repositories/
  approval_repository.py
  project_repository_binding_repository.py
  release_candidate_repository.py
  workflow_job_repository.py
modules/platform-api/src/cloudhelm_platform_api/services/
  approval_service.py
  approval_domain_decision_service.py
  release_candidate_contract.py
  release_candidate_policy.py
  project_repository_binding_service.py
  release_candidate_service.py
  workflow_job_service.py
modules/platform-api/src/cloudhelm_platform_api/providers/
  repository_profile_provider.py
  workflow_queue.py
modules/platform-api/src/cloudhelm_platform_api/api/
  repository_bindings.py
  release_candidates.py
modules/platform-api/tests/
  test_m7_project_repository_binding_api.py
  test_m7_release_candidate_api.py
  test_m7_workflow_jobs.py
  test_m7_approval_decisions.py
  test_database_migration.py
  test_m7_shared_contracts.py
modules/workflow-engine/
  pyproject.toml
  README.md
  src/cloudhelm_workflow_engine/
    config.py
    celery_app.py
    tasks.py
    handlers.py
    lease_heartbeat.py
    dispatcher.py
    worker_service.py
    stale_reclaimer.py
  tests/
packages/shared-contracts/schemas/ci/
packages/shared-contracts/schemas/workflow/
  release-candidate-reconcile-payload.schema.json
  release-candidate-reconcile-result.schema.json
packages/shared-contracts/schemas/events/task-event.schema.json
packages/shared-contracts/openapi/cloudhelm.openapi.yaml
docs/07-data/01-database-schema.md
docs/07-data/tables/
docs/08-api/05-approval-api.md
docs/08-api/07-environment-deployment-api.md
docs/14-roadmap/03-implementation-milestone-flow.md
docs/15-detailed-design/03-api-detail.md
docs/15-detailed-design/04-data-detail.md
.env.example
PROJECT_PROGRESS.md
```

M7-2 写代码前必须：

1. 复查本计划 7.0、7.3、7.4、7.9、7.10 和 7.14。
2. 复查 `informations/m7-ci-remote-deploy/official-references.md` 中 Celery、
   SQLAlchemy 行锁、Gitea profile、Git ref 和 Alembic 结论。
3. 执行：

   ```powershell
   git branch --show-current
   git status --short
   cd modules/platform-api
   uv lock --check
   uv run alembic current
   uv run alembic check
   uv run pytest -q
   ```

4. 先更新共享状态/错误码/事件契约，再写 migration 和生产代码。

M7-2 完成判定：

- repository binding 请求只接受服务端 profile key，不接受任意 URL、token、
  workflow path、remote 或 refspec。
- repository binding 更新允许替换服务端 profile，但 ReleaseCandidate 必须持久化
  不含 secret 的 binding snapshot JSON、覆盖内部 clone URL/credential ref 的
  snapshot hash；更新后旧 pending/approved candidate 必须转 stale。
- `POST /api/tasks/{task_id}/release-candidate` 只接受严格空对象，由服务端绑定
  最新 open M6 PullRequestRecord、完整 commit、受控 target ref、snapshot hash、
  request hash 和第一道审批；同一事务还创建无外部副作用的 reconcile job，审批前
  没有 push、CI 或外部副作用。
- 最新 PullRequestRecord 必须有 `created_by_agent_run_id`。CandidateService
  预生成 Candidate UUID，先创建
  `requested_by_agent_run_id=PullRequestRecord.created_by_agent_run_id` 的
  Approval，再创建 `approval_id NOT NULL` 的 Candidate 和 WorkflowJob；缺失实现
  AgentRun 返回 `409 m6_pull_request_creator_required`。
- snapshot、candidate request 和 WorkflowJob request 全部复用
  `cloudhelm_tool_gateway.audit.stable_json_hash`；canonical JSON 与版本字段、
  target ref、idempotency key 和 rejected 后重复 POST 语义必须按 7.4 唯一实现。
- ApprovalRequest 本切片补齐 resource、request hash、expiry 和 consumed 字段；
  approve/reject 只更新审批与 candidate，不 publish、不 dispatch，`consumed_at`
  留到后续显式 publish 步骤；M7-2 不改 Task status/current phase，Orchestrator
  `WaitingMergeApproval -> CIValidating` 接入留到后续纵切。
- `approve_release_candidate` 是内部保留 action；通用
  `POST /api/tasks/{task_id}/approvals` 必须返回
  `422 approval_action_reserved`。数据库双向约束保证该 action 当且仅当
  `resource_type=release_candidate` 且 `risk_level=L2`，领域决策同时匹配 action
  与 resource type。
- 第一道审批的实现者身份固定来自
  `Approval.requested_by_agent_run_id = PullRequestRecord.created_by_agent_run_id`。
  approve/reject 将 trim 后的 plain UUID 或 `agent-run:<UUID>` actor_id 规范化为
  UUID；与该 ID 相同时返回 `403 approval_self_decision_forbidden`。
- 第一道审批决策先用无锁 hint 找到 Candidate/Binding，再按
  `Task -> ProjectRepositoryBinding -> ReleaseCandidate -> Approval` 加锁并重验
  task/resource/hash/expiry；禁止先锁 Approval 再反向锁 Candidate。
- `workflow_jobs` 成为 PostgreSQL 业务权威；Celery message 只携带 job id。
- job 固定保存 `side_effect_class`，claim/lease/heartbeat/stale reclaim 使用短
  事务；无外部副作用 job 可安全重排，可能已产生外部副作用且状态未知时进入
  `recovery_required`。
- durable dispatcher 使用 dispatch lease、`next_enqueue_at`、enqueue attempt/
  error 和周期扫描关闭 PostgreSQL/Redis 双写空窗；重复消息仍由 PostgreSQL
  claim 去重。
- WorkflowJob 的 claimable、lease-active、resource-blocking、terminal 状态集合，
  cancel 转移、三类 side-effect stale 处理、dispatcher reserve/finalize 与
  `Task -> WorkflowJob` 锁顺序必须按 7.4 唯一实现。
- upgrade/downgrade/check、顺序/并发幂等、hard-crash/stale reclaim、OpenAPI/
  schema、文档和进度验证全部通过后，才勾对应 Roadmap 子项。

## 2. 阶段目标

完成以下真实闭环：

```text
M6 PullRequestCreated + 本地 PR record + 精确 commit
  -> 用户审批 release candidate
  -> Git Tool 将精确 commit 发布到受控 Gitea branch
  -> CI 执行 test / security / build / artifact
  -> CI 产出 commit 绑定的 image digest 和 artifact manifest
  -> Release / Deploy Agent 生成 ReleasePlan
  -> Tool Gateway 拦截 deploy.deploy_staging（L3）
  -> 用户审批精确 ReleasePlan
  -> Deploy Tool
  -> Deployment Controller
  -> Remote Agent
  -> docker compose config / pull / up
  -> /health 与容器状态检查
  -> 服务实例、部署结果、心跳和日志回传
  -> Task 进入 Monitoring，交给 M8
```

### 2.1 固定语义

1. CI 只负责代码检出、依赖锁校验、测试、安全扫描、镜像构建和制品发布。
   CI workflow 中禁止 SSH、远端 Compose、部署 API、Remote Agent 调用或服务重启。
2. 真实远端变更只允许沿以下链路执行：

   ```text
   Release / Deploy Agent
     -> Tool Gateway
     -> Deploy Tool
     -> Deployment Controller
     -> Remote Agent
   ```

3. Release / Deploy Agent 是普通 Agent，继续复用当前 Task root conversation；
   角色变化只增加 turn，隐式新建 conversation 仍被禁止。
4. 部署只接受 CI 成功制品。ReleasePlan 中的 `commit_sha` 必须等于当前
   PullRequestRecord 的 commit，镜像必须使用 OCI digest，禁止只凭可变 tag 部署。
5. 部署审批必须绑定：
   - Task 与 Project。
   - `environment_id`、`remote_target_id`。
   - `ci_run_id`、`commit_sha`。
   - `image_digest`。
   - `release_plan_sha256`。
6. 审批通过后仍由用户或 Orchestrator 显式执行下一步；Approval API 本身只记录
   决策，不在审批 HTTP 事务中直接发起远端副作用。
7. Remote Agent 是实际远端执行入口。Agent 离线时只允许 SSH 预定义只读诊断，
   部署动作进入阻塞状态。
8. M7 只部署 staging/demo。production、Kubernetes、自动回滚和交互终端不进入
   本阶段完成范围。
9. M7 成功后 Task 进入 `Monitoring`，保留给 M8 的监控、告警和 SRE 闭环；
   本阶段不提前进入 `Done`。
10. CI、HTTP 和远端执行不得在持有 Task 行锁时等待。M7 必须采用短事务
    claim + lease/heartbeat + stale reclaim，把 M1-M6 已登记的 hard-crash
    active 记录恢复边界纳入 worker 设计。
11. Agent 委派与沟通继续参考 Codex CLI：root thread 保留用户目标、决策和
    最终汇总；只有显式 spawn 才创建 child，默认 `max_depth=1`、
    `max_threads=6`；read-heavy 可并行，写共享 workspace/Git/远端状态的任务
    必须串行或隔离；child 只回传脱敏摘要和证据引用，权限不得高于父线程。
    M7 若增加运行中用户消息，必须明确区分 steer 当前 turn 与 queue 下一 turn。

### 2.2 MVP 固定实现路径

- CI Provider：Gitea Actions + `act_runner`。
- Git/CI 演示环境：本地 Docker Compose 中的 Gitea、runner 和受控镜像 registry。
- 远端目标：一台独立 Linux VM、局域网 Linux 主机或云服务器。
- 远端运行方式：systemd 管理 Remote Agent，业务项目使用 Docker Compose。
- 制品：CI test/security report、SBOM/镜像扫描结果、CI manifest、镜像引用和
  `sha256` digest。
- 部署配置：项目受控 Compose 模板 + 远端预配置 env profile。
- 远端协议：认证 HTTPS；请求带目标、部署、幂等键和 request hash。
- SSH：只用于人工安装、连通性预检和预定义只读诊断，不作为部署执行器。

## 3. 必须先阅读的本地资料

- `AGENTS.md`
- `云舵 CloudHelm 毕设设计书.md`
- `PROJECT_PROGRESS.md`
- `docs/14-roadmap/03-implementation-milestone-flow.md`
- `docs/15-detailed-design/00-mvp-scope-and-cutline.md`
- `docs/15-detailed-design/01-module-contracts.md`
- `docs/15-detailed-design/02-agent-tool-contract.md`
- `docs/15-detailed-design/03-api-detail.md`
- `docs/15-detailed-design/04-data-detail.md`
- `docs/15-detailed-design/05-workflow-state-events.md`
- `docs/15-detailed-design/06-deployment-observability-detail.md`
- `docs/15-detailed-design/07-testing-acceptance-matrix.md`
- `docs/15-detailed-design/08-m6-local-development-flow.md`
- `docs/06-workflows/01-pr-to-remote-deploy.md`
- `docs/04-agents/agents/release-agent.md`
- `docs/05-tool-layer/tools/ci-tool.md`
- `docs/05-tool-layer/tools/deploy-tool.md`
- `docs/05-tool-layer/tools/remote-control-tool.md`
- `docs/03-modules/modules/deployment-controller.md`
- `docs/03-modules/modules/remote-agent.md`
- `docs/03-modules/modules/remote-control-plane.md`
- `docs/08-api/07-environment-deployment-api.md`
- `docs/08-api/08-remote-ops-api.md`
- `docs/12-deployment/README.md`
- `docs/12-deployment/00-local-development.md`
- `docs/12-deployment/01-remote-demo-deployment.md`
- `docs/12-deployment/02-demo-environment.md`
- `docs/12-deployment/03-production-extension.md`
- `docs/10-security/00-security-boundary.md`
- `docs/10-security/01-permission-policy.md`
- `modules/agent-runtime/README.md`
- `modules/tool-gateway/README.md`
- `modules/platform-api/README.md`
- `packages/shared-contracts/openapi/cloudhelm.openapi.yaml`

## 4. 写代码前必须查阅并归档的成熟实践

当前文件已经存在，编码前必须核验、补齐并提交：

```text
informations/m7-ci-remote-deploy/official-references.md
informations/m7-ci-remote-deploy/reference-projects.md
```

`official-references.md` 至少记录检索日期、官方链接、适用子任务、摘要、采用结论
和排除结论：

1. Gitea Actions workflow、`act_runner` 注册、workflow dispatch、run/job/artifact
   API、Webhook 签名和 delivery id。
2. Git 官方远端配置、非 force push、精确 ref/commit 推送和远端 commit 校验。
3. Docker Buildx、OCI image digest、SBOM/provenance、registry push/pull 和镜像
   digest 校验。
4. Docker Compose `config`、`pull`、`up -d`、healthcheck、project name、资源和
   安全配置。
5. FastAPI 服务部署、认证 dependency、流式响应、请求体积限制和长操作边界。
6. HTTPX TLS、连接池、连接/读取超时和流式下载。
7. SQLAlchemy 2.x 行锁、短事务、外部副作用前后事务拆分和并发幂等。
8. Alembic 多表、约束、索引、downgrade 和 `alembic check`。
9. systemd service hardening、专用用户、文件权限、环境文件和服务重启策略。
10. Linux Docker socket 权限风险、专用 staging 用户和最小命令 allowlist。
11. OpenAPI / JSON Schema 跨服务契约和兼容演进。
12. SSH host key 校验、只读诊断命令和密钥文件权限。
13. Celery + Redis broker 的 late ack、prefetch、重试、task id 和 worker shutdown，
    以及 PostgreSQL 业务 job/lease 与 broker 投递的职责边界。

`reference-projects.md` 只总结架构和工程实践：

- Rundeck：审批、作业执行记录和幂等远端动作。
- Windmill：脚本动作封装和参数化审计。
- Kestra：事件驱动工作流和失败恢复。
- MeshCentral：Agent 心跳、设备状态和远端操作。
- Teleport：主机身份、会话审计和 SSH host verification。

禁止保存第三方全文、真实 Token、Cookie、runner registration token、服务器
地址、SSH 私钥或 registry 凭据。

## 5. 本阶段排除范围

- production 部署、生产数据库迁移和生产回滚。
- Kubernetes、Argo CD、Flux、Terraform/OpenTofu 和多云资源管理。
- 完整 Prometheus、Loki、Alertmanager、Incident 和 SRE Agent；这些属于 M8。
- 自动执行回滚；M7 只保存 rollback candidate 和 rollback plan。
- 任意 SSH command、交互式远程终端和浏览器式远程桌面。
- 远端服务重启、清缓存和 feature flag 变更。
- CI workflow 内的 SSH、Compose 上线、Remote Agent 调用或部署 webhook。
- 只靠可变 image tag、未验证 artifact 或用户提交的任意镜像地址部署。
- 从 HTTP 请求接收任意主机、SSH key、token、Compose 路径或本地文件路径。
- 在 Platform API 路由、React 页面或 Agent prompt 中堆积部署业务规则。
- 用测试 fake、固定返回或本地静态 JSON 冒充真实远端部署。
- 自动把健康部署后的 Task 写为 `Done`。

## 6. 预检步骤

### 6.1 Git 与 M6 基线

```powershell
git branch --show-current
git status --short
git log --oneline --decorate --max-count=10
git diff --stat
```

要求：

- M6 已完成验证、提交并推送。
- `dev` 工作区干净。
- 从 `dev` 创建 `feature/m7-remote-deploy-closure`。
- `PROJECT_PROGRESS.md`、roadmap、README、OpenAPI、schema 和版本均已同步到
  M1-M6 核验修复版 `0.5.1`。

### 6.2 M6 完整回归

```powershell
cd modules/tool-gateway
uv lock --check
uv run pytest -q

cd ..\agent-runtime
uv lock --check
uv run pytest -q

cd ..\orchestrator
uv lock --check
uv run pytest -q

cd ..\platform-api
uv lock --check
uv run alembic upgrade head
uv run alembic check
uv run pytest -q

cd ..\..\examples\sample-repo-python
uv lock --check
uv run pytest -q

cd ..\..\apps\control-console
npm.cmd test
npm.cmd run build
```

额外确认：

- M6 sample workspace 和 Artifact root 可创建并写入。
- 最新 PullRequestRecord 的四类质量证据、commit 和 format patch 同属一个
  `evidence_set_id`。
- Task 最终处于 `PullRequestCreated`，而不是终态。
- 普通 Agent 继续使用同一 Task root conversation。

### 6.3 本地 CI 工具预检

```powershell
Get-Command docker, git, uv, node, npm, ssh -ErrorAction SilentlyContinue
docker version
docker compose version
git --version
uv --version
node --version
npm.cmd --version
```

要求：

- Docker Desktop 使用 Linux containers。
- Gitea、runner 和 registry 端口规划无冲突。
- Gitea token、runner registration token、registry 凭据只通过当前进程或被
  `.gitignore` 排除的本地 env 文件注入。
- CI runner 能访问 Gitea、registry 和外部依赖源。
- 远端主机能访问 registry；实际演示路径优先使用 TLS registry。

### 6.4 远端 Linux 主机预检

远端主机信息只通过环境变量或受控配置注入：

```powershell
$env:CLOUDHELM_M7_REMOTE_SSH = "USER@HOST"
ssh $env:CLOUDHELM_M7_REMOTE_SSH "uname -a"
ssh $env:CLOUDHELM_M7_REMOTE_SSH "docker version"
ssh $env:CLOUDHELM_M7_REMOTE_SSH "docker compose version"
ssh $env:CLOUDHELM_M7_REMOTE_SSH "df -h /opt"
ssh $env:CLOUDHELM_M7_REMOTE_SSH "timedatectl status"
```

要求：

- Linux 主机已安装 Docker Engine、Compose plugin 和 systemd。
- 时间同步正常。
- `/opt/cloudhelm/projects` 和 `/var/lib/cloudhelm-remote-agent` 可由专用服务用户
  使用。
- Remote Agent 端口只对控制平面所在私网或指定来源开放。
- 控制平面和远端双方信任对应 TLS CA。
- registry、控制平面和远端主机网络互通。
- staging/demo 使用专用 Docker Compose project，不复用其他业务目录。

如果真实远端主机、TLS 或 registry 尚未准备，代码和本地集成测试可以继续；
M7 总里程碑保持阻塞，直到完成一次真实远端 E2E。

## 7. 详细任务拆分

### 7.0 固定实施顺序、异步执行器与权威身份

M7 各节编号按能力分组，不代表可以跳过前置层。实际实施顺序固定为：

```text
7.1 设计书 / 详细设计 / 资料冲突收敛
  -> 7.3 shared contracts、状态枚举和事件
  -> 7.4 migration、repository 和持久化身份
  -> 7.10 Environment / RemoteTarget / heartbeat 最小 API
  -> 7.2 Gitea Actions、registry 和 CI provider
  -> 7.5 Remote Agent
  -> 7.6 Deployment Controller
  -> 7.7 Tool Gateway
  -> 7.8 Release / Deploy Agent
  -> 7.9 Orchestrator
  -> 7.10 完整 API / SSE
  -> 7.12 控制台
  -> 7.11 安装配置 / E2E
  -> 7.13 契约、版本和文档收口
```

异步执行器固定采用项目设计书已选的 **Redis + Celery**，不自研任务队列：

- 新增 `modules/workflow-engine`，Celery task 只携带数据库 `workflow_job_id`，
  不携带 secret、Compose、任意 URL 或自由命令。
- PostgreSQL `workflow_jobs` 是业务权威，保存 job type、resource、request hash、
  idempotency key、attempt、lease owner、lease expiry、heartbeat、next retry、
  cancel requested、结果摘要和错误码。
- Redis/Celery 只负责投递和 worker 调度；worker claim 成功并提交短事务后才执行
  Git、CI、HTTP 或远端副作用，结束后使用新事务写终态。
- worker 使用 `acks_late`、有界 prefetch 和显式超时，但幂等仍由 PostgreSQL
  request hash、远端 operation id 和唯一约束保证；Celery retry 不得盲目重放
  push、build 或 deploy。
- stale reclaim 只抢占 lease 已过期且远端查询确认可恢复的 job；远端状态不明时
  标记 `recovery_required`，不得自动重复部署。

CI 唯一触发语义固定为：

- 受控 Git Tool 将精确 commit 推送到服务端生成的 release candidate ref。
- Gitea workflow **不监听 push**，仅允许 Platform API 使用固定 workflow id、
  精确 ref 和结构化 inputs 发起 `workflow_dispatch`。
- delivery id 只标识一次 webhook delivery attempt；状态幂等同时绑定 repository、
  workflow run/job id、event action/status、head SHA 和 provider updated time。
- `publish_release_candidate` 与 `trigger_ci` 是两个独立可审计步骤；同一 candidate
  只能产生一个有效 CIRun，重复 dispatch 返回已有 run/job。

发布身份和审批固定为两道独立门禁：

1. Release candidate approval：绑定当前 PullRequestRecord、精确 commit、受控
   repository binding、目标 ref 和 request hash；通过后才允许 push/dispatch。
2. Deployment approval：绑定 CIRun、CI manifest、image digest、ReleasePlan、
   Environment、RemoteTarget 和 request hash；通过后才允许 Remote Agent 副作用。

Coder、Scaffold、提交代码的 AgentRun 及创建 PullRequestRecord 的 AgentRun
不得批准上述任一审批；必须补实现者自批、过期、已消费和 hash 漂移负测。

其他固定边界：

- M7 只提供 Remote Agent 的受限直读日志与 diagnostics；M8 再接 Loki 的集中检索。
- M7 只生成 rollback candidate / rollback request，不自动执行回滚。
- 实际镜像身份以 registry index/manifest digest 和平台 manifest 为准；远端
  `pull` 后必须核对 `RepoDigests`/平台信息，容器 image id 不作为审批证据。
- registry credential 由远端专用用户通过受控 credential file/store 获取，不进入
  ReleasePlan、API、Agent 输出、Compose、Artifact 或日志。
- 首个代码纵切固定为
  `Environment + RemoteTarget + machine-auth heartbeat`；它必须包含 migration、
  repository、service、API、OpenAPI、事件、online/offline/recovery 规则和真实
  PostgreSQL 黑盒/白盒测试，且 API 不返回 credential ref 或完整 endpoint。

### 7.1 先完成 M7 细化设计与边界决策

核验、补齐或创建：

```text
云舵 CloudHelm 毕设设计书.md
docs/15-detailed-design/09-m7-ci-remote-deployment-flow.md
docs/15-detailed-design/03-api-detail.md
docs/15-detailed-design/04-data-detail.md
docs/15-detailed-design/05-workflow-state-events.md
docs/15-detailed-design/07-testing-acceptance-matrix.md
docs/00-project/02-references.md
docs/01-architecture/00-system-architecture.md
docs/06-workflows/01-pr-to-remote-deploy.md
docs/06-workflows/04-remote-takeover.md
docs/08-api/00-api-overview.md
informations/m7-ci-remote-deploy/official-references.md
informations/m7-ci-remote-deploy/reference-projects.md
```

细化设计必须明确：

- Gitea Actions、runner 和 registry 的拓扑。
- M6 本地 PR record 到 release candidate 的衔接。
- CI workflow 的允许动作和部署命令禁止清单。
- CI run、artifact manifest、image digest 和 commit 的证据关系。
- ReleasePlan、部署审批和 request hash。
- Deployment Controller 与 Remote Agent 的 HTTP 契约。
- Remote Agent 身份认证、TLS、心跳、幂等和命令 allowlist。
- Compose 模板、远端 env profile、release 目录和健康检查。
- 远端日志的分页/流式边界和脱敏规则。
- Task、CI、Deployment、ServiceInstance 的状态机和失败恢复。
- M7 到 M8 的 `Monitoring` 交接条件。
- Redis + Celery worker、PostgreSQL workflow job、lease/heartbeat/stale reclaim。
- 独立 release candidate 持久化身份与两道审批。
- 受控 Gitea repository binding、credential ref 和 workflow id。
- `workflow_dispatch` 单一触发源及 run/job/delivery 幂等键。
- M7 受限 Remote Agent 日志与 M8 Loki 日志检索边界。
- rollback candidate/request 与自动回滚的排除边界。
- 实现者不得自批、registry credential、实际 digest 复核与审计 actor。

设计冲突先同步相关 `docs/`，再开始生产代码。

验证命令与完成判定：

```powershell
git diff --check
Select-String -Path '云舵 CloudHelm 毕设设计书.md',docs/**/*.md `
  -Pattern 'image_tag|POST\s+/api/deployments\s*$|CI.*执行部署|CI\s*-->\s*Deploy|PR 合并后能触发.*部署|自动进入远端部署环境|remote\.ssh_exec_readonly.*command|remote\.open_terminal'
```

Ansible、Kubernetes、production、`remote_sessions` 和 WebSocket terminal 允许保留
为明确标注的增强版设计，但必须人工核对其上下文未被描述成 M7 交付能力。

- `docs/15-detailed-design/09-m7-ci-remote-deployment-flow.md` 可独立回答上述全部
  边界问题。
- 总体设计书与 API/Data/Workflow/Testing 文档不再要求客户端提交 commit/image，
  不再把 CI 写成部署执行者，不再宣称 M7 自动回滚。
- 完成后仅记录 M7-0 设计任务完成，不勾选任何尚未落代码的 M7 能力。

### 7.2 建立真实 CI 与 release candidate 来源

本节只能在 7.3 shared contracts、7.4 持久化身份和 7.10 最小
Environment/RemoteTarget API 验证通过后实施。

建议创建或更新：

```text
infra/ci/
  docker-compose.ci.yml
  README.md
  gitea/
    app.ini.example
  act-runner/
    config.example.yaml
  registry/
    README.md
examples/sample-repo-python/
  .gitea/workflows/ci.yml
  scripts/build_ci_manifest.py
modules/platform-api/src/cloudhelm_platform_api/providers/ci/
  __init__.py
  base.py
  gitea_actions.py
modules/platform-api/tests/
  test_m7_gitea_ci_provider.py
  test_m7_ci_webhook.py
```

实现要求：

1. release candidate 必须引用当前最新版 PullRequestRecord 和精确 commit。
2. 用户通过 `approve_release_candidate` 后，Git Tool 才能把该 commit 发布到受控
   Gitea branch；禁止 force push。
3. Project 配置为远端 Git 模式时，M6 workspace 应从该 Project 的受控仓库
   clone；fixture 模式继续保留给离线测试。
4. CI workflow 至少执行：
   - `uv lock --check`
   - pytest + JUnit
   - Bandit
   - pip-audit
   - Docker Buildx 构建
   - Trivy 或等价镜像扫描
   - SBOM/manifest 生成
   - 镜像推送并记录 digest
5. 任一测试、安全或构建步骤失败时禁止发布可部署 manifest。
6. CI workflow 静态契约测试必须确认不存在 SSH、SCP、远端 Compose、部署 API、
   Remote Agent 或服务重启命令。
7. CI Provider 校验 webhook 签名、delivery id、repository、ref 和 commit。
8. 同一 delivery id 或 run id 重放时返回已有结果，不重复创建 CIRun。
9. Platform 下载并保存 CI 报告时校验大小、媒体类型和 SHA-256。
10. CI manifest 至少包含：
    - provider、repository、run id。
    - source branch、commit SHA。
    - test/security/build 状态。
    - image ref 和 immutable digest。
    - test/security/SBOM artifact 引用和 SHA-256。
    - workflow revision、开始/结束时间。
11. Gitea/act_runner 使用固定 patch 版本或镜像 digest，runner 与 Remote Agent、
    registry 和部署目标分机或分 Compose 网络隔离，不使用 `latest`/`nightly`。
12. workflow 只使用 `workflow_dispatch`，不得同时监听 push。

### 7.3 扩展 Agent、CI、部署和远端共享契约

新增或更新：

```text
modules/agent-runtime/src/cloudhelm_agent_runtime/schemas/
  release.py
  agent_io.py
modules/agent-runtime/src/cloudhelm_agent_runtime/prompts/
  release.md
  base.md
modules/agent-runtime/src/cloudhelm_agent_runtime/
  instructions.py
modules/agent-runtime/src/cloudhelm_agent_runtime/providers/
  contracts.py
packages/shared-contracts/schemas/agents/
  release-agent-output.schema.json
packages/shared-contracts/schemas/ci/
  ci-run.schema.json
  ci-artifact-manifest.schema.json
packages/shared-contracts/schemas/workflow/
  release-candidate-reconcile-payload.schema.json
  release-candidate-reconcile-result.schema.json
packages/shared-contracts/schemas/deployments/
  release-plan.schema.json
  deployment-result.schema.json
  health-check-result.schema.json
packages/shared-contracts/schemas/remote/
  remote-agent-heartbeat.schema.json
  remote-operation.schema.json
  service-status.schema.json
  remote-log-event.schema.json
packages/shared-contracts/schemas/tools/
  ci-tool.schema.json
  deploy-tool.schema.json
  remote-control-tool.schema.json
packages/shared-contracts/openapi/
  cloudhelm-remote-agent.openapi.yaml
```

`ReleasePlan` 最低字段：

- task/project/environment/remote target。
- PullRequestRecord、CI run 和 commit。
- release version。
- image ref 和 digest。
- compose template revision。
- env profile ref，只保存引用和版本，不保存 secret 值。
- service、port、volume 和 health check。
- rollback candidate。
- risk level、approval reason。
- `release_plan_sha256`。

`DeploymentResult` 最低字段：

- deployment、remote operation 和 target。
- release version、commit、image digest。
- Compose project。
- 每个服务的状态、runtime ref 和 health result。
- started/finished 时间。
- stdout/stderr 脱敏摘要和日志 Artifact。
- failure code、retryable 和 rollback candidate。

Agent Runtime 要求：

- 一次性扩展稳定输出传输 schema 和稳定工具声明集合。
- 所有普通角色从 M7 起继续发送同一 schema/tools 前缀。
- Release Agent 专属输出仍由严格 Pydantic model 二次校验。
- M7 契约升级可以造成一次预期缓存冷启动，后续普通角色 turn 必须重新稳定命中。
- Release Agent 禁止直接调用 Git、HTTP、Docker、SSH 或远端文件系统。

### 7.4 数据模型与 migration

M7-1 已落地：

```text
modules/platform-api/src/cloudhelm_platform_api/models/
  environment.py
  remote_target.py
modules/platform-api/src/cloudhelm_platform_api/repositories/
  environment_repository.py
  remote_target_repository.py
modules/platform-api/migrations/versions/
  20260715_0007_create_m7_environment_remote_target.py
```

其中 `remote_target.py` 同时承载 `RemoteAgentCredential` 和
`RemoteAgentReplayNonce` ORM。M7-1 的四张表、约束、索引和
upgrade/downgrade/check 已验证通过。

M7-2 下一纵切新增：

```text
modules/platform-api/src/cloudhelm_platform_api/models/
  project_repository_binding.py
  release_candidate.py
  workflow_job.py
modules/platform-api/src/cloudhelm_platform_api/repositories/
  project_repository_binding_repository.py
  release_candidate_repository.py
  workflow_job_repository.py
modules/platform-api/migrations/versions/
  20260716_0008_create_m7_release_jobs.py
modules/workflow-engine/
  pyproject.toml
  README.md
  src/cloudhelm_workflow_engine/
    config.py
    celery_app.py
    tasks.py
    handlers.py
    lease_heartbeat.py
    dispatcher.py
    worker_service.py
    stale_reclaimer.py
  tests/
    test_job_claim.py
    test_stale_reclaim.py
```

后续 M7 纵切再新增：

```text
modules/platform-api/src/cloudhelm_platform_api/repositories/
  ci_run_repository.py
  deployment_repository.py
  service_instance_repository.py
modules/platform-api/src/cloudhelm_platform_api/models/
  ci_run.py
  deployment.py
  service_instance.py
```

新增表：

#### `project_repository_bindings`

- `project_id`
- `provider`: M7 固定 gitea
- `profile_key`
- `repository_external_id`、`repository_owner`、`repository_name`
- `clone_url`、`default_branch`
- `credential_ref`
- `workflow_id`
- `release_ref_prefix`
- `status`: active/disabled
- 唯一约束：`project_id`、provider/repository external id、
  provider/owner/name

API 只接受服务端 repository profile key；`credential_ref` 不进入读取响应，
调用方不得提交任意 clone URL、remote、workflow path 或 push refspec。

#### `release_candidates`

- `task_id`、`project_id`
- `pull_request_record_id`
- `repository_binding_id`
- `binding_snapshot_json`
- `binding_snapshot_sha256`
- `commit_sha`
- `target_ref`
- `request_hash`
- `status`: pending_approval/approved/rejected/published/stale/cancelled
- `approval_id`
- `remote_verified_sha`
- `idempotency_key`
- `approved_at`、`published_at`
- 唯一约束：`(task_id, idempotency_key)`、
  `(repository_binding_id, target_ref)`、
  `(pull_request_record_id, binding_snapshot_sha256)`
- 每个 Task 同时最多一个 `pending_approval|approved` candidate；`published`
  是已经发生过远端发布的历史终态，不进入该部分唯一索引

`binding_snapshot_json` 只保存 provider、repository identity、default branch、
workflow id 和 release ref prefix；`binding_snapshot_sha256` 还覆盖内部 clone URL
与 credential ref 以及 profile key，但内部字段不进入 candidate API。Binding PUT
必须先重算 internal snapshot hash：相同 profile key、物化字段和 active 状态的
幂等 PUT 返回原 binding，不改 `updated_at`、不写事件，也不失效 Candidate；
只有 internal snapshot hash 变化或 binding 从 active 变为 disabled 时，
旧 pending/approved candidate 与其 pending approval 才在同一事务转为 stale/
expired。系统失效固定写
`decided_by=system:release_candidate_freshness` 与数据库 `decided_at=now()`。

Binding PUT 与 Candidate POST 的并发串行化固定为：

- Candidate POST 按 `Task -> ProjectRepositoryBinding -> PullRequestRecord ->
  existing Candidate` 加锁，并从生成 snapshot 到插入 Candidate 的整个短事务持有
  Binding `FOR UPDATE`。
- Binding PUT 先锁 Binding，再按 Candidate UUID、Approval UUID 升序锁定并失效旧
  资源；该事务不反向获取 Task。
- 因此 PUT 先提交时 POST 读取新 snapshot；POST 先提交时 PUT 必须看到并失效刚创建
  的旧 snapshot Candidate，不允许留下基于旧 binding 的 active Candidate。

M7-2 canonical 与幂等算法固定如下，不允许在 ORM、service、worker 或测试中各自
实现另一套序列化：

1. `stable_json_hash(value)` 的输入对象必须先把 UUID 转为小写标准字符串；函数按
   `json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)` 生成 UTF-8
   bytes，并返回 `sha256:<64 lowercase hex>`。
2. 安全 snapshot JSON 精确包含八个字段：

   ```json
   {
     "schema_version": "m7.repository-binding.snapshot.v1",
     "provider": "gitea",
     "repository_external_id": "123",
     "repository_owner": "cloudhelm",
     "repository_name": "demo",
     "default_branch": "dev",
     "workflow_id": ".gitea/workflows/ci.yml",
     "release_ref_prefix": "refs/heads/cloudhelm/candidates"
   }
   ```

3. `binding_snapshot_sha256` 对内部对象计算；内部对象由
   `schema_version=m7.repository-binding.internal-snapshot.v1`、
   `public_snapshot=<上述八字段对象>`、`profile_key`、`clone_url` 和
   `credential_ref` 组成。内部对象不落 `binding_snapshot_json`、API 或 EventLog。
4. `release_ref_prefix` 必须是无尾斜杠的完整 `refs/heads/...` 前缀，且通过等价
   `git check-ref-format` 校验。`target_ref` 固定为
   `{release_ref_prefix}/{task_id}/{full_commit_sha}/{snapshot_hash_hex}`。
5. candidate request canonical 精确包含：
   `schema_version=m7.release-candidate.request.v1`、
   `action=approve_release_candidate`、`task_id`、`project_id`、
   `pull_request_record_id`、`repository_binding_id`、
   `binding_snapshot_sha256`、`commit_sha`、`target_ref`；其稳定 hash 即
   `request_hash`，`idempotency_key` 固定为
   `release_candidate:v1:<request_hash hex>`。
6. 顺序/并发重复 POST 按
   `(pull_request_record_id, binding_snapshot_sha256)` 返回同一 Candidate、
   Approval 和内部 reconcile job。若该 Candidate 已 rejected，仍返回原 rejected
   记录且不创建新审批；重新申请必须产生新的 PullRequestRecord 或新的 binding
   snapshot。首次创建返回 201，幂等命中返回 200。

#### `workflow_jobs`

- `task_id`
- `job_type`
- `resource_type`、`resource_id`
- `side_effect_class`: none/external_idempotent/external_uncertain
- `status`
- `idempotency_key`、`request_hash`
- `attempt`、`max_attempts`
- `lease_owner`、`lease_expires_at`、`heartbeat_at`
- `next_retry_at`、`cancel_requested_at`
- `dispatch_lease_owner`、`dispatch_lease_expires_at`
- `next_enqueue_at`、`last_enqueued_at`
- `enqueue_attempt`、`last_enqueue_error_code`
- `payload_json`、`result_json`
- `error_code`
- `started_at`、`finished_at`
- 唯一约束：`(task_id, job_type, idempotency_key)`
- 同一 job type/resource 的 resource-blocking 部分唯一索引
- active/lease/retry/enqueue 查询索引

M7-2 生产 handler 只实现无外部副作用的
`release_candidate_reconcile`：复核 candidate、最新 PR、binding snapshot 与
approval freshness，必要时原子标记 stale/expired。publish、CI 和 deploy handler
留到后续纵切，不能以占位 handler 冒充。

WorkflowJob 状态集合与索引谓词固定为：

```text
claimable        = pending
lease-active     = claimed | running | cancel_requested
resource-blocking= pending | claimed | running | cancel_requested | recovery_required
terminal         = succeeded | failed | cancelled
manual-blocking  = recovery_required
```

- `attempt` 在 claim 成功时加一；`started_at` 在首次 `claimed -> running` 时写入；
  terminal 写 `finished_at`。`recovery_required` 清空 worker/dispatch lease，
  `next_retry_at/next_enqueue_at` 为空且 `finished_at=null`，并阻止同资源创建新 job。
- safe retry 或 stale reclaim 只有在 `attempt < max_attempts` 时回 pending；达到
  上限时进入 failed，固定写
  `error_code=workflow_job_attempts_exhausted`、数据库 `finished_at=now()` 并清空
  worker/dispatch lease、retry/enqueue。取消优先：已请求取消且确认无副作用时进入
  cancelled。
- pending 取消直接进入 cancelled；claimed 且 handler 尚未开始时直接 cancelled；
  running 取消进入 cancel_requested 并保留 lease。cancel_requested 最终只能收敛为
  cancelled、实际 succeeded/failed 或 recovery_required。
- terminal 不再迁移。`release_candidate_reconcile` 只允许 Task
  `running|waiting_approval`；dispatcher 排除 paused/cancelled/failed/done。
  mark-running 发现 paused 时 `claimed -> pending` 并清 lease，Task resume 把相关
  pending job 的 `next_enqueue_at` 推进到数据库当前时间；发现 cancelled/failed/
  done 时收敛为 cancelled。Task cancelled 时按 `Task -> WorkflowJob.id` 顺序锁定
  并执行上述取消转移。

`side_effect_class` 只能由服务端 handler registry 根据 `job_type` 派生：

- `none`：stale claimed/running 在未取消时可安全回 pending；stale
  cancel_requested 进入 cancelled。
- `external_idempotent`：必须先查询相同远端 operation identity；明确
  succeeded/failed 时收敛，明确未执行或可附着到同一幂等 operation 时才回
  pending，unknown 进入 recovery_required。
- `external_uncertain`：running 后只接受明确远端 succeeded/failed；其余结果进入
  recovery_required，不自动重放。
- `cancel_requested` 覆盖两类 external stale 规则：不得再次调用原副作用；
  remote cancelled/not_started -> cancelled，remote succeeded -> succeeded，
  remote failed -> failed，remote running/unknown -> recovery_required。

M7-2 job registry 只允许：

```text
release_candidate_reconcile -> release_candidate -> none
```

Candidate POST 在创建 Candidate 与 Approval 的同一事务创建该 job：

```text
job_type=release_candidate_reconcile
resource_type=release_candidate
resource_id=<candidate UUID>
side_effect_class=none
max_attempts=3
```

job request canonical 固定包含
`schema_version=m7.workflow-job.release-candidate-reconcile.v1`、job/resource
身份、candidate request hash 和 approval id；其稳定 hash 写 `request_hash`，
`idempotency_key=release_candidate_reconcile:v1:<request_hash hex>`。

payload 精确为以下对象，六个字段全部 required，`additionalProperties=false`：

```json
{
  "schema_version": "m7.release-candidate-reconcile.payload.v1",
  "candidate_id": "UUID",
  "approval_id": "UUID",
  "expected_candidate_request_hash": "sha256:<64 lowercase hex>",
  "expected_binding_snapshot_sha256": "sha256:<64 lowercase hex>",
  "expected_pull_request_record_id": "UUID"
}
```

result 精确为以下对象，七个字段全部 required，`additionalProperties=false`：

```json
{
  "schema_version": "m7.release-candidate-reconcile.result.v1",
  "outcome": "valid | stale | terminal_noop",
  "candidate_status": "pending_approval | approved | rejected | published | stale | cancelled",
  "approval_status": "pending | approved | rejected | expired | cancelled",
  "pull_request_record_id": "UUID",
  "binding_snapshot_sha256": "sha256:<64 lowercase hex>",
  "checked_at": "RFC3339 UTC date-time"
}
```

`valid` 只对应 pending/pending 或 approved/approved；本次检测到漂移时
`outcome=stale`、candidate=stale，pending Approval 转 expired，已经 approved 的
Approval 保留 approved 历史；`terminal_noop` 只对应
rejected/published/stale/cancelled Candidate。payload/result 不含 clone URL、
credential ref 或 profile 内容。检测到漂移时 Candidate/Approval
原子转 stale/expired，Approval 同时写
`decided_by=system:release_candidate_freshness` 与数据库决策时间，但 job 自身
succeeded；该异步 job 不替代审批决策时的同步 freshness 校验。job ID 只进入
EventLog/测试证据，不加入调用方 CRUD API。

对仍为 `pending_approval|approved` 的 Candidate，以下任一 Approval freshness
失败都把 Candidate 标记 stale，job 返回 `outcome=stale`：

- `expires_at <= PostgreSQL now()`。
- `consumed_at IS NOT NULL`。
- Approval status 为 expired/cancelled。
- action、resource type/id 或 request hash 与 Candidate 不一致。

若此时 Approval 仍是 pending，则同步改为 expired 并写固定 system actor/time；
已经 approved/expired/cancelled 的 Approval 保留历史状态。Approval 缺失，或
Candidate/Approval 出现 pending/approved、rejected 决策不一致等违反原子事务的
组合时，job 进入 failed，写 `release_candidate_approval_state_invalid`，不静默
修复。Candidate 已是 rejected/published/stale/cancelled 时才返回
terminal_noop。

durable dispatcher 固定协议：

1. 新 job 初值为 `pending`、`next_enqueue_at=数据库 now()`、attempt/enqueue
   attempt 为 0、两类 lease 为空。
2. due 查询 join Task 并只接受 `running|waiting_approval`，同时满足
   `status=pending`、`attempt<max_attempts`、
   `next_retry_at IS NULL OR <= now()`、`next_enqueue_at<=now()`，且 dispatch
   lease 为空或过期；按 `next_enqueue_at,id` 执行 `FOR UPDATE SKIP LOCKED`。
3. reserve 短事务写 owner、`dispatch_lease_expires_at` 并先递增
   `enqueue_attempt`；提交后才 publish。Candidate POST 提交后的 best-effort
   dispatch 必须复用同一 reserve 入口。
4. broker message 只携带 `workflow_job_id`。publish success 按
   `id + status=pending + dispatch owner` 条件写 `last_enqueued_at`，把
   `next_enqueue_at` 推进到 redispatch 时间、清
   `last_enqueue_error_code` 和 lease；publish failure 使用相同条件写稳定错误码和
   指数退避。worker 已先 claim 时 finalize 必须 no-op。
5. enqueue 失败退避固定为
   `min(max_enqueue_backoff, enqueue_backoff * 2 ** (enqueue_attempt - 1))`；
   safe business retry 固定为
   `min(max_retry_backoff, retry_backoff * 2 ** max(attempt - 1, 0))`，M7-2 不加
   jitter。claim 时清空 dispatch lease、next enqueue 和 next retry。
6. worker 同时访问 Task/job/resource 时锁顺序固定为
   `Task -> WorkflowJob -> ProjectRepositoryBinding -> ReleaseCandidate ->
   Approval`；无锁 hint 只用于找到后续锁对象，锁后必须重验身份。dispatcher
   reserve 只锁 WorkflowJob，Binding PUT 只走
   `Binding -> Candidate(UUID 顺序) -> Approval(UUID 顺序)`，两者不得在同一事务
   反向获取 Task。Redis、Git、HTTP 或 handler 执行期不持有数据库行锁。

#### `environments`

- `project_id`
- `name`
- `environment_type`: staging/demo
- `status`
- `base_url`
- `env_profile_ref`
- `created_at`、`updated_at`
- 唯一约束：`(project_id, name)`

#### `remote_targets`

- `environment_id`
- `display_name`
- `target_type`
- `agent_id`
- `agent_endpoint`
- `credential_ref`
- `tls_fingerprint`
- `status`
- `agent_version`
- `capabilities_json`
- `last_heartbeat_at`
- `last_error_code`
- 唯一约束：`(environment_id, agent_id)`

API 响应隐藏 `credential_ref`，endpoint 只返回经过脱敏的展示值。

#### `ci_runs`

- `task_id`、`project_id`
- `pull_request_record_id`
- `provider`
- `external_run_id`
- `repository`
- `source_ref`
- `commit_sha`
- `status`
- `artifact_manifest_id`
- `workflow_revision`
- `idempotency_key`
- `started_at`、`finished_at`
- 唯一约束：provider/run id、Task/idempotency key
- webhook 状态幂等字段：event action/status、provider updated time、head SHA

#### `deployments`

- `task_id`、`project_id`
- `environment_id`、`remote_target_id`
- `ci_run_id`
- `release_plan_artifact_id`
- `approval_id`
- `release_version`
- `commit_sha`
- `image_ref`、`image_digest`
- `request_hash`
- `remote_operation_id`
- `status`
- `health_summary_json`
- `failure_code`
- `rollback_from`
- `idempotency_key`
- `started_at`、`finished_at`
- 唯一约束：environment/release version、Task/idempotency key
- `requested_by_actor`、`approved_by_actor`、`dispatched_by_agent_run_id`

#### `service_instances`

- `deployment_id`、`environment_id`、`remote_target_id`
- `service_name`
- `compose_project`
- `runtime_type`、`runtime_ref`
- `status`
- `health_url`
- `health_json`
- `last_health_check_at`
- 唯一约束：`(deployment_id, service_name)`

扩展 `approval_requests`：

- `resource_type`
- `resource_id`
- `request_hash`
- `expires_at`
- `consumed_at`

资源审批要求 `resource_type/resource_id/request_hash/expires_at` 同时存在；
`consumed_at` 只能用于已批准审批。Release candidate 审批固定为
`action=approve_release_candidate`、`risk_level=L2`。

扩展 `tool_calls`：

- `resumed_by_agent_run_id`
- 审批恢复和执行后的 audit 字段。

要求：

- M7 的 L2 release candidate 与 L3/L4 远端 Approval 必须保存 request hash。
- 审批过期、已消费、目标变化或 hash 变化均视为 stale。
- migration 支持 downgrade。
- API、ORM、Pydantic、OpenAPI 和数据库约束一致。
- `alembic check` 必须无差异。
- Celery task 只引用 `workflow_jobs.id`；CI/Deployment 行本身不充当临时队列。

### 7.5 实现 `modules/remote-agent`

建议目录：

```text
modules/remote-agent/
  README.md
  pyproject.toml
  uv.lock
  src/cloudhelm_remote_agent/
    __init__.py
    main.py
    config.py
    auth.py
    api/
      health.py
      deployments.py
      services.py
      operations.py
    schemas/
      heartbeat.py
      deployment.py
      service.py
      logs.py
    services/
      heartbeat_service.py
      deployment_service.py
      compose_service.py
      health_service.py
      log_service.py
      operation_store.py
    adapters/
      docker_compose.py
      control_plane_client.py
  tests/
```

Remote Agent 最小生产能力：

1. 启动健康检查和版本/capability 查询。
2. 周期性向 Platform API 提交签名心跳。
3. 接收经过认证的 staging deployment request。
   - machine credential 绑定 `remote_target_id + agent_id + key_id`。
   - 请求签名覆盖 method、path、timestamp、nonce 和 body SHA-256。
   - 服务端限制时间偏差并持久化 nonce/replay identity；过期、撤销、跨 target
     或重复请求必须拒绝。
   - 支持新旧 key 短暂重叠轮换，API 和日志只返回 key fingerprint。
4. 根据 `deployment_id + idempotency_key + request_hash` 防止重复执行。
5. 使用 SQLite operation store 保存 running/succeeded/failed 结果，进程重启后仍可
   查询历史操作。
6. 只操作 `/opt/cloudhelm/projects/<project-key>` 下的受控目录。
7. 校验 Compose：
   - 禁止 `privileged`。
   - 禁止 host network、host PID/IPC。
   - 禁止挂载 Docker socket。
   - 禁止任意 device、危险 capability 和受控根目录外 host path。
   - 只允许 CI manifest 中声明的 image digest。
8. 从远端预配置 env profile 读取 secret，部署请求只携带 profile ref。
9. 依次执行：
   - 写入 release metadata。
   - `docker compose config`
   - `docker compose pull`
   - 使用 registry/`RepoDigests` 和目标平台信息复核实际 digest
   - `docker compose up -d`
   - `docker compose ps`
   - HTTP `/health`
10. 所有命令使用参数数组、固定 profile、超时和输出上限。
11. 健康成功后更新 `current` 和 `rollback.json`；失败时保留诊断证据，不自动回滚。
12. 提供 service status、受限日志读取和 diagnostics。
13. 日志返回限制时间范围、行数和字节数，并执行 secret 脱敏。
14. 未提供任意 shell 或交互终端入口。
15. registry 登录凭据来自受控 `_FILE`/credential store，输出与 release metadata
    只保存 credential ref/fingerprint，不保存 secret。

### 7.6 实现 `modules/deployment-controller`

建议目录：

```text
modules/deployment-controller/
  README.md
  pyproject.toml
  uv.lock
  src/cloudhelm_deployment_controller/
    __init__.py
    schemas.py
    manifest_renderer.py
    manifest_policy.py
    remote_agent_client.py
    deployment_service.py
    health_policy.py
  tests/
```

职责：

- 验证 ReleasePlan。
- 从受控模板渲染 Compose 和 release metadata。
- 将镜像 ref 固定为 `image@sha256:...`。
- 生成稳定 manifest hash。
- 调用 Remote Agent。
- 读取 remote operation 和 health result。
- 返回结构化 DeploymentResult。

要求：

- 使用 Pydantic 和模板引擎 StrictUndefined。
- 模板根目录由服务端配置，API 和 Agent 不传任意模板路径。
- env profile 只使用引用。
- HTTP client 使用 TLS 校验、明确 connect/read timeout、大小限制和脱敏日志。
- endpoint 必须来自 RemoteTarget 服务端记录并经过 allowlist 校验。
- 不写 Platform 数据库；Platform API 是部署事务和事件边界。
- 不直接调用 SSH 部署。
- 网络超时后通过相同 idempotency key 查询 Remote Agent operation，禁止盲目
  重复执行 Compose。

### 7.7 扩展 Tool Gateway：CI、Deploy、Remote Control 与审批恢复

新增或更新：

```text
modules/tool-gateway/src/cloudhelm_tool_gateway/schemas/
  ci.py
  deploy.py
  remote.py
modules/tool-gateway/src/cloudhelm_tool_gateway/tools/
  ci_tool.py
  deploy_tool.py
  remote_control_tool.py
modules/tool-gateway/tests/
  test_m7_ci_tool.py
  test_m7_deploy_tool.py
  test_m7_remote_control_tool.py
  test_m7_approval_resume.py
```

M7 注册工具：

|工具|风险|审批|
|---|---:|---|
|`ci.trigger_workflow`|L2|否|
|`ci.get_workflow_status`|L0|否|
|`ci.get_job_logs`|L0|否|
|`ci.get_artifact_manifest`|L0|否|
|`ci.rerun_failed_job`|L2|否；只允许失败且可重跑的固定 job|
|`deploy.render_manifest`|L1|否|
|`deploy.deploy_staging`|L3|是|
|`deploy.get_release_status`|L0|否|
|`deploy.health_check`|L0|否|
|`deploy.rollback_request`|L3|是，仅生成请求|
|`remote.list_targets`|L0|否|
|`remote.service_status`|L0|否|
|`remote.stream_logs`|L0|否|
|`remote.collect_diagnostics`|L0|否；仅固定无副作用 profile|
|`remote.ssh_exec_readonly`|L1|是；目标必须显式启用 SSH 诊断|

`remote.ssh_exec_readonly` 只接受预定义 diagnostic profile，例如：

- `docker_ps`
- `compose_ps`
- `disk_usage`
- `systemd_status`

禁止自由 command 字符串；必须校验 SSH host key，私钥路径来自服务端配置。
服务端还必须使用 forced-command wrapper / 精确 sudoers，并关闭 PTY、转发和
user rc；加入 docker group 的账号不视为只读账号。

审批恢复要求：

1. 首次 `deploy.deploy_staging` 只创建 waiting ToolCall 和 ApprovalRequest。
2. Approval 保存精确 request hash。
3. 审批通过后，下一次 `run-next` 原子抢占原 waiting ToolCall。
4. 抢占事务提交后才调用 Deployment Controller。
5. 并发恢复只允许一个执行者。
6. 重复请求返回已有 running/succeeded 状态。
7. 审批目标、manifest、digest、环境或版本变化时返回 stale approval。
8. `resumed_by_agent_run_id` 和原请求 AgentRun 均进入审计。
9. 审批使用后写 `consumed_at`，禁止二次消费。

### 7.8 实现 Release / Deploy Agent

新增：

```text
modules/agent-runtime/src/cloudhelm_agent_runtime/agents/
  release_agent.py
modules/agent-runtime/src/cloudhelm_agent_runtime/prompts/
  release.md
modules/agent-runtime/src/cloudhelm_agent_runtime/schemas/
  release.py
modules/agent-runtime/tests/
  test_release_agent.py
  test_release_agent_tool_contract.py
```

要求：

- 输入必须包含最新 PullRequestRecord、CI manifest、environment、target、服务模板
  和最近健康 release。
- 校验 PR commit、CI commit 和 image digest 一致。
- 生成结构化 ReleasePlan、deployment risk 和 rollback candidate。
- 不读取或输出 secret 值。
- 通过 ToolCall 请求 CI、Deploy 和 Remote Control Tool。
- staging 部署必须返回 `needs_approval`。
- 只读状态和健康检查可以自动执行并审计。
- CI 失败、制品缺失、digest 不一致、Agent 离线时返回 blocked/failed 原因。
- 复用当前 Provider、HTTP SSE、完整 Task root conversation、稳定 schema/tools、
  有界重试和真实 usage。
- 成功步骤继续通过 Platform API savepoint 原子保存 AgentRun、conversation turn、
  ReleasePlan Artifact 和事件。

### 7.9 扩展 Orchestrator M7 状态机

新增或更新：

```text
modules/orchestrator/src/cloudhelm_orchestrator/state_machine.py
modules/orchestrator/src/cloudhelm_orchestrator/models.py
modules/orchestrator/tests/test_m7_state_machine.py
modules/platform-api/src/cloudhelm_platform_api/services/
  release_deployment_service.py
  release_deployment_context.py
modules/platform-api/src/cloudhelm_platform_api/schemas/release_deployment.py
modules/platform-api/tests/test_m7_release_deployment_api.py
packages/shared-contracts/openapi/cloudhelm.openapi.yaml
apps/control-console/src/shared/types/api.ts
apps/control-console/src/shared/types/events.ts
```

建议阶段：

```text
PullRequestCreated
  -> WaitingMergeApproval
  -> CIValidating
  -> ReleasePlanning
  -> WaitingDeployApproval
  -> Deploying
  -> VerifyingDeployment
  -> Monitoring
```

建议 next actions：

```text
request_release_candidate_approval
publish_release_candidate
trigger_ci
poll_ci
run_release_agent
request_deployment_approval
execute_deployment
verify_deployment
complete_m7_handoff
```

要求：

- candidate POST 只创建第一道 release candidate 审批；`remote-deployment/start`
  只消费 approved candidate 并选择 Environment/RemoteTarget，不直接发布或部署。
- 每次 `run-next` 只推进一个可审计步骤。
- CI 是异步外部状态；poll/webhook 更新后再推进 Release Agent。
- WaitingDeployApproval 期间禁止任何远端副作用。
- Deploying 前再次读取 Task、Approval、Deployment、RemoteTarget 和 CI 状态。
- CI 失败：Task 暂停在 CIValidating，保存失败报告和可重试动作。
- 部署失败：Deployment 为 failed，Task 暂停在 Deploying。
- 健康失败：Deployment 为 unhealthy，保存诊断和 rollback candidate。
- Agent 离线：进入可恢复阻塞，不自动切换 SSH 部署。
- pause/cancel 在远端 dispatch 前阻止副作用；dispatch 后记录 cancel requested，
  等 Remote Agent 返回终态。
- M7 成功只进入 Monitoring。
- 成功交接必须写 `MonitoringRegistered` 事件。

### 7.10 Platform API 远端发布工作流

M7-1 已落地：

```text
modules/platform-api/src/cloudhelm_platform_api/api/
  environments.py
  remote_targets.py
  remote_agents.py
  machine_auth.py
modules/platform-api/src/cloudhelm_platform_api/schemas/
  environment.py
  remote_target.py
modules/platform-api/src/cloudhelm_platform_api/services/
  environment_service.py
  remote_target_service.py
  machine_auth_service.py
  remote_agent_heartbeat_service.py
modules/platform-api/src/cloudhelm_platform_api/providers/
  remote_target_profile_provider.py
modules/platform-api/tests/
  test_m7_environment_remote_target_api.py
  test_m7_machine_auth_heartbeat.py
  test_m7_shared_contracts.py
```

M7-2 下一纵切新增：

```text
modules/platform-api/src/cloudhelm_platform_api/api/
  repository_bindings.py
  release_candidates.py
modules/platform-api/src/cloudhelm_platform_api/schemas/
  approval.py
  project_repository_binding.py
  release_candidate.py
  workflow_job.py
modules/platform-api/src/cloudhelm_platform_api/services/
  approval_service.py
  approval_domain_decision_service.py
  release_candidate_contract.py
  release_candidate_policy.py
  project_repository_binding_service.py
  release_candidate_service.py
  workflow_job_service.py
modules/platform-api/src/cloudhelm_platform_api/providers/
  repository_profile_provider.py
  workflow_queue.py
modules/platform-api/tests/
  test_m7_project_repository_binding_api.py
  test_m7_release_candidate_api.py
  test_m7_workflow_jobs.py
  test_m7_approval_decisions.py
```

后续 M7 纵切再新增：

```text
modules/platform-api/src/cloudhelm_platform_api/api/
  ci_runs.py
  release_deployment.py
  deployments.py
  remote_services.py
  remote_agent_operations.py
modules/platform-api/src/cloudhelm_platform_api/schemas/
  ci_run.py
  release_deployment.py
  deployment.py
  remote_service.py
modules/platform-api/src/cloudhelm_platform_api/services/
  ci_run_service.py
  ci_webhook_service.py
  release_deployment_service.py
  release_deployment_context.py
  deployment_service.py
  remote_agent_operation_service.py
  service_instance_service.py
  deployment_approval_service.py
  event_stream_service.py
modules/platform-api/src/cloudhelm_platform_api/providers/
  ci/
  remote/
modules/platform-api/tests/
  test_m7_ci_api.py
  test_m7_release_deployment_api.py
  test_m7_deployment_api.py
  test_m7_remote_agent_operations.py
  test_m7_remote_services_api.py
```

建议 API：

```text
POST /api/projects/{project_id}/environments
GET  /api/projects/{project_id}/environments
GET  /api/environments/{environment_id}

PUT  /api/projects/{project_id}/repository-binding
GET  /api/projects/{project_id}/repository-binding

POST /api/environments/{environment_id}/remote-targets
GET  /api/environments/{environment_id}/remote-targets
POST /api/remote-targets/{target_id}/test-connection

POST /api/remote-agents/heartbeat

GET  /api/tasks/{task_id}/ci-runs
GET  /api/ci-runs/{ci_run_id}
POST /api/webhooks/ci/gitea

POST /api/tasks/{task_id}/release-candidate
GET  /api/tasks/{task_id}/release-candidate

GET  /api/tasks/{task_id}/remote-deployment
POST /api/tasks/{task_id}/remote-deployment/start
POST /api/tasks/{task_id}/remote-deployment/run-next

GET  /api/projects/{project_id}/deployments
GET  /api/deployments/{deployment_id}
POST /api/deployments/{deployment_id}/health-check
POST /api/deployments/{deployment_id}/rollback-request

GET  /api/environments/{environment_id}/services
GET  /api/services/{service_id}/status
GET  /api/services/{service_id}/logs
GET  /api/services/{service_id}/logs/stream
POST /api/services/{service_id}/collect-diagnostics
```

关键规则：

- M7-2 的 candidate POST 是第一道审批的唯一创建入口，请求体必须是 `{}`；
  target ref、binding snapshot/hash、idempotency key 和 request hash 均由服务端
  派生。
- Candidate、L2 Approval 与 `release_candidate_reconcile` WorkflowJob 在同一
  PostgreSQL 事务创建；提交后使用 durable dispatcher 的同一 reserve 入口
  best-effort 投递，失败由周期扫描补投。该 job 无外部副作用且不替代 approve/
  reject 时的同步 freshness 校验。
- `remote-deployment/start` 在后续纵切只接受 `environment_id`，要求已有 approved
  candidate，且不重复创建 candidate；commit、image 和 target 由服务端从已批准
  资源派生。
- WorkflowJob 不提供调用方 CRUD API，只能由受控 service/Orchestrator 创建。
- `repository-binding` 请求只接受服务端配置的 `profile_key`；URL、token、
  workflow path、remote name 和 ref prefix 由 profile 派生。
- RemoteTarget endpoint 和 credential 来自服务端受控配置。
- heartbeat 使用独立 machine authentication dependency。
- CI webhook 校验签名、delivery id 和 repository。
- CI、部署、健康和日志网络调用期间不持有数据库事务。
- 每个外部步骤先短事务抢占，再执行副作用，最后独立事务写终态。
- CIRun、Deployment、ToolCall 和 Artifact 都必须使用幂等键。
- 服务日志只返回受限时间窗和字节数。
- SSE 沿用数据库 EventLog 轮询/tailing 与 `Last-Event-ID` 重连；必须验证连接
  建立后新增的 CI/部署/心跳事件能实时到达，而不只验证历史回放。
- API 永远不返回 runner token、registry token、Remote Agent machine secret、SSH key、
  env secret 或远端真实 secret 文件路径。

建议稳定错误码：

- `repository_profile_not_found`
- `repository_profile_configuration_invalid`
- `repository_profile_unusable`
- `repository_binding_not_found`
- `repository_binding_conflict`
- `repository_binding_inactive`
- `m6_pull_request_required`
- `m6_pull_request_creator_required`
- `release_candidate_not_found`
- `release_candidate_conflict`
- `release_candidate_stale`
- `approval_expired`
- `approval_consumed`
- `approval_request_hash_mismatch`
- `approval_self_decision_forbidden`
- `approval_action_reserved`
- `workflow_job_not_found`
- `workflow_job_conflict`
- `workflow_job_not_claimable`
- `workflow_job_lease_lost`
- `workflow_broker_unavailable`
- `ci_run_not_ready`
- `ci_commit_mismatch`
- `ci_artifact_untrusted`
- `remote_agent_offline`
- `deployment_approval_required`
- `deployment_approval_stale`
- `deployment_already_running`
- `image_digest_mismatch`
- `remote_operation_timeout`
- `health_check_failed`

### 7.11 远端部署配置和安装文件

创建：

```text
infra/remote-agent/
  README.md
  cloudhelm-remote-agent.service
  remote-agent.env.example
  install.sh
infra/staging/
  sample-repo-python.compose.yml.j2
  sample-repo-python.env.schema.json
  README.md
tests/e2e/
  test_m7_remote_deploy.py
  README.md
```

要求：

- systemd 使用专用用户。
- 服务环境文件权限为 `0600`。
- `ProtectSystem`、`PrivateTmp`、`NoNewPrivileges`、`ReadWritePaths` 等 hardening
  选项按 Docker socket 边界配置。
- 文档明确 Docker group/socket 具有高权限，Remote Agent 只用于 staging/demo。
- 远端 secret profile 预先放入 `/etc/cloudhelm/projects/...`，不进入 Git。
- Compose 模板只引用 CI image digest，不包含 `build:`。
- sample service 数据使用命名卷，升级时不得删除。
- release 目录保存：
  - rendered Compose。
  - release metadata。
  - CI manifest 摘要。
  - health result。
  - `rollback.json`。
- 安装、升级、卸载和日志查看命令写入 README。
- E2E 使用专用 demo project，并提供部署后清理步骤。

### 7.12 控制台远端环境和部署展示

建议新增：

```text
apps/control-console/src/features/
  environments/
  remote-deployment/
  remote-services/
  remote-logs/
apps/control-console/src/shared/types/
  ci.ts
  deployment.ts
  remote.ts
apps/control-console/tests/
  m7DeploymentActionPolicy.test.ts
  m7DeploymentEvidence.test.ts
  m7EventTypes.test.ts
  m7RemoteStatus.test.ts
```

展示内容：

- Environment 名称、类型和 base URL。
- Remote Target、Agent 状态、版本、capability 和 heartbeat age。
- release candidate 审批状态。
- CI run、job 状态、commit、报告和 image digest。
- ReleasePlan、risk、rollback candidate 和 manifest hash。
- Deployment 状态、Compose project、remote operation、开始/结束时间。
- 每个服务的 runtime status、health、版本和 image digest。
- 受限远端日志和 diagnostics。
- 统一 Approval Panel 中的 release candidate 与 deployment 审批。

交互要求：

- 只有后端 `next_action` 允许时启用“启动发布”或“推进下一步”。
- 页面不接收任意 commit、image、host、token、SSH key、Compose 路径或命令。
- 部署审批卡片展示环境、commit、digest、manifest hash 和风险。
- 日志按纯文本渲染，不解释 HTML。
- offline、degraded、failed、unhealthy 和 stale approval 使用明确错误状态。
- SSE 高频事件保留当前内容，避免整块闪烁。
- 继续使用 Gemini 式浅色阅读流。
- 1280×720、1024×768、375×812 无 document 水平溢出。

### 7.13 事件、OpenAPI、配置、版本和文档同步

更新：

```text
云舵 CloudHelm 毕设设计书.md
packages/shared-contracts/openapi/cloudhelm.openapi.yaml
packages/shared-contracts/schemas/events/task-event.schema.json
docs/01-architecture/
docs/03-modules/
docs/04-agents/
docs/05-tool-layer/
docs/06-workflows/01-pr-to-remote-deploy.md
docs/07-data/
docs/08-api/
docs/09-control-console/
docs/10-security/
docs/12-deployment/
docs/15-detailed-design/
README.md
.env.example
infra/README.md
PROJECT_PROGRESS.md
```

新增事件至少包括：

- `RepositoryBindingConfigured`
- `EnvironmentCreated`
- `RemoteTargetRegistered`
- `RemoteTargetConnectionSucceeded`
- `RemoteTargetConnectionFailed`
- `RemoteAgentHeartbeat`
- `RemoteAgentOnline`
- `RemoteAgentOffline`
- `RemoteAgentRecovered`
- `ReleaseCandidateApprovalRequested`
- `ReleaseCandidateApproved`
- `ReleaseCandidateRejected`
- `ReleaseCandidatePublished`
- `WorkflowJobQueued`
- `WorkflowJobDispatchDeferred`
- `WorkflowJobStarted`
- `WorkflowJobRetryScheduled`
- `WorkflowJobSucceeded`
- `WorkflowJobCancelled`
- `WorkflowJobRecoveryRequired`
- `CIRunTriggered`
- `CIRunStarted`
- `CIRunPassed`
- `CIRunFailed`
- `CIArtifactPublished`
- `ReleasePlanCreated`
- `DeploymentApprovalRequested`
- `DeploymentRequested`
- `DeploymentStarted`
- `DeploymentStepUpdated`
- `DeploymentHealthy`
- `DeploymentUnhealthy`
- `DeploymentFailed`
- `ServiceInstanceRegistered`
- `ProjectServiceStatusChanged`
- `MonitoringRegistered`

heartbeat 高频上报只更新 `last_heartbeat_at`；首次上线、离线、恢复或超过记录
间隔时再写 EventLog，避免事件风暴。

环境变量至少覆盖：

```text
CLOUDHELM_CI_PROVIDER
CLOUDHELM_GITEA_BASE_URL
CLOUDHELM_GITEA_TOKEN
CLOUDHELM_GITEA_WEBHOOK_SECRET
CLOUDHELM_CI_ARTIFACT_MAX_BYTES
CLOUDHELM_CI_POLL_INTERVAL_SECONDS
CLOUDHELM_REGISTRY_BASE_URL
CLOUDHELM_REGISTRY_CREDENTIAL_REF
CLOUDHELM_REPOSITORY_PROFILES
CLOUDHELM_REPOSITORY_PROFILES_FILE
CLOUDHELM_REPOSITORY_CREDENTIALS
CLOUDHELM_RELEASE_CANDIDATE_APPROVAL_TTL_SECONDS
CLOUDHELM_WORKFLOW_QUEUE_NAME
CLOUDHELM_WORKFLOW_MAINTENANCE_QUEUE_NAME
CLOUDHELM_WORKFLOW_JOB_LEASE_SECONDS
CLOUDHELM_WORKFLOW_JOB_HEARTBEAT_SECONDS
CLOUDHELM_WORKFLOW_DISPATCH_INTERVAL_SECONDS
CLOUDHELM_WORKFLOW_DISPATCH_LEASE_SECONDS
CLOUDHELM_WORKFLOW_BROKER_PUBLISH_TIMEOUT_SECONDS
CLOUDHELM_WORKFLOW_REDISPATCH_AFTER_SECONDS
CLOUDHELM_WORKFLOW_ENQUEUE_BACKOFF_SECONDS
CLOUDHELM_WORKFLOW_MAX_ENQUEUE_BACKOFF_SECONDS
CLOUDHELM_WORKFLOW_RETRY_BACKOFF_SECONDS
CLOUDHELM_WORKFLOW_MAX_RETRY_BACKOFF_SECONDS
CLOUDHELM_WORKFLOW_RECLAIM_INTERVAL_SECONDS
CLOUDHELM_WORKFLOW_BATCH_SIZE
CLOUDHELM_WORKFLOW_SOFT_TIME_LIMIT_SECONDS
CLOUDHELM_WORKFLOW_HARD_TIME_LIMIT_SECONDS
CLOUDHELM_WORKFLOW_VISIBILITY_TIMEOUT_SECONDS
CLOUDHELM_REMOTE_TARGET_PROFILES_FILE
CLOUDHELM_REMOTE_TARGET_PROFILES
CLOUDHELM_REMOTE_AGENT_CREDENTIALS
CLOUDHELM_REMOTE_AGENT_TIMESTAMP_TOLERANCE_SECONDS
CLOUDHELM_REMOTE_AGENT_NONCE_TTL_SECONDS
CLOUDHELM_REMOTE_AGENT_OFFLINE_TIMEOUT_SECONDS
CLOUDHELM_REMOTE_AGENT_HEARTBEAT_EVENT_INTERVAL_SECONDS
CLOUDHELM_REMOTE_AGENT_NEXT_HEARTBEAT_SECONDS
CLOUDHELM_REMOTE_AGENT_HEARTBEAT_MAX_BODY_BYTES
CLOUDHELM_REMOTE_AGENT_CA_BUNDLE
CLOUDHELM_REMOTE_AGENT_CONNECT_TIMEOUT_SECONDS
CLOUDHELM_REMOTE_AGENT_READ_TIMEOUT_SECONDS
CLOUDHELM_M7_COMPOSE_TEMPLATE_ROOT
CLOUDHELM_M7_STAGING_ONLY
```

M7-2 默认值固定为：

```text
CLOUDHELM_RELEASE_CANDIDATE_APPROVAL_TTL_SECONDS=86400
CLOUDHELM_WORKFLOW_QUEUE_NAME=cloudhelm.workflow
CLOUDHELM_WORKFLOW_MAINTENANCE_QUEUE_NAME=cloudhelm.workflow.maintenance
CLOUDHELM_WORKFLOW_JOB_LEASE_SECONDS=90
CLOUDHELM_WORKFLOW_JOB_HEARTBEAT_SECONDS=20
CLOUDHELM_WORKFLOW_DISPATCH_INTERVAL_SECONDS=5
CLOUDHELM_WORKFLOW_DISPATCH_LEASE_SECONDS=15
CLOUDHELM_WORKFLOW_BROKER_PUBLISH_TIMEOUT_SECONDS=5
CLOUDHELM_WORKFLOW_REDISPATCH_AFTER_SECONDS=60
CLOUDHELM_WORKFLOW_ENQUEUE_BACKOFF_SECONDS=1
CLOUDHELM_WORKFLOW_MAX_ENQUEUE_BACKOFF_SECONDS=60
CLOUDHELM_WORKFLOW_RETRY_BACKOFF_SECONDS=5
CLOUDHELM_WORKFLOW_MAX_RETRY_BACKOFF_SECONDS=300
CLOUDHELM_WORKFLOW_RECLAIM_INTERVAL_SECONDS=30
CLOUDHELM_WORKFLOW_BATCH_SIZE=50
CLOUDHELM_WORKFLOW_SOFT_TIME_LIMIT_SECONDS=840
CLOUDHELM_WORKFLOW_HARD_TIME_LIMIT_SECONDS=900
CLOUDHELM_WORKFLOW_VISIBILITY_TIMEOUT_SECONDS=1800
```

Settings 必须验证：

```text
2 * job heartbeat < job lease
reclaim interval < job lease
2 * broker publish timeout < dispatch lease
dispatch interval < dispatch lease
redispatch after > dispatch lease
enqueue backoff <= max enqueue backoff
retry backoff <= max retry backoff
soft time limit < hard time limit < visibility timeout
visibility timeout >= hard time limit + job lease
```

Remote Agent 配置至少覆盖：

```text
CLOUDHELM_REMOTE_AGENT_PLATFORM_API_BASE_URL
CLOUDHELM_REMOTE_AGENT_TARGET_ID
CLOUDHELM_REMOTE_AGENT_AGENT_ID
CLOUDHELM_REMOTE_AGENT_KEY_ID
CLOUDHELM_REMOTE_AGENT_CREDENTIAL_FILE
CLOUDHELM_REMOTE_AGENT_PLATFORM_CA_BUNDLE
CLOUDHELM_REMOTE_AGENT_HEARTBEAT_SECONDS
CLOUDHELM_REMOTE_AGENT_REQUEST_TIMEOUT
CLOUDHELM_REMOTE_AGENT_VERSION
CLOUDHELM_REMOTE_AGENT_CAPABILITIES
```

M7-1 的 Remote Agent 只包含只读 runtime 端点和 heartbeat，因此 project root、
state path、env profile、operation timeout 与最大命令输出等配置留到后续真实
deployment operation 切片再引入。machine secret 只通过 credential file 注入；
Platform API 侧 secret 映射只写占位引用，示例文件不保存真实值。

版本同步到 `0.6.0`，更新所有受影响模块、lock 文件、health/version 测试和文档。

### 7.14 子任务验证、证据与 Roadmap 映射

|计划任务|最低验证命令|验收证据|Roadmap 位置|
|---|---|---|---|
|7.1 M7-0 设计闭环|Markdown 链接、UTF-8/BOM、冲突关键词、`git diff --check`|09 细化设计、资料归档、设计书/API/Data/Workflow/Testing 同步|只勾选 M7-0 设计项，不勾任何实现项|
|7.3 shared contracts|Agent Runtime schema tests、JSON Schema 元校验、Remote Agent OpenAPI contract test|ReleasePlan、CI manifest、DeploymentResult、Heartbeat、Tool schema|“Release / Deploy Agent”“Tool Gateway”相关项待代码完成后勾选|
|7.4 data/migration|`alembic upgrade/check/downgrade/upgrade`、repository/service pytest|表、约束、索引、lease、single-use approval、无开发库污染|“部署记录、环境与目标”基础子项|
|7.10 M7-1 API/heartbeat|Platform API 黑盒/白盒、machine auth/replay、EventLog 与事件 Schema 测试；项目/环境 SSE 留到后续 M7|Environment、RemoteTarget、online/offline/recovery EventLog、credential 不泄露|“实现 Environment / RemoteTarget API、machine authentication 和 Remote Agent online/offline/recovery 心跳”|
|7.2 CI|Gitea provider tests、workflow 静态检查、真实 CI run smoke|run/job/log/artifact ID、精确 commit、JUnit、安全、SBOM、digest|“CI 运行测试、安全扫描和构建”|
|7.5 Remote Agent|模块 pytest、SQLite restart、Compose policy、真实 Linux smoke|systemd、capability、operation、RepoDigests、服务/日志结果|“实现 Remote Agent...”|
|7.6 Controller|模块 pytest、StrictUndefined、TLS client、timeout/idempotency|rendered manifest hash、危险配置拒绝、DeploymentResult|“实现 Deployment Controller”|
|7.7 Tool Gateway|Tool schema/risk/approval/resume 并发测试|L0-L3 固定风险、waiting ToolCall、single-use approval、审计|“实现 Deploy Tool 与远端控制工具”|
|7.8 Release Agent|Agent Runtime Pydantic、tool manifest、conversation tests|独立 AgentRun、ReleasePlan SHA、digest mismatch 阻断|“实现 Release / Deploy Agent”|
|7.9 Orchestrator|状态机路径/非法迁移/失败恢复测试|每步一个事件、CI/部署异步、最终 Monitoring|“编排 CI/CD 与远端部署流程”|
|7.12 Console|Node tests、build、真实浏览器桌面/移动 QA|CI、审批、部署、心跳、服务、受限日志截图|“控制台展示部署与远端状态”|
|7.11/E2E|Compose config、真实 CI、远端 Linux E2E、清理检查|manifest、ReleasePlan、Approval、DeploymentResult、health、timeline|M7 全部复选框满足后勾选阶段|

每个子任务只有在对应代码、黑盒/白盒测试、文档、进度和证据均完成后才允许
勾选 Roadmap；“目录已创建”“接口返回 200”或测试 fake 均不构成完成证据。

## 8. 黑盒测试

至少覆盖：

1. 创建 staging Environment，并拒绝非法 environment type。
2. 注册受控 RemoteTarget，API 不泄露 credential。
3. 合法 Remote Agent HMAC credential 可上报心跳；错误 key/signature、错误 target
   和重放请求被拒绝。
4. 心跳超时后 Target 变为 offline，恢复后回到 online。
5. 缺少 M6 PullRequestRecord、质量证据或已审批计划时禁止启动 M7。
6. candidate POST 只接受空对象；target ref、binding snapshot/hash、
   idempotency key 和 request hash 均由服务端派生。
7. candidate 与第一道 Approval 原子创建；顺序/并发重复返回同一资源，hash 漂移
   返回 409。
8. release candidate 审批前不发布 branch、不触发 CI、不创建外部副作用 job。
9. CI 检出精确 commit，真实执行 test/security/build。
10. CI 测试、安全或构建失败时不生成可部署 Artifact。
11. CI manifest 的 commit 或 digest 与 PR record 不一致时 Release Agent 阻断。
12. Release Agent 生成真实 ReleasePlan。
13. 首次 `deploy.deploy_staging` 只产生 L3 Approval，不触发远端操作。
14. 审批拒绝、过期或 hash 变化时远端保持不变。
15. 审批通过并显式推进后，远端只执行一次部署。
16. 网络超时后用相同 idempotency key 查询已有 operation，不重复 `compose up`。
17. Remote Agent 执行真实 Compose 并返回服务状态。
18. `/health` 2xx 后 Deployment 进入 healthy，Task 进入 Monitoring。
19. `/health` 失败时 Deployment 为 unhealthy，保存日志与 rollback candidate。
20. Remote Agent 离线时部署阻塞，SSH fallback 只执行预定义只读诊断。
21. 控制台通过 SSE 展示 CI、审批、部署、心跳、服务和健康状态。
22. 控制台可查看受限远端日志。
23. Task 在 M7 成功后仍为 Monitoring，不提前进入 Done。
24. 一次真实远端 Linux 主机 E2E 完成并保存证据。

## 9. 白盒测试

至少覆盖：

- ReleasePlan、DeploymentResult、CI manifest、Heartbeat 和 RemoteOperation schema。
- Release Agent 缺字段、非法 enum、commit/digest 断裂和 secret 泄露检测。
- M7 所有普通 Agent 的稳定输出 schema/tools 前缀。
- Task root conversation、approval context 和 tool call/output 配对。
- M7 状态机正常、非法迁移、CI 失败、审批拒绝、部署失败和健康失败。
- Environment/Target/CIRun/Deployment/Service repository 分页、归属和唯一约束。
- RepositoryBinding profile-only 输入、binding snapshot/hash、candidate/approval
  原子性、幂等 PUT 与 Candidate POST 并发串行化，以及 binding/PR 漂移失效。
- WorkflowJob 顺序/并发 claim、lease owner、heartbeat、dispatch lease、broker
  失败补投、reserve/publish/finalize 三个崩溃窗口、指数退避和旧 owner late
  result 拒绝。
- pending/claimed/running 的取消转移、Task pause/cancel 与 claim 竞态，以及
  `recovery_required` 清 lease、`finished_at=null` 和阻塞同资源新 job。
- `none`、`external_idempotent`、`external_uncertain` 三类 stale reclaim；M7-2
  真实 handler 必须由 Candidate POST 生产事务触发，不能只在测试中直接造 job。
  PostgreSQL/migration/worker 集成只创建数据库 CHECK 允许的真实 `none` job；
  另外两类只测试纯 StalePolicy/handler registry，待后续 migration 扩展真实
  handler 映射后再补数据库集成。
- migration upgrade/downgrade 和事务回滚。
- Webhook 签名、delivery id 重放和外部 run id 幂等。
- CI artifact 大小、SHA、媒体类型和 commit provenance。
- Tool Gateway Agent allowlist、风险等级和 approval resume 并发。
- Approval target/hash/expiry/single-use。
- Deployment Controller 模板 StrictUndefined、digest 固定和危险 Compose 配置拒绝。
- Remote Agent 路径穿越、symlink、危险 volume、docker.sock、privileged 和 host network。
- Remote Agent operation SQLite 幂等、进程重启恢复、超时和输出截断。
- heartbeat 时间戳、签名、离线判断和事件降频。
- service status、日志时间窗、行数、字节数和脱敏。
- SSH diagnostic profile 白名单和 host key 校验。
- 前端 next_action、审批策略、SSE 去重、日志纯文本和请求竞态。
- CI workflow AST/YAML 检查，确认无部署命令。

## 10. 验证命令

```powershell
cd modules/remote-agent
uv lock --check
uv run pytest -q

cd ..\deployment-controller
uv lock --check
uv run pytest -q

cd ..\tool-gateway
uv lock --check
uv run pytest -q

cd ..\agent-runtime
uv lock --check
uv run pytest -q

cd ..\orchestrator
uv lock --check
uv run pytest -q

cd ..\platform-api
uv lock --check
uv run alembic downgrade 20260714_0006
uv run alembic upgrade head
uv run alembic check
uv run pytest -q

cd ..\..\examples\sample-repo-python
uv lock --check
uv run pytest -q
docker compose config
docker build --tag cloudhelm/sample-repo-python:m7-smoke .

cd ..\..\apps\control-console
npm.cmd test
npm.cmd run build
```

CI/部署配置：

```powershell
docker compose -f infra/ci/docker-compose.ci.yml config
docker compose -f infra/ci/docker-compose.ci.yml up -d
docker compose -f infra/ci/docker-compose.ci.yml ps
```

真实远端验证：

```powershell
ssh $env:CLOUDHELM_M7_REMOTE_SSH "systemctl is-active cloudhelm-remote-agent"
ssh $env:CLOUDHELM_M7_REMOTE_SSH "docker compose version"
uv run pytest -q tests/e2e/test_m7_remote_deploy.py -m remote
```

补充门禁：

- FastAPI OpenAPI 与共享 YAML 反序列化后精确一致。
- Remote Agent OpenAPI 与共享契约精确一致。
- 解析全部 JSON Schema，并校验代表性 Agent、CI、Deployment、Remote 对象。
- CI workflow 静态检查确认没有部署或 SSH 命令。
- image digest、CI commit、PR commit 和 ReleasePlan hash 全链一致。
- 浏览器检查 1280×720、1024×768、375×812。
- secret scan。
- TODO/FIXME/NotImplemented/空 `pass` 扫描。
- 普通生产源码 300 行、复杂文件 400 行检查。
- `git diff --check`。
- 本地 CI、Platform、sample workspace 和远端 demo 目录分别检查残留制品和凭据。
- 真实 E2E 保存 CI manifest、ReleasePlan、DeploymentResult、health、日志摘要和
  timeline。

## 11. 文档、进度与 Git

每完成一个可验证小步：

1. 更新 `PROJECT_PROGRESS.md`，记录环境、命令、结果、缺陷闭环和剩余风险。
2. 满足完成判定后，在总排期勾选对应 M7 子项。
3. API、schema、状态机、Tool、Agent、远端协议、安全或配置变化同步相关文档。
4. 检查 `git status --short`、`git diff --stat` 和关键文件 diff。
5. 按可验证粒度提交中文 commit。
6. push 当前 M7 功能分支。
7. M7 全部通过后合并回 `dev` 并推送。
8. 从 `dev` 合并到 `main` 前重新执行完整验证；如发布则使用 `v0.6.0`。
9. M7 完成后把本文件重写为 M8 详细计划。

建议提交粒度：

- `docs: 完成 M7 CI 与远端部署细化设计`
- `feat: 新增远端环境和部署数据模型`
- `feat: 新增 Remote Agent`
- `feat: 新增 Deployment Controller`
- `feat: 新增 CI Deploy 和 Remote Control 工具`
- `feat: 新增 Release Deploy Agent 与 M7 状态机`
- `feat: 接入远端发布 API 和控制台`
- `test: 补充 M7 远端部署黑盒白盒测试`
- `docs: 同步 M7 进度版本与验收记录`

## 12. M7 完成判定

只有全部满足才算 M7 完成：

- 存在一个真实 Gitea Actions CI run。
- CI 对 M6 精确 commit 完成 test/security/build/artifact。
- CI workflow 不包含任何远端部署动作。
- CI manifest、image digest、PullRequestRecord 和 ReleasePlan 证据一致。
- Release / Deploy Agent 有生产实现、结构化输出和测试。
- Deploy Tool、Remote Control Tool 和审批恢复语义真实落地。
- Deployment Controller 有真实模板渲染、远端调用和健康检查。
- Remote Agent 以 systemd 服务运行，能上报心跳、执行 Compose、返回状态和日志。
- staging 部署在 L3 审批前没有远端副作用。
- 审批后 sample repo 真正在远端 Linux 主机运行。
- `/health` 成功，Deployment 为 healthy，ServiceInstance 状态正确。
- 控制台展示 CI、release、审批、部署、远端状态、健康和日志。
- Task 最终进入 Monitoring。
- migration、全部模块测试、CI smoke、远端 E2E、OpenAPI、JSON Schema、前端构建
  和静态门禁全部通过。
- roadmap、`PROJECT_PROGRESS.md` 和下一阶段 `PROJECT_PLAN.md` 已同步。
- 已按小步提交并推送功能分支和 `dev`。

## 13. 风险与阻塞

- 真实远端主机缺失：完成代码和本地集成测试后保持 M7 阻塞，直到真实 E2E。
- registry 网络或 TLS 配置失败：修复可信 registry 链路；不得改用未校验可变 tag。
- Gitea runner 不稳定：记录真实 run/job 日志，修复 runner 配置后重跑。
- M6 commit 与远端仓库历史不一致：让 Project 的 M6 workspace 从受控 Gitea
  baseline clone，禁止 force push 覆盖历史。
- CI artifact 下载失败：保留 CIRun 和错误事件，不生成 ReleasePlan。
- Remote Agent machine credential、TLS CA 或时间偏差错误：保持
  offline/degraded，部署阻塞。
- Docker socket 权限较高：限定 staging/demo、专用用户、命令 allowlist、systemd
  hardening 和独立主机。
- Remote Agent 网络超时但远端操作已执行：依靠 operation store 和相同幂等键查询，
  禁止盲目重复部署。
- Compose 模板或 env profile 缺失：Deployment 进入 failed，不生成临时默认 secret。
- 健康检查失败：保存诊断和 rollback candidate，不自动回滚。
- 远端日志含敏感信息：服务端脱敏、截断并限制时间窗，控制台按纯文本展示。
- Approval 并发或资源变化：行锁、request hash、expires/consumed 字段阻止重复执行。
- CI/Deployment 长操作：数据库事务只负责抢占和终态写入，网络操作发生在事务外。
- M7 schema/tools 扩展造成缓存冷启动：记录一次预期冷启动，后续 turn 验证缓存恢复。
- 完整 Prometheus/Loki/Alertmanager 尚未接入：M7 只提供心跳、服务状态、健康和
  受限日志，M8 再完成监控告警。
