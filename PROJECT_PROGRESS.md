# PROJECT_PROGRESS.md

本文件记录 CloudHelm 每次设计、实现、测试、部署和范围调整的进度。每完成一个可验证小步后必须更新。

## 2026-07-16（M7-2D Git 收口并进入 M7-2E）

### 已完成

- 已将 M7-2D migration、ORM、repository、严格共享契约、评审修复、测试、文档、
  Roadmap、进度和 M7-2E 详细计划提交为 `db16a3d`：
  `feat: 完成 M7-2D CI 与部署数据底座`。
- 已 push 到
  `origin/feature/m7-remote-deploy-closure`，远端功能分支更新到 `db16a3d`。
- 常规 Git Credential Manager push 返回 HTTP 403；按既有仓库处理方式只对本次
  命令使用当前 `gh` token 的临时 `http.extraheader`，未修改 remote 或持久化
  credential。
- 当前执行指针已进入 M7-2E 受控 candidate ref、精确 SHA 回读、唯一 Gitea
  `workflow_dispatch` 和 CIRun run identity。

### 进行中

- 按 `PROJECT_PLAN.md` 执行 M7-2E 文档/资料冻结和 WSL Gitea fixture 预检。

### 阻塞与风险

- 正式 Ops Hub installation、runner、CI completion/artifact、ReleasePlan、第二道
  Approval API 和远端部署仍未交付。
- M7-2E 必须继续留在当前功能分支，不向 `main` 合并。

### 下一步

1. 更新 Gitea 1.26.4 dispatch/run API 官方资料归档。
2. 冻结 publish/dispatch 两段 external WorkflowJob 与恢复契约。
3. 新增 `20260716_0010` 和 WSL 隔离 Gitea 测试 fixture。

### 涉及文件

- `PROJECT_PROGRESS.md`
- `PROJECT_PLAN.md`
- M7-2D 提交 `db16a3d`

### 验证

- `git diff --cached --check` 通过。
- 提交包含 42 个文件，`9169 insertions, 439 deletions`。
- push 输出：
  `f4f16bb..db16a3d feature/m7-remote-deploy-closure`。

## 2026-07-16（M7-2D CI/部署数据底座实现与评审闭环）

### 已完成

- 完成 `20260716_0009`：
  - 创建 `ci_runs`、`deployments`、`service_instances`。
  - 增加第二道 deployment Approval 组合门禁与资源 action 非空门禁。
  - 保持 `20260716_0008` 历史 migration 不变。
- 完成三表 SQLAlchemy ORM、只负责持久化/查询/稳定分页/行锁的 repository、
  严格 Pydantic Record 和 Draft 2020-12 共享 JSON Schema。
- 根据独立评审完成缺陷闭环：
  - 修复 provider event 半组字段和 failed Deployment 空 `failure_code` 的 SQL
    三值逻辑绕过。
  - `running/passed` CIRun 必须具有 `external_run_id`。
  - `rollback_requested` 必须具有 L3 Approval 投影、approved actor、remote
    operation、started/finished、health summary 和两项回滚引用；禁止自引用，
    测试使用历史 healthy Deployment。
  - OCI `image_ref` 拒绝 URL scheme、userinfo 和多重 `@`；health URL 拒绝
    userinfo。
  - Deployment/Service 健康对象最多 32 个小写受控 key，value 只允许最长 512
    字符 string、number、boolean 或 null，并拒绝凭据、敏感字段和
    raw logs/stdout/stderr/log。
  - Pydantic 与共享 JSON Schema 同步加入 `allOf/if/then` 生命周期条件。
- 补齐测试：
  - JSONB literal null、SQL 三值逻辑、敏感 health key、嵌套/超长健康值。
  - migration 字段类型、nullable、server default、索引 unique/predicate/列顺序
    与完整 FK delete rule。
  - provider run、Deployment Approval、Remote operation 三个部分唯一索引竞争。
  - 两个真实 PostgreSQL Session 的 `FOR UPDATE` 锁等待。
  - `ServiceInstanceRepository.create_many()` 冲突后整批回滚。
  - 从合法 Record 注入敏感额外字段，并同时验证 Pydantic 与 JSON Schema 拒绝。
- 同步总设计书、数据库总表、三张逐表文档、模块/README、测试矩阵、M7 细化设计
  和 Roadmap；版本继续保持 `0.5.1`。

### 进行中

- M7-2D 已满足实现与验证完成判定，正在执行 Git 复查、提交和 push 收口。
- 下一执行切片进入 M7-2E：受控 candidate ref 发布、`git ls-remote --refs`
  精确 SHA 回读、唯一 Gitea `workflow_dispatch` 和 CIRun run identity。

### 阻塞与风险

- M7-2D 仍只是权威数据底座，不包含 candidate ref push、真实 Gitea CI、
  ReleasePlan、第二道审批 API、Deployment Controller、Remote Agent operation
  或生产事件。
- 历史 healthy rollback candidate、Approval 状态/消费、父子 Task/Project/
  Environment/Target/digest 一致性属于跨行规则，后续 service 必须在规定锁序内
  重验，不能只依赖单行 CHECK。
- Platform API 全量仍有 2 条既有 Pydantic alias warning；本切片未改变其来源，
  后续单独清理。

### 下一步

1. 复查 M7-2D `git diff --stat`、关键 migration/ORM/schema/test diff、UTF-8、
   Markdown 链接、JSON 和敏感信息。
2. 提交并立即 push 当前 `feature/m7-remote-deploy-closure`。
3. 按新的 `PROJECT_PLAN.md` 冻结 M7-2E external side-effect handler、payload/
   result、凭据和崩溃恢复契约。
4. 在 WSL 建立隔离 Gitea 测试 fixture，实现受控 ref、精确 SHA 回读、唯一
   workflow dispatch 和 CIRun identity 收敛。

### 涉及文件

- `modules/platform-api/migrations/versions/20260716_0009_create_m7_ci_deployment_data.py`
- `modules/platform-api/src/cloudhelm_platform_api/models/`
- `modules/platform-api/src/cloudhelm_platform_api/repositories/`
- `modules/platform-api/src/cloudhelm_platform_api/schemas/`
- `modules/platform-api/tests/test_m7_ci_deployment_*.py`
- `modules/platform-api/tests/test_database_migration.py`
- `packages/shared-contracts/schemas/ci/ci-run.schema.json`
- `packages/shared-contracts/schemas/deployment/*.schema.json`
- `云舵 CloudHelm 毕设设计书.md`
- `docs/01-architecture/04-desktop-ops-hub-project-boundary.md`
- `docs/03-modules/modules/platform-api.md`
- `docs/07-data/`
- `docs/14-roadmap/03-implementation-milestone-flow.md`
- `docs/15-detailed-design/`
- `README.md`
- `modules/platform-api/README.md`
- `packages/shared-contracts/README.md`

### 验证

- WSL Ops Hub：PostgreSQL `accepting connections`，Redis `PONG`。
- 修改未提交的 `0009` 后执行开发库
  `downgrade 20260716_0008 -> upgrade head -> alembic check`，结果通过；
  `alembic check` 为 `No new upgrade operations detected`。
- M7-2D 定向测试：`75 passed`。
- Platform API 全量：`407 passed, 1 skipped, 2 warnings`。
- Workflow Engine 非 integration 回归：`51 passed, 2 deselected`。
- 独立临时数据库往返：
  `0008 -> head -> 0008 -> head/check` 通过。
- 初次开发库 downgrade 因新补充 constraint 尚未存在而失败；downgrade 对该新增
  constraint 使用 `if_exists` 后重试通过。
- 定向回归首次发现 2 个测试断言问题：Service JSON literal null 先命中成对健康
  CHECK、SQLAlchemy Result 未调用 `.all()`；修正测试构造后回归为 `75 passed`。

## 2026-07-16（M7-2D CI/部署数据契约冻结）

### 已完成

- 按 `PROJECT_PLAN.md` 先完成 M7-2D 文档契约冻结，尚未把数据表计划写成已交付：
  - CIRun 状态固定为
    `triggered/running/passed/failed/cancelled`，provider 固定 `gitea`。
  - ServiceInstance 状态固定为
    `starting/running/healthy/unhealthy/stopped/failed`，不增加 `unknown`，
    runtime 固定 `docker_compose`。
  - Deployment 失败证据统一使用 `failure_code/failure_summary`，并保留有界脱敏
    `health_summary_json`。
  - `workflow_revision` 定义为 1-255 字符有界 opaque revision，不误假设为
    Gitea commit SHA。
- 冻结三表完整字段、状态证据、SHA/digest/ref/slug/JSON 约束、唯一键、部分唯一
  索引、FK 删除规则、稳定分页和跨表锁内重验边界。
- Deployment Approval 采用独立
  `ck_approval_requests_deployment`，双向绑定
  `approve_deployment + deployment + L3 + requested_by_agent_run_id`；
  不修改历史 `20260716_0008`，现有 release candidate L2 CHECK 保持有效。
- 新增 `docs/07-data/tables/ci_runs.md`，重写旧
  `deployments.md`、`service_instances.md`，清除 `image_tag/deployed_by/
  rollback_from` 等漂移字段。
- 同步总设计书、数据库总表、数据索引和 M7/Data 细化设计；明确 M7-2D 不发布
  candidate ref、不触发 Gitea CI、不新增部署 API/事件，也不调用 Controller 或
  Remote Agent。
- 三个只读设计子任务分别核验 migration/约束、ORM/repository/契约和测试矩阵，
  工作树写入仍由主线程串行完成。

### 进行中

- 编写 `20260716_0009` migration、三表 ORM、repository、严格 Pydantic Record
  和 Draft 2020-12 共享 JSON Schema。

### 阻塞与风险

- Task/Project、Environment/RemoteTarget、父子 commit/digest 等跨表相等关系不能
  由单行 CHECK 完成；M7-2D 只提供精确查询与锁入口，后续 service 必须按
  `Task -> CIRun/Deployment -> ServiceInstance/Approval` 锁序重验。
- M7-2D 完成后仍只是数据底座；candidate ref、真实 Gitea CI、ReleasePlan、
  第二道审批 service/API 和远端 operation 仍需后续纵切。

### 下一步

1. 新增 `20260716_0009_create_m7_ci_deployment_data.py`。
2. 新增 CIRun、Deployment、ServiceInstance ORM 并注册 Alembic metadata。
3. 新增三个只负责持久化、查询、稳定分页和行锁的 repository。
4. 新增三个内部 Record DTO 与共享 JSON Schema。
5. 在 WSL PostgreSQL 执行正负约束、并发、migration 往返和 Platform API 回归。

### 涉及文件

- `云舵 CloudHelm 毕设设计书.md`
- `docs/07-data/01-database-schema.md`
- `docs/07-data/README.md`
- `docs/07-data/tables/ci_runs.md`
- `docs/07-data/tables/deployments.md`
- `docs/07-data/tables/service_instances.md`
- `docs/15-detailed-design/04-data-detail.md`
- `docs/15-detailed-design/09-m7-ci-remote-deployment-flow.md`
- `docs/README.md`
- `PROJECT_PROGRESS.md`

### 验证

- `git diff --check` 通过。
- Git 纳入范围共 `737` 个文件，严格 UTF-8 解码错误 `0`、BOM `0`。
- Markdown `205` 个、相对链接 `483` 条，缺失 `0`。
- 已复查文档 diff，确认没有新增未来 HTTP path、生产事件或外部副作用实现声明。

## 2026-07-16（M7-2C durable Workflow Engine 完成并进入 M7-2D）

### 已完成

- 完成 PostgreSQL 权威的 Redis + Celery Workflow Engine：
  - dispatcher due scan、逐 reservation 唯一 token、dispatch lease、publish
    success/failure finalize、指数退避和周期补投。
  - worker claim、mark-running、heartbeat、terminal、safe retry、Task
    pause/resume/cancel 联动和 stale reclaim。
  - Celery message 只携带 `workflow_job_id`，每次 delivery 使用独立 claim token。
  - 首个生产 handler 为
    `release_candidate_reconcile -> release_candidate -> none`，只执行数据库
    reconcile，不调用 Git、CI、Docker、HTTP 或 Remote Agent。
- 完成 Candidate reconcile 锁后重验：
  - Task、Job、Binding、Candidate、Approval 全部加锁后重新读取
    `clock_timestamp()`。
  - PR、Binding snapshot/hash、request hash、Approval expiry/consumed 和非法状态
    分支均使用精确错误码或 stale/terminal-noop 结果收敛。
- 根据并发审计补齐三个阻断问题：
  - dispatcher 改为无锁候选扫描后按 `Task -> WorkflowJob` 加锁重验。
  - 同一 batch 内每条 reservation 使用独立 `dispatch_owner`。
  - Task pause 在 Task 锁内撤销 pending job 的 dispatch token，旧 finalize
    no-op，不能覆盖 resume 的立即补投时间。
  - registry mismatch 在 Task cancel/pause 竞争后按 Task -> Job 重新加锁；
    cancel_requested/终态 Task 优先 cancelled，paused 回 pending，只有 runnable
    Task 才写 registry failure。
- 补齐 stale/retry 白盒矩阵：
  - stale claimed。
  - stale cancel_requested。
  - recovery_required 不自动重放。
  - `external_idempotent/external_uncertain` 在无 resolver 时 fail closed 为
    `recovery_required`，attempt 耗尽或 Task 终态不能伪造远端失败/取消。
  - Handler registry 拒绝未知 side-effect class；未来 external handler 异常不
    进入通用盲目 retry。
- 拆分 WorkflowJob repository、dispatch、lifecycle、recovery 和纯 recovery
  policy；本轮新增/重构的主要生产源码均不超过 300 行，函数不超过 60 行。
- 新增严格 WorkflowJob DTO、共享 JSON Schema 和完整事件 payload 门禁；Control
  Console 显式监听全部 WorkflowJob/Candidate 事件。
- 清除 M7-2C 文档漂移：
  - Workflow Engine、Platform API、Orchestrator、数据库、事件、审批、
    Ops Hub WSL 和测试文档已同步。
  - Roadmap 已勾选 M7-2C。
  - `PROJECT_PLAN.md` 已重写为 M7-2D CIRun、Deployment、ServiceInstance
    migration/ORM/repository/contract 数据底座计划。
- WSL 干净依赖环境发现
  `test_m7_machine_auth_heartbeat.py` 仍直接 import `httpx`，而当前 Starlette/
  项目依赖使用 `httpx2`；已改为 `import httpx2 as httpx` 并完成全量回归。
- 并行重载时 heartbeat thread 测试出现一次调度型假失败；测试改为较长初始
  lease，并在有界时间内轮询真实续租结果，随后隔离全量回归稳定通过。
- M7-2C 代码、配置、共享契约与测试已提交为 `16a0c27`，并 push 到
  `origin/feature/m7-remote-deploy-closure`。
- M7-2C README、设计文档、Roadmap、进度和 M7-2D 计划已提交为
  `b53f0ac`，并 push 到同一远端功能分支。

### 进行中

- M7-2D：先同步总设计书、数据库总表和三个逐表文档，冻结 CIRun、
  Deployment、ServiceInstance 的字段、状态、约束和索引，再实现
  `20260716_0009` migration、ORM、repository 与严格共享契约。
- 当前尚未创建 M7-2D migration 或生产表，不把下一阶段计划写成已交付能力。

### 阻塞与风险

- 完整 M7 仍缺 candidate ref 发布、真实 Gitea CI、ReleasePlan、第二道审批、
  Deployment Controller、Remote Agent operation、正式 Ops Hub installation 和
  Linux staging E2E。
- M7-2D 现有总表、旧逐表文档、详细设计和总设计书仍有字段/状态漂移；必须先
  文档冻结，再写 migration。
- Platform API 全量测试仍有 Pydantic `UnsupportedFieldAttributeWarning`；当前
  不影响测试结论，但后续应单独清理公共分页/查询 `Annotated` alias 定义。
- Agent Runtime 真实外部 provider/Prompt Cache 专项仍因未注入临时凭据而 skip，
  不能把本轮结果描述为新的外部 provider 实时证据。

### 下一步

1. 复查 M7-2C `git diff --stat`、关键代码/契约 diff 和敏感信息扫描结果。
2. 按可验证小步提交并 push M7-2C 代码/测试与文档/计划。
3. 同步 `云舵 CloudHelm 毕设设计书.md`、数据库总表和
   `ci_runs/deployments/service_instances` 逐表文档。
4. 新增 `20260716_0009` migration、三表 ORM/repository/Pydantic/JSON Schema。
5. 在 WSL 使用真实 PostgreSQL 执行正负约束、并发、migration 往返和 Platform
   API 全量验收。

### 涉及文件

- `modules/workflow-engine/`
- `modules/platform-api/src/cloudhelm_platform_api/repositories/workflow_job_*.py`
- `modules/platform-api/src/cloudhelm_platform_api/services/release_candidate_reconcile_*.py`
- `modules/platform-api/src/cloudhelm_platform_api/services/task_service.py`
- `modules/platform-api/tests/test_m7_release_candidate_reconcile.py`
- `packages/shared-contracts/schemas/workflow/workflow-job.schema.json`
- `packages/shared-contracts/schemas/events/task-event.schema.json`
- `apps/control-console/src/shared/types/events.ts`
- `apps/control-console/tests/m6EventTypes.test.ts`
- `README.md`
- `docs/01-architecture/04-desktop-ops-hub-project-boundary.md`
- `docs/03-modules/`
- `docs/07-data/`
- `docs/08-api/`
- `docs/12-deployment/`
- `docs/14-roadmap/03-implementation-milestone-flow.md`
- `docs/15-detailed-design/`
- `PROJECT_PLAN.md`

### 验证

- WSL Platform API：
  - `uv lock --check`
  - Alembic `current=20260716_0008 (head)`
  - `alembic check=No new upgrade operations detected`
  - 全量 `332 passed, 1 skipped`
- WSL Workflow Engine：
  - 非 integration：`51 passed, 2 deselected`
  - 隔离 Redis restart + prefork hard-crash：`2 passed, 51 deselected`
  - dispatcher/pause/claim 并发门禁连续 5 轮，每轮 `7 passed`
- WSL 其余服务：
  - Orchestrator：`7 passed`
  - Agent Runtime：`61 passed, 1 skipped`
  - Tool Gateway：`46 passed`
  - Remote Agent：`33 passed`
- Control Console：`17 passed`，production build 通过。
- sample repo：`2 passed`，Bandit 无发现，pip-audit 无已知漏洞；本地包因不在
  PyPI 按工具真实行为跳过。
- 当前 Git 纳入范围：
  - UTF-8 文本 `726` 个，解码错误 `0`、BOM `0`
  - Markdown `204` 个、相对链接 `472` 条，缺失 `0`
  - JSON `38` 个，解析错误 `0`
  - 非测试生产代码/配置/文档高置信敏感信息命中 `0`
  - Python `compileall` 通过
  - `git diff --check` 通过

## 2026-07-16（暂停：M1-M7 当前代码复核与 M7-2C 验证）

### 已完成

- 按最新 `AGENTS.md`、`PROJECT_PLAN.md` 和
  `docs/14-roadmap/03-implementation-milestone-flow.md` 对当前工作树重新进行
  M1-M7 分段复核。
- 当前阶段性结论：
  - M1-M3 的目录骨架、真实 API/数据库事件、控制台真实数据主流程满足各自完成
    判定。
  - M4 的代码、结构化输出、root/child conversation 原语和本地回归满足现行
    边界；真实外部 provider 五轮 Prompt Cache 专项本轮未重新注入配置执行，
    保留既有验收记录，不把本轮 skip 写成新的实时证据。
  - M5 Tool Gateway 的参数校验、角色/工具权限、风险、限流、审批和脱敏审计满足
    当前受控本地工具边界。
  - M6 本地代码修改、测试、安全扫描、Git 与等价 PR record 闭环继续通过回归。
  - 完整 M7 尚未完成；当前已交付 M7-0、M7-1、M7-2A、M7-2B1、M7-2B2。
    M7-2C 已形成可运行草稿并通过 Windows 回归，但尚未完成最终 WSL 复测、
    文档/Progress/Roadmap 同步、代码体量收口和 Git 提交，因此本次暂停不将
    M7-2C 或完整 M7 标记为完成。
- 当前工作树验证：
  - Platform API：`317 passed, 1 skipped`。
  - Workflow Engine Windows：`26 passed, 1 skipped`；唯一 skip 为需显式启用的
    WSL Redis restart 集成测试。
  - Workflow Engine dispatcher/claim/lifecycle 定向并发连续 5 轮，每轮
    `13 passed`。
  - Orchestrator：`7 passed`。
  - Agent Runtime：`61 passed, 1 skipped`；skip 为未注入真实外部 provider
    配置的专项。
  - Tool Gateway：`45 passed, 1 skipped`；skip 为当前 Windows symlink 权限
    条件。
  - Remote Agent：`31 passed, 2 skipped`；skip 为 POSIX mode/symlink 的
    Windows 条件。
  - Control Console：`17 passed`，production build 通过。
  - sample repo：`2 passed`，Bandit 通过，pip-audit 无已知漏洞。
  - Alembic：`current=20260716_0008 (head)`；
    `No new upgrade operations detected`。
  - FastAPI OpenAPI 与共享 YAML 精确一致、全部共享 JSON Schema
    Draft 2020-12 meta-validation 随 Platform API 全量测试通过。
  - 当前纳入 Git 的文本文件与未跟踪草稿共检查 `726` 个，UTF-8 解码错误 `0`、
    BOM `0`。
  - Markdown `204` 个文件、相对链接 `472` 条，缺失 `0`。
  - 生产代码、配置和文档高置信密钥模式命中 `0`；测试目录中的假 secret
    仅用于脱敏测试。
  - `git diff --check` 通过。

### 进行中

- 已按用户要求立即暂停，不再继续 WSL 集成、文档同步、代码重构、Roadmap 打钩
  或 Git 提交。
- 当前分支保持 `feature/m7-remote-deploy-closure`，HEAD 保持 `6144ad5`；
  `origin/feature/m7-remote-deploy-closure` 与 HEAD 无领先/落后。
- M7-2C 的生产代码、测试、共享契约和文档草稿继续原样保留在未提交工作树中，
  没有清理、reset、stash 或覆盖。

### 阻塞与风险

- 当前最终草稿拆分后尚未重新执行 WSL 非集成全量和隔离 Redis stop/start +
  真实 prefork Celery worker 测试；此前结果不能替代暂停点代码的最终复测。
- `README.md`、`docs/07-data/01-database-schema.md`、
  `docs/15-detailed-design/04-data-detail.md`、
  `docs/15-detailed-design/05-workflow-state-events.md` 和
  `docs/15-detailed-design/07-testing-acceptance-matrix.md` 仍有把
  durable Workflow Engine 写成未实现/规划项的旧表述，与当前 M7-2C 草稿存在
  状态漂移。
- Roadmap 的 M7-2C 仍为 `[ ]`，`PROJECT_PLAN.md` 仍指向 M7-2C；
  这是正确的暂停状态，必须在全部完成判定满足后再打钩和滚动计划。
- `release_candidate_reconcile_service.py` 当前为 `441` 行，其中 `execute`
  为 `184` 行；超过 `AGENTS.md` 对复杂 service 和函数的拆分评估线，恢复后需
  先拆分或形成明确评估结论。
- 完整 M7 Roadmap 当前仍有 CIRun/Deployment/ServiceInstance、正式 Ops Hub
  installation/bootstrap、Gitea runner/registry、受控 ref 发布与唯一 CI、
  Release/Deploy Agent、Deployment Controller、Remote Agent operation、
  通用 renderer、控制台证据页和 Linux staging E2E 等未完成项，因此不能把
  “M1-M7 全部符合”作为当前结论。
- M4 真实外部 provider 五轮 Prompt Cache 专项本轮为条件 skip；恢复后若要生成
  新的当前时点实时证据，需要显式注入临时 provider 配置再执行。

### 下一步

1. 恢复时先执行 `git status --short`、`git diff --stat` 和关键文件 diff，
   确认暂停期间工作树未漂移。
2. 拆分或评估 `release_candidate_reconcile_service.py` 的职责与长函数，并回归
   Candidate cancellation、freshness、审批和事件事务分支。
3. 同步数据库、Workflow/Event、Testing、README、Roadmap 和
   `PROJECT_PROGRESS.md` 中的 M7-2C 状态，清除相互矛盾的旧表述。
4. 在 WSL 独立虚拟环境执行最终非集成全量，并使用隔离 Redis container 复跑
   Redis stop/start、PostgreSQL 补投和真实 prefork Celery worker E2E。
5. 重跑 Platform API、Workflow Engine、并发多轮、Alembic、OpenAPI/JSON
   Schema、UTF-8/BOM、Markdown 链接、敏感信息、文件体量和
   `git diff --check` 门禁。
6. 全部通过后再勾选 M7-2C、把 `PROJECT_PLAN.md` 重写到
   CIRun/Deployment/ServiceInstance 数据与 migration，并按可验证小步
   commit/push 当前功能分支。

### 涉及文件

- `PROJECT_PROGRESS.md`
- 当前未提交 M7-2C 工作树，详见 `git status --short`

### 验证

- 本条仅记录暂停点和此前已完成的只读审计/验证；写入后不继续执行新的实现或
  集成测试。

## 2026-07-16（M7-2B2 Candidate、第一道审批与 reconcile WorkflowJob 原子创建纵切）

### 已完成

- 实现：
  - `POST /api/tasks/{task_id}/release-candidate`
  - `GET /api/tasks/{task_id}/release-candidate`
- Candidate POST 使用严格空对象 DTO；首次创建返回 `201`，相同 PR 与 Binding
  snapshot 的顺序/并发幂等命中返回 `200`。GET 优先 active Candidate，否则返回
  `created_at,id` 最新历史。
- 服务端绑定最新版 open M6 PullRequestRecord、实现 AgentRun、完整 commit、
  Binding public snapshot/internal hash、受控 target ref、request hash 和
  idempotency key；重新核验四类 M6 门禁 Artifact。
- Candidate、第一道 L2 Approval、pending
  `release_candidate_reconcile` WorkflowJob、`WorkflowJobQueued` 和
  `ReleaseCandidateApprovalRequested` 在同一 PostgreSQL 事务创建。
- 复用 Approval approve/reject API，新增 Candidate 专用领域决策：
  - Task-first 锁序。
  - PR、Binding snapshot/hash 与 request hash freshness。
  - expiry、consumed、resource/action 与重复决策门禁。
  - plain UUID、`agent-run:<UUID>` 和首尾空格统一规范化后的实现 AgentRun
    自批拒绝。
  - reason 脱敏，事件不包含 clone URL、profile 或 credential。
- 新 PR 创建先锁 Task，并发创建最终只保留一条 open PR；新 PR 或 Binding 漂移
  会原子使旧 Candidate stale、pending Approval expired。
- 修复锁等待时间竞争：原 `PostgreSQL now()` 固定为事务开始时间，Binding PUT
  事务先开始、等待 Candidate 创建后可能写出 `decided_at < created_at`。资源审批
  现改用 `clock_timestamp()`，并以 Candidate/Approval `created_at` 作为下界；
  确定性测试先启动 PUT 事务、再创建 Candidate、最后恢复 PUT。
- 共享 OpenAPI、事件 JSON Schema、Control Console API/事件类型、README、API/
  Data/Workflow/Testing 文档与 Roadmap 已同步。版本继续保持 `0.5.1`；完整 M7
  E2E 收口时再发布 `0.6.0`。
- B2 生产代码、测试与共享契约已提交为 `dfbee7e`，并 push 到
  `origin/feature/m7-remote-deploy-closure`。
- B2 README、API/Data/Workflow/Testing 文档、Roadmap 与 M7-2C
  `PROJECT_PLAN.md` 已提交为 `2aee882`，并 push 到同一远端分支。

### 进行中

- M7-2C Redis + Celery durable Workflow Engine。

### 阻塞与风险

- B2 只持久化 pending WorkflowJob，尚无 dispatcher、claim、lease、heartbeat、
  retry、stale reclaim 或 Redis 重启补投。
- CIRun、Deployment、ServiceInstance、正式 Ops Hub installation、Gitea
  runner/registry、Deployment Controller、Remote Agent operation 和 Linux
  staging E2E 仍属于后续 M7 切片。
- 当前自批门禁基于 AgentRun provenance；真实 user/session/RBAC/SoD 由 M9
  接入，不把调用方 actor 字符串描述为不可伪造身份。

### 下一步

1. 创建独立 `modules/workflow-engine` Python 包并固定 Celery/redis 依赖。
2. 扩展 WorkflowJob repository 的 reserve/finalize/claim/heartbeat/terminal/
   retry/reclaim 短事务。
3. 实现首个真实 `release_candidate_reconcile` handler。
4. 使用 WSL 原生 PostgreSQL/Redis 验证重复消息、并发 claim、worker kill、
   Redis 重启补投和 Task pause/cancel。

### 涉及文件

- `modules/platform-api/src/cloudhelm_platform_api/api/release_candidates.py`
- `modules/platform-api/src/cloudhelm_platform_api/repositories/{pull_request_record,release_candidate,workflow_job}_repository.py`
- `modules/platform-api/src/cloudhelm_platform_api/schemas/release_candidate.py`
- `modules/platform-api/src/cloudhelm_platform_api/services/{pull_request_record_gate,release_candidate_*}.py`
- `modules/platform-api/tests/{m7_release_candidate_api_fixture,test_m7_release_candidate_api,test_m7_approval_decisions,test_m7_repository_binding_concurrency,test_m6_pull_request_concurrency}.py`
- `packages/shared-contracts/openapi/cloudhelm.openapi.yaml`
- `packages/shared-contracts/schemas/events/task-event.schema.json`
- `apps/control-console/src/shared/types/{api,events}.ts`
- `README.md`
- `modules/platform-api/README.md`
- `docs/01-architecture/04-desktop-ops-hub-project-boundary.md`
- `docs/03-modules/{modules/platform-api,modules/workflow-engine,packages/shared-contracts}.md`
- `docs/07-data/01-database-schema.md`
- `docs/08-api/{00-api-overview,07-environment-deployment-api}.md`
- `docs/14-roadmap/03-implementation-milestone-flow.md`
- `docs/15-detailed-design/{03-api-detail,04-data-detail,07-testing-acceptance-matrix,09-m7-ci-remote-deployment-flow}.md`
- `PROJECT_PLAN.md`

### 验证

- WSL Ubuntu 24.04 原生 Docker：PostgreSQL `healthy`，Redis `PONG`。
- `uv lock --check`、`alembic current`=`20260716_0008 (head)`、
  `alembic check`=`No new upgrade operations detected`。
- Candidate/Approval/Binding/PR/共享契约定向：`46 passed, 2 warnings`。
- 确定性 Binding PUT/Candidate POST 锁等待竞争连续 10 轮，每轮 `1 passed`。
- Platform API 全量：`308 passed, 1 skipped`。
- Orchestrator：`7 passed`。
- Agent Runtime：`61 passed, 1 skipped`。
- Tool Gateway：`45 passed, 1 skipped`。
- Remote Agent：`31 passed, 2 skipped`。
- Control Console：`17 passed`，production build 通过。
- sample repo：`2 passed`，Bandit 0 finding，pip-audit 无已知漏洞。
- Python `compileall` 与 `git diff --check` 通过。

## 2026-07-16（M7-2B1 RepositoryProfile 与 Binding PUT/GET）

### 已完成

- 新增严格 `extra=forbid` 的 `RepositoryProfileConfig`，固定 Gitea provider、
  HTTPS clone URL、default branch 和完整 `refs/heads/...` release ref 校验。
- 新增服务端配置来源：
  - `CLOUDHELM_REPOSITORY_PROFILES`
  - `CLOUDHELM_REPOSITORY_PROFILES_FILE`
  - `CLOUDHELM_REPOSITORY_CREDENTIALS`
- 实现：
  - `PUT /api/projects/{project_id}/repository-binding`
  - `GET /api/projects/{project_id}/repository-binding`
- PUT 请求只接受 `profile_key`；响应、OpenAPI、EventLog 和前端类型均不包含
  clone URL、credential ref、credential 内容或 profile 文件路径。
- 首次创建无 Binding 行时使用 Project `FOR UPDATE` 作为 mutex；并发相同 PUT
  返回同一 Binding 和单条事件。
- Repository identity 变更先取得 PostgreSQL transaction-level advisory
  namespace lock；两个已绑定 Project 并发反向交换 identity 均稳定返回 409，
  不形成唯一索引死锁或 500。
- 复用 `stable_json_hash` 实现 public/internal snapshot；相同 active snapshot
  保持 ID、时间和事件不变。
- Binding 漂移时按 Candidate/Approval UUID 顺序加锁：
  - `pending_approval|approved Candidate -> stale`
  - `pending Approval -> expired`
  - 已 approved Approval 与 published Candidate 保留历史终态。
  - `decided_by=system:release_candidate_freshness`
  - 决策时间使用 PostgreSQL `now()`。
- 两类 repository identity 约束统一映射为
  `409 repository_binding_conflict`，冲突更新完整回滚。
- CORS 已加入 PUT；共享 OpenAPI、事件 schema、前端类型、README、`.env.example`
  和非敏感 profile example 已同步。
- 版本影响已记录：本切片新增兼容 API，纳入下一 minor `0.6.0`；当前仅为未发布
  功能分支，没有创建 release/tag，开发包暂保持 `0.5.1`。

### 进行中

- M7-2B2：严格空对象 Candidate POST/GET、第一道 L2 Approval、
  `release_candidate_reconcile` WorkflowJob 原子创建和专用审批锁序。

### 阻塞与风险

- M7-2B2 尚未完成，因此 Roadmap 只勾选 M7-2B1，不把整个 M7-2B 或 M7 标记完成。
- 当前 `PullRequestRecordService.create` 仍需在查重、supersede 和 insert 前锁
  Task；Candidate 读取最新版 open PR 前必须先完成该并发门禁。
- 正式 Ops Hub installation、Workflow Engine、Gitea CI、Deployment Controller
  和 Linux staging E2E 仍属于后续 M7 切片。

### 下一步

1. 为 PullRequestRecord create 补 Task-first 串行化和并发回归。
2. 实现 Candidate snapshot/ref/request hash、201/200 幂等和 GET active-first。
3. 原子创建 Candidate、L2 Approval、reconcile WorkflowJob 与领域事件。
4. 实现 Candidate approve/reject 专用锁序、freshness、自批和 expiry 门禁。

### 涉及文件

- `modules/platform-api/src/cloudhelm_platform_api/core/repository_config.py`
- `modules/platform-api/src/cloudhelm_platform_api/providers/repository_profile_provider.py`
- `modules/platform-api/src/cloudhelm_platform_api/{api,repositories,schemas,services}/**repository_binding**`
- `modules/platform-api/src/cloudhelm_platform_api/repositories/release_candidate_repository.py`
- `modules/platform-api/tests/m7_repository_binding_fixture.py`
- `modules/platform-api/tests/test_m7_{project_repository_binding_api,repository_profile,repository_binding_drift,repository_binding_concurrency}.py`
- `modules/platform-api/repository-profiles.example.json`
- `packages/shared-contracts/openapi/cloudhelm.openapi.yaml`
- `packages/shared-contracts/schemas/events/task-event.schema.json`
- `apps/control-console/src/shared/types/api.ts`
- `.env.example`
- `PROJECT_PLAN.md`
- `README.md`
- `docs/01-architecture/04-desktop-ops-hub-project-boundary.md`
- `docs/03-modules/{modules/platform-api,packages/shared-contracts}.md`
- `docs/07-data/{01-database-schema,tables/project_repository_bindings}.md`
- `docs/08-api/07-environment-deployment-api.md`
- `docs/14-roadmap/03-implementation-milestone-flow.md`
- `docs/15-detailed-design/09-m7-ci-remote-deployment-flow.md`

### 验证

- M7-2B1 RepositoryProfile/Binding/漂移/并发定向：`35 passed`。
- M7-2B1 + M6/M7 共享契约定向：`46 passed`。
- RepositoryBinding 并发文件连续执行 5 轮，每轮 `6 passed`。
- Platform API 全量：`279 passed, 1 skipped`。
- Control Console：`17 passed`，production build 通过。
- `uv lock --check`、Python `compileall`、`alembic current`、
  `alembic check`、`git diff --check` 通过。
- WSL Ubuntu 24.04 原生 Docker Engine `29.1.3`、Compose `2.40.3`；
  PostgreSQL `healthy`、Redis `PONG`。
- 40 个本轮文本文件严格 UTF-8 解码通过且 BOM 为 0；新增 JSON 文件可解析，
  15 个改动 Markdown 的相对链接缺失为 0。

## 2026-07-16（M1-M7 复核、WSL Ops Hub 基线与 M7-2A 数据底座）

### 已完成

- 按最新 `AGENTS.md`、Roadmap、详细设计和已提交文档重新核对 M1-M7：
  - M1-M6 已实现边界与 `docs/13-testing/01-m1-m6-audit-report.md` 一致。
  - M7-0/M7-1 已实现边界仍为设计基线、Environment/RemoteTarget、
    machine-auth heartbeat 和最小 Remote Agent。
  - Tauri、IAM/RBAC、EventLog sequence、TechnicalDesign user provenance 继续
    属于 M9，没有混入 M7 migration。
- 完成 M1-M6 与 M7-1 当前非数据库回归：
  - Orchestrator `7 passed`。
  - Agent Runtime `61 passed, 1 skipped`。
  - Tool Gateway `45 passed, 1 skipped`。
  - Remote Agent `31 passed, 2 skipped`。
  - Control Console `17 passed`，production build 通过。
- 建立 Windows 开发机的 WSL Ops Hub 基线：
  - 安装 Ubuntu 24.04 WSL2。
  - 发行版迁移到 `D:\WSL\Ubuntu-24.04`。
  - 创建 `cloudhelm` 用户，安装发行版内原生 Docker Engine `29.1.3`、
    Docker Compose `2.40.3`、PostgreSQL/Redis client 和开发工具。
  - 使用隐藏 `sleep infinity` keepalive 保持 WSL 运行；未保持时发行版会进入
    `Stopped`，容器端口随之消失。
  - WSL 原生 Docker 中 PostgreSQL 为 `healthy`，Redis 返回 `PONG`，
    Windows psycopg 可连接 `127.0.0.1:15432`。
  - 修正 keepalive 检测：一次 WSL 调用在 Windows 侧会形成 parent/child 两个
    同命令行 `wsl.exe`，现按根 client 计数，避免把一次启动误判为两个。
  - 连续执行两次 keepalive 启动均保持同一根 client；等待 60 秒后 PostgreSQL
    仍为 `healthy`、Redis 为 `PONG`，Windows `15432` 端口可达。
- 按用户决定卸载 Docker Desktop：
  - `docker-desktop` 发行版、C 盘用户数据和 D 盘迁移副本已删除。
  - C 盘可用空间由约 `12.8 GiB` 增至约 `42.1 GiB`。
  - `C:\ProgramData\DockerDesktop` 仅残留约 16 KiB 的管理员安装日志，不作为
    CloudHelm 运行依赖。
- 完成 M7-2A `20260716_0008` 数据底座：
  - 新增 `project_repository_bindings`、`release_candidates`、
    `workflow_jobs`。
  - ApprovalRequest 新增资源、request hash、有效期、消费时间和 cancelled 状态。
  - 修复 Candidate `published` 对 SQL NULL 的 CHECK 漏洞，强制
    `remote_verified_sha IS NOT NULL AND remote_verified_sha = commit_sha`。
  - Candidate 八字段安全 snapshot 现在拒绝 JSON null、非字符串、额外字段和
    不安全 `release_ref_prefix`。
  - 修复 Binding、Candidate snapshot 和 target ref 对 component 以点开头、
    中间 component 以 `.lock` 结尾及控制字符的数据库漏检；这些值会被
    `git check-ref-format` 拒绝，现已由 PostgreSQL CHECK 同步阻断。
  - WorkflowJob 初始 `next_enqueue_at` 改由 PostgreSQL `now()` 生成。
  - 通用 Approval POST 对 `approve_release_candidate` 返回稳定
    `422 approval_action_reserved`，避免数据库 CHECK 退化为 500。
  - 同步 Control Console Approval 类型和共享 OpenAPI。
  - 新增独立 M7-2A 约束夹具和真实 PostgreSQL 行为测试：
    - 覆盖 Approval、RepositoryBinding、Candidate、WorkflowJob 的全部新增
      CHECK 类别。
    - 覆盖普通/部分/函数式唯一约束、NO ACTION/CASCADE 外键行为。
    - 直接省略字段执行 INSERT，验证关键 PostgreSQL server default。
    - 每个可区分的失败断言 PostgreSQL 返回的真实 constraint name，避免负测
      命中错误约束形成假阳性。
    - Candidate 六个状态和 WorkflowJob 八个状态均有合法数据库形态正向测试，
      避免只证明“会拒绝”而未证明生命周期分支可用。
  - 修正数据库权威 DDL、storage boundary、M7 data detail、Roadmap 和当前执行
    指针；M7-2A 与 M7-2B/C 已拆分，不再把数据底座与未实现 service/worker 混写。
  - 补充 WSL 发行版/Docker/Compose/用户权限预检、keepalive 去重和停止命令，
    并将 IT-031A 开发依赖基线与 IT-031B 最小 Ops Hub profile 预演拆分。
  - WSL 开发基线文档已以 `c82f3bb` 独立提交并 push 到
    `origin/feature/m7-remote-deploy-closure`。

### 进行中

- M7-2A 数据/契约小步随本条进度记录独立提交并 push。
- 当前实施切片进入 M7-2B：
  ProjectRepositoryBinding profile/API、ReleaseCandidate 原子创建、第一道审批、
  binding 漂移和 Task-first 并发门禁。

### 阻塞与风险

- WSL systemd 服务本身不保证发行版始终保持 Running；当前开发环境使用显式
  keepalive。正式 Ops Hub 必须在独立 Linux 主机/systemd/Compose 中验证常驻。
- ReleaseCandidate Approval 要求 `requested_by_agent_run_id IS NOT NULL`，因此
  对应 AgentRun 的 `ON DELETE SET NULL` 会被 CHECK 阻断；当前按保留审计
  provenance 记录，M9 再统一历史删除策略。
- M7-2B/C、通用 renderer、Ops Hub 正式 bootstrap、CI/部署和 Linux staging E2E
  尚未完成，版本继续保持 `0.5.1`。

### 下一步

1. 实现 server-controlled RepositoryProfile 与 Binding PUT/GET，补 CORS PUT、
   幂等和漂移失效测试。
2. 修复 PullRequestRecord Task 锁，再实现 Candidate/Approval/WorkflowJob 原子
   创建、201/200 幂等语义和专用审批锁序。
3. 建立 `modules/workflow-engine` durable dispatcher/worker/heartbeat/reclaimer。
4. 继续实现通用 renderer、正式 Ops Hub profile、Gitea CI/registry 和远端 E2E。

### 涉及文件

- `modules/platform-api/migrations/versions/20260716_0008_create_m7_release_jobs.py`
- `modules/platform-api/src/cloudhelm_platform_api/models/**`
- `modules/platform-api/src/cloudhelm_platform_api/schemas/{approval,common}.py`
- `modules/platform-api/src/cloudhelm_platform_api/services/approval_service.py`
- `modules/platform-api/tests/{conftest,m7_release_job_fixture,test_database_migration,test_m7_release_job_constraints,test_agent_tool_approval_api}.py`
- `packages/shared-contracts/openapi/cloudhelm.openapi.yaml`
- `apps/control-console/src/shared/types/api.ts`
- `docs/07-data/{01-database-schema,02-storage-boundary}.md`
- `docs/07-data/tables/{approval_requests,release_candidates}.md`
- `docs/12-deployment/05-ops-hub-installation.md`
- `docs/14-roadmap/03-implementation-milestone-flow.md`
- `docs/15-detailed-design/04-data-detail.md`
- `docs/15-detailed-design/07-testing-acceptance-matrix.md`
- `云舵 CloudHelm 毕设设计书.md`
- `README.md`
- `PROJECT_PLAN.md`

### 验证

- WSL 原生 Docker：
  - 发行版、D 盘 VHD、Docker group、systemd daemon、Docker info、Compose
    version 和 Compose config 预检通过。
  - keepalive 连续执行两次后根 client 数均为 1。
  - PostgreSQL `healthy`。
  - Redis `PONG`。
  - 等待 60 秒后 Windows `15432` 可达，psycopg 连接成功。
- Alembic：
  - `upgrade -> 20260716_0008` 通过。
  - `downgrade 20260715_0007` 后 M7-2 三表和 Approval 五字段消失，
    M1-M7-1 表保留。
  - 重新 upgrade 后 `alembic current=20260716_0008`。
  - `alembic check`：`No new upgrade operations detected`。
- Platform API migration/约束/Approval 定向回归：`101 passed`。
- Platform API 全量回归：`243 passed, 1 skipped`。
- Python `compileall` 与 `uv lock --check` 通过。

## 2026-07-16（Desktop / Ops Hub / 用户权限架构与规划修订）

### 已完成

- 本轮按“只修改文档和计划、暂停生产代码”执行，重新冻结正式产品拓扑：
  - Windows/Linux CloudHelm Desktop。
  - 本机 Local Runtime sidecar。
  - 常在线 Linux CloudHelm Ops Hub。
  - Remote Agent。
  - 可受管、也可完全独立运行的业务项目。
- 明确 Desktop 最终用户安装不依赖 Docker、PostgreSQL、Redis 或 Python；
  Desktop SQLite 只保存 server profile、UI 设置、草稿、缓存和 event sequence，
  token/Ed25519 device private key 保存到 OS credential store。
- 保留 PostgreSQL/Redis 作为 Ops Hub 服务端基础设施：PostgreSQL 保存任务、
  Agent、审批、事件、WorkflowJob、用户/RBAC、部署和审计权威状态，Redis/Celery
  只负责非权威投递。
- 新增/同步 Desktop 安装、Ops Hub bootstrap、三类存储、项目可剥离四层边界、
  通用项目 renderer、离线 sequence sync 与 standalone/managed 双路径设计。
- 新增用户管理与分层权限规划：
  - User、Device、UserSession、refresh token history、Invitation。
  - Role、Permission、RoleBinding、permission version。
  - system/project/environment scope。
  - resource capability 与 domain separation-of-duty。
  - Desktop 页面/按钮门禁和 API 服务端重新鉴权。
- 完成最终契约纠偏：
  - Ops Hub installation 与 Remote Target / Environment bootstrap 分为两条独立
    生命周期；M7 不创建真实 user/device/session，identity bootstrap 固定进入 M9。
  - 预置权限按 `(role_key, binding_scope_type)` 映射；Environment binding 只获得
    environment-domain permission，父 Project/关联 Task/CI 只返回最小脱敏摘要。
  - EventLog 区分 `actor_user_id` 与 `subject_user_id`，增加 `stream_kind` 和
    project/subject sequence index；Desktop cursor 按
    `ops_hub_id + user_id + stream_kind + scope_id` 分区。
  - TechnicalDesign 保存当前版本修改者 source、user/AgentRun provenance 和
    `technical-design-content.v1` stable content hash，支撑最后修改者禁自批。
  - Desktop 与 Local Runtime 统一使用 Ed25519 challenge proof；服务端只保存
    public key/fingerprint/version，Local Runtime 只取得短期 device-bound token。
- 预置角色固定为：
  `system_owner`、`project_developer`、`project_reviewer`、
  `environment_operator`、`deployment_approver`、`auditor`、`viewer`。
- 修订 M7-M10：
  - M7：Ops Hub 常驻控制面、durable continuation、CI 与远端部署。
  - M8：监控、告警与 SRE。
  - M9：Tauri Desktop、Local Runtime、用户/RBAC、SQLite/credential 和同步。
  - M10：Windows/Linux 发行、Ops Hub 运维、双路径和最终 E2E。
- `PROJECT_PLAN.md` 已从旧 M7-2 大型代码计划重写为新架构下的恢复计划；
  当前代码继续暂停，恢复时先保护并验证 `20260716_0008` 草稿。
- 已核对先前截图中的五项 M1-M6 核验进度。分支/工作区、subagent policy 与
  Task cancel、Codex CLI 式协作边界、M1-M6 后端/前端/契约回归和 Git 收口均已
  由历史 `docs/13-testing/01-m1-m6-audit-report.md` 与对应提交归档；该截图不再是
  当前执行指针。
- 修正文档中的 subagent 过度表述：
  - CloudHelm 使用 `max_active_children=6` 的自有计数语义，不再写成与 Codex
    CLI 并发 thread 配置精确等价。
  - M1-M6 只有内部 child conversation/权限/生命周期原语，没有真实 child
    AgentRun/provider 调度、wait-all、steer/queue 或 thread UI。
  - 并发写路径统一描述为 Task-first 串行化，不再宣称所有路径共享一条不准确的
    完整锁序。

### 进行中

- 文档、计划和资料归档的全量验证已完成。
- 文档提交 `996c120` 已推送；M7-2 生产代码草稿继续保持暂停和未暂存。

### 阻塞与风险

- 当前 `apps/control-console` 仍是 Vite Web：没有 `src-tauri`、安装包、登录、
  SQLite、OS credential store 或运行时 server profile。
- `modules/local-runtime`、`infra/ops-hub`、project/env schema 和通用 renderer
  尚未实现。
- 当前 M4/M6 真实流程仍使用 `run-next`；服务端 durable continuation 是 M7
  目标，不能写成当前已交付。
- 当前 IAM、RBAC、EventLog sequence 和 Desktop sync 全部是 M9 规划；
  `20260716_0008` 草稿不包含这些表或字段。
- 本轮只读 M1-M6 subagent 定向 pytest 尝试因
  `127.0.0.1:15432` PostgreSQL 连接超时停在 fixture setup，15 个用例未进入
  测试体；本轮不复用历史通过数冒充当前回归结果。由于本轮不修改生产代码，
  后续恢复代码前按新计划启动数据库并重新执行。

### 下一步

1. 继续保持 M7-2 代码暂停；用户后续继续实施时，从
   `PROJECT_PLAN.md` 的 M7-2A 预检、数据库往返和独立代码小步恢复。
2. 恢复实现前再次核对开发数据库 Alembic head、10 个未提交代码草稿和远端分支。

### 涉及文件

- `AGENTS.md`
- `README.md`
- `云舵 CloudHelm 毕设设计书.md`
- `PROJECT_PLAN.md`
- `PROJECT_PROGRESS.md`
- `docs/00-project/**`
- `docs/01-architecture/**`
- `docs/02-tech-stack/**`
- `docs/03-modules/**`
- `docs/04-agents/00-agent-layer.md`
- `docs/07-data/**`
- `docs/08-api/**`
- `docs/10-security/**`
- `docs/12-deployment/**`
- `docs/13-testing/01-m1-m6-audit-report.md`
- `docs/14-roadmap/03-implementation-milestone-flow.md`
- `docs/15-detailed-design/**`
- `informations/m4-agent-context/codex-responses-context.md`
- `informations/m7-desktop-ops-architecture/**`

### 验证

- 三个只读复核方向最终均为 P0=0、P1=0：
  - Ops Hub/Remote Target lifecycle、M7 切片、Roadmap、Plan。
  - IAM/Role Scope、EventLog actor/subject、TechnicalDesign provenance、
    Desktop/Local Runtime device challenge。
  - M1-M6 Task-first 串行化与真实 child runtime 未交付边界。
- `git diff --check` 通过。
- 全仓纳入 Git 的 203 个 Markdown：
  - 严格 UTF-8 解码错误 0。
  - BOM 0。
  - 检查 469 个相对链接，缺失 0。
- 高置信敏感信息扫描命中 0。
- 92 个 `json` fenced block 全部可解析，错误 0。
- Auth 专项共 31 个规范化 API 端点；API 总览和总体设计书缺失均为 0。
- 陈旧拓扑、旧 bootstrap、旧 `StrictUndefined`、旧 cursor、旧锁表述和
  旧设备共享密钥返回语义扫描命中 0。
- 本轮只修改文档和计划，未运行生产代码全量测试；M1-M6 定向 pytest 的本地
  PostgreSQL 超时边界继续按本节“阻塞与风险”记录，不用历史通过数替代当前结果。
- 只暂存并提交 75 个 Markdown 文档/资料，暂存区非 Markdown 文件 0；
  `git diff --cached --check` 通过。
- 提交 `996c120`（`docs: 重构 Desktop Ops Hub 与用户权限规划`）已推送到
  `origin/feature/m7-remote-deploy-closure`。
- push 前后工作区只保留暂停中的 10 个 M7-2 Python/migration/test 草稿，文档
  工作区无未提交修改。

## 2026-07-16（M7-2 数据底座实施暂停点）

### 已完成

- M7-2 契约冻结已完成最终 P0/P1 复核、Markdown/UTF-8/链接/敏感信息门禁，
  提交 `47bdaf4`（`docs: 冻结 M7-2 候选发布与工作任务契约`）已推送
  `origin/feature/m7-remote-deploy-closure`。
- 从干净工作区开始 M7-2 第一个代码小步，当前未提交草稿已创建：
  - migration：
    `modules/platform-api/migrations/versions/20260716_0008_create_m7_release_jobs.py`
  - ORM：
    `ProjectRepositoryBinding`、`ReleaseCandidate`、`WorkflowJob`
  - ApprovalRequest 五个资源审批字段、9 个 CHECK、3 个索引和
    `ApprovalStatus.CANCELLED`
  - `models/__init__.py` 注册新表
  - 测试数据库 TRUNCATE 清单与 M7-2 migration 契约测试
- 0008 migration 已在本地开发 PostgreSQL 真实执行成功，当前开发库 Alembic head
  为 `20260716_0008`；ORM metadata 与数据库执行
  `uv run alembic check` 返回 `No new upgrade operations detected`。
- `test_database_migration.py` 已扩展为检查新表、列、约束、函数式/部分索引和
  `CASCADE/NO ACTION` 删除规则，当前独立回归 `9 passed`。
- 只读实施复核已返回 Platform API 精确文件/符号映射；仍在运行的 Workflow
  实施映射 Agent 已在暂停时中止，没有 Agent 继续写入或分析工作区。

### 进行中

- 已按用户要求暂停。migration、ORM 与 migration 测试共 10 个修改/新增文件保留
  在工作区，尚未 stage、commit 或 push；未继续实现 repository、service、API、
  Workflow Engine 或共享契约。

### 阻塞与风险

- 当前开发数据库 schema 已在未提交代码之前推进到 `20260716_0008`。恢复时必须
  先核对 `git status`、`alembic current`，并完成真实
  `downgrade 20260715_0007 -> upgrade 20260716_0008` 往返验证。
- 现有 ApprovalService 是 `Task -> Approval` 锁序。release candidate 决策必须在
  锁 Approval 前分派专用路径，并按
  `Task -> Binding -> Candidate -> Approval` 锁序重验。
- `PullRequestRecordService.create` 当前未参与 Task 行锁；恢复时必须在 PR 查重、
  supersede 和 insert 前锁 Task，避免 Candidate 对“最新 PR”的判断被并发穿透。
- `main.py` CORS 当前只允许 GET/POST；RepositoryBinding PUT 上线前必须加入 PUT。
- Candidate POST 首次创建要返回 201、幂等命中要返回 200，路由必须动态设置响应
  状态并在 OpenAPI 同时声明两种成功响应。
- migration 目前只完成 upgrade、`alembic check` 和 migration 测试；尚未执行
  downgrade/upgrade 往返、Platform API 全量 pytest、数据库负约束测试或并发测试，
  当前代码不能标记为完成。

### 下一步

1. 恢复后先执行：
   `git branch --show-current`、`git status --short`、
   `uv run alembic current`，确认分支、草稿和开发库 head 与本记录一致。
2. 复查 0008 migration 与三个 ORM 的关键 diff，执行真实 downgrade/upgrade、
   `alembic check` 和 migration test；闭环后更新本节并作为数据库小步提交/push。
3. 实现 server-controlled RepositoryProfile、Binding repository/service/PUT/GET，
   同时补 CORS PUT、幂等 PUT 与漂移失效测试。
4. 补 Task/PR 并发锁，再实现 Candidate/Approval/WorkflowJob 原子创建和专用审批
   锁序；首次 201、幂等 200。
5. 最后建立 `modules/workflow-engine` durable dispatcher/worker/heartbeat/
   reclaimer、共享 JSON Schema/OpenAPI、Redis/崩溃恢复和完整回归。

### 涉及文件

- `modules/platform-api/migrations/versions/20260716_0008_create_m7_release_jobs.py`
- `modules/platform-api/src/cloudhelm_platform_api/models/__init__.py`
- `modules/platform-api/src/cloudhelm_platform_api/models/approval.py`
- `modules/platform-api/src/cloudhelm_platform_api/models/project_repository_binding.py`
- `modules/platform-api/src/cloudhelm_platform_api/models/release_candidate.py`
- `modules/platform-api/src/cloudhelm_platform_api/models/workflow_job.py`
- `modules/platform-api/src/cloudhelm_platform_api/schemas/approval.py`
- `modules/platform-api/src/cloudhelm_platform_api/schemas/common.py`
- `modules/platform-api/tests/conftest.py`
- `modules/platform-api/tests/test_database_migration.py`

### 验证

- `uv run python -m compileall -q src migrations`：通过
- `uv run alembic upgrade head`：`20260715_0007 -> 20260716_0008` 成功
- `uv run alembic current`：`20260716_0008 (head)`
- `uv run alembic check`：`No new upgrade operations detected`
- `uv run pytest -q tests/test_database_migration.py`：`9 passed in 8.92s`
- `git diff --check`：在 migration/ORM 初稿阶段通过；暂停前尚未对全部未跟踪文件
  执行 staged diff 门禁

## 2026-07-16（M7-2 契约冻结与实施预检）

### 已完成

- 在 M7-1 Git 收口 `0d315da` 后保持
  `feature/m7-remote-deploy-closure` 与远端一致、工作区干净，直接进入
  `PROJECT_PLAN.md` 的 M7-2。
- 完成 Git、依赖、PostgreSQL 和 Redis 预检：
  - `git branch --show-current` 为当前功能分支。
  - `git status --short` 无输出。
  - `uv lock --check` 通过。
  - Alembic current 为 `20260715_0007`，`alembic check` 无待生成迁移。
  - 启动 Compose optional Redis，`redis-cli ping` 返回 `PONG`。
  - Platform API 基线回归 `153 passed, 1 skipped`。
- 并行完成 M7-2 数据/API、Approval、共享契约和 Redis/Celery 设计核验，修正原
  计划中的字段、状态和入口冲突：
  - repository identity 统一为 `repository_external_id`。
  - 远端校验 SHA 统一为 `remote_verified_sha`。
  - WorkflowJob 唯一身份统一为
    `(task_id, job_type, idempotency_key)`。
  - Candidate 状态补 `rejected`，WorkflowJob 状态补 `cancelled`。
- 正式拆分第一道审批入口：
  `POST /api/tasks/{task_id}/release-candidate` 只接受严格空对象并原子创建
  Candidate + Approval；后续 `remote-deployment/start` 只选择 Environment/
  Target 并要求已有 approved candidate，不再重复创建第一道审批。
- 固定 binding 漂移门禁：Candidate 持久化安全 snapshot JSON，并以独立 snapshot
  hash 覆盖内部 clone URL 与 credential ref；binding 更新后旧 pending/approved
  candidate 与 pending approval 同步 stale/expired。
- 固定 PostgreSQL/Redis 双写补偿：WorkflowJob 保存 side-effect class、dispatch
  lease、next/last enqueue、attempt/error；周期 dispatcher 补投，重复消息由
  PostgreSQL claim 裁决。
- 新增三张权威单表文档：
  - `docs/07-data/tables/project_repository_bindings.md`
  - `docs/07-data/tables/release_candidates.md`
  - `docs/07-data/tables/workflow_jobs.md`
  并把字段、索引、状态分类、时间不变量和 API 可见边界同步到总 schema。
- 固定 canonical/hash/ref 算法：
  - snapshot、Candidate request 和 WorkflowJob request 统一复用
    `json.dumps(..., ensure_ascii=False, sort_keys=True, default=str)` 的 UTF-8
    canonical bytes。
  - 对外 hash 统一为 `sha256:<64 lowercase hex>`。
  - Candidate 安全 snapshot 固定八字段，内部 freshness hash 额外覆盖
    `profile_key/clone_url/credential_ref`。
  - target ref 固定为
    `{release_ref_prefix}/{task_id}/{full_commit_sha}/{snapshot_hash_hex}`。
- 固定并发与事务锁序：
  - Candidate POST：
    `Task -> Binding -> PullRequestRecord -> existing Candidate`。
  - Binding PUT：
    `Binding -> Candidate(UUID 顺序) -> Approval(UUID 顺序)`。
  - 第一道审批决策：
    `Task -> Binding -> Candidate -> Approval`。
  - Worker：
    `Task -> WorkflowJob -> Binding -> Candidate -> Approval`。
- 固定第一道审批为内部保留 action：通用 Approval POST 返回
  `422 approval_action_reserved`；数据库双向约束
  `approve_release_candidate <=> release_candidate + L2`，并要求
  `requested_by_agent_run_id` 非空。plain UUID 或 `agent-run:<UUID>` actor 与 PR
  creator 相同返回 `403 approval_self_decision_forbidden`。
- 固定 M7-2 唯一生产 handler 为无外部副作用的
  `release_candidate_reconcile`；publish、CI、deploy handler 不写占位实现，留到
  对应后续纵切。
- 固定 WorkflowJob attempt 耗尽、Task pause、external cancel override、
  reconcile payload/result 精确 JSON 契约、dispatcher reserve/publish/finalize
  崩溃窗口和成功后错误字段清理；M7-2 数据库只允许真实映射
  `release_candidate_reconcile -> release_candidate -> none`。
- 将四张权威表 DDL 在 PostgreSQL 16 临时 schema 中真实建表验证并事务回滚，
  `jsonb ?&` 与 `jsonb - text[]` 运算符也已在当前数据库验证。
- 已同步 `PROJECT_PLAN.md`、数据/API/Workflow 细化设计、Approval 文档和 Roadmap
  拆分；当前仅冻结实施契约，尚未把 M7-2 代码项标记完成。

### 进行中

- 准备创建 `20260716_0008_create_m7_release_jobs.py`，并按
  migration -> ORM/repository -> service/API -> workflow-engine -> tests 的顺序
  实施。

### 阻塞与风险

- `DecisionRequest.actor_id` 仍是受控入口传入的审计字符串；M7-2 可按 AgentRun ID
  实施领域自批门禁，但不描述为不可伪造的身份认证边界。
- M7-2 不接真实 Gitea push、workflow dispatch、CIRun、registry、部署或 Remote
  operation resolver；外部 side-effect job 的 stale running 只能进入
  `recovery_required`，不能宣称已自动恢复。
- Redis 当前是本地 Docker 开发实例；生产 ACL、TLS、私网和持久化配置留到安装/
  E2E 纵切。

### 下一步

- 先提交本次 M7-2 契约冻结，再创建 0008 migration 和三个 ORM。
- 扩展 ApprovalRequest resource/hash/expiry/consumed 字段与 candidate 决策。
- 实现 profile-only RepositoryBinding PUT/GET、Candidate POST/GET 与全套负测。
- 建立 `modules/workflow-engine`、durable dispatcher、Celery worker 和真实 Redis
  集成测试。

### 涉及文件

- `PROJECT_PLAN.md`
- `docs/03-modules/modules/workflow-engine.md`
- `docs/07-data/01-database-schema.md`
- `docs/07-data/tables/project_repository_bindings.md`
- `docs/07-data/tables/release_candidates.md`
- `docs/07-data/tables/workflow_jobs.md`
- `docs/07-data/tables/approval_requests.md`
- `docs/08-api/05-approval-api.md`
- `docs/08-api/07-environment-deployment-api.md`
- `docs/14-roadmap/03-implementation-milestone-flow.md`
- `docs/15-detailed-design/03-api-detail.md`
- `docs/15-detailed-design/04-data-detail.md`
- `docs/15-detailed-design/05-workflow-state-events.md`
- `docs/15-detailed-design/09-m7-ci-remote-deployment-flow.md`

### 验证

- `docker compose -f infra/docker-compose.dev.yml --profile optional up -d redis`
- `docker exec cloudhelm-redis-dev redis-cli ping`：`PONG`
- `uv lock --check`
- `uv run alembic current`：`20260715_0007 (head)`
- `uv run alembic check`：`No new upgrade operations detected`
- `uv run pytest -q`：`153 passed, 1 skipped`
- PostgreSQL 16 临时 schema 建表：`ddl_contract_tables=8`、
  `ddl_contract_check=passed_rolled_back`
- PostgreSQL 16 JSONB 运算符：`jsonb ?&` 与 `jsonb - text[]` 均通过
- 最终独立只读契约复核：P0 `0`、P1 `0`
- 最新 21 个变更/新增 Markdown 文件：严格 UTF-8 解码错误 `0`、BOM `0`、
  相对链接缺失 `0`、敏感信息模式命中 `0`、旧字段/旧入口/占位语义命中 `0`
- `git diff --check` 通过

## 2026-07-16（M7-1 完成与 M7-2 执行指针）

### 已完成

- 在 `feature/m7-remote-deploy-closure` 上从暂停点恢复 M7-1
  `Environment + RemoteTarget + machine-auth heartbeat` 纵切，先复查暂停记录、
  暂存区、未暂存文档和 `PROJECT_PLAN.md`，再按代码/契约与文档/进度分开收口。
- 完成 `20260715_0007_create_m7_environment_remote_target.py`，真实新增并验证：
  - `environments`
  - `remote_targets`
  - `remote_agent_credentials`
  - `remote_agent_replay_nonces`
- 完成 Environment 创建、列表、详情和 profile-only RemoteTarget 注册、列表。
  Environment `base_url` 当前只保存和展示；RemoteTarget endpoint、TLS fingerprint、
  credential ref 与 secret 均由服务端 profile/secret 映射派生，普通 API 不接受
  任意连接目标或 secret。
- 完成 Remote Agent machine authentication：
  - 六个必填 HMAC header。
  - 固定 canonical：
    `METHOD\nPATH\nTIMESTAMP\nNONCE\nBODY_SHA256`。
  - timestamp tolerance、credential lifecycle/scope、secret fingerprint 漂移阻断。
  - nonce 原文不入库，由 PostgreSQL 唯一约束裁决顺序和并发 replay。
  - header 格式和 timestamp 窗口通过后，HMAC 不匹配统一返回
    `machine_auth_invalid`；target/credential lifecycle、scope 和服务端配置状态
    只在 HMAC 通过后暴露。
- 完成 heartbeat 16 KiB 原始 body 前置门禁、线程池 machine-auth、独立短
  Session、online/offline/recovery、heartbeat EventLog 降频和
  `next heartbeat * 2 < offline timeout` 配置不变量。
- 完成 `modules/remote-agent` 最小真实模块：
  - `/health`、`/version`、`/capabilities`。
  - target id 必须是 UUID，Platform API 必须是 HTTPS origin。
  - 可选 CA bundle、显式连接池/timeout、禁用环境代理与 redirect。
  - credential file 使用 `O_NOFOLLOW + fstat + 同一 fd 有界读取`。
  - heartbeat ACK 最大 16 KiB，machine secret 每次发送前重新读取。
- 暂存代码审查发现并闭环两个阻断：
  - `pydantic-settings` 复杂环境变量解析产生的 `SettingsError` 现已收敛为
    `remote_agent_configuration_invalid` 和退出码 2。
  - `httpx2` / `httpcore2` INFO 请求日志现已压到 WARNING，避免 journal 记录
    完整 Platform API 管理入口；新增真实日志回归测试。
- 同步 Platform OpenAPI、Remote Agent OpenAPI、三个 remote JSON Schema 和
  Environment/RemoteTarget/RemoteAgent 六类事件枚举。M7-1 代码与共享契约提交为
  `768c48b`（`feat: 完成 M7-1 远端目标与心跳闭环`），已推送
  `origin/feature/m7-remote-deploy-closure`。
- 同步根 README、模块文档、数据/API/安全/细化设计、`.env.example` 和两张
  machine-auth 子表文档；Roadmap 只勾选已有证据的
  Environment/RemoteTarget/machine-auth heartbeat 子项。
- M7-1 文档、Roadmap、进度和 M7-2 计划提交为 `306ae6b`
  （`docs: 收口 M7-1 并推进 M7-2 计划`），已推送当前功能分支。
- `PROJECT_PLAN.md` 当前执行指针已推进到 M7-2：
  `ProjectRepositoryBinding + ReleaseCandidate + WorkflowJob +
  Redis/Celery claim/lease/heartbeat/stale reclaim`。

### 进行中

- M7-2 尚未开始写生产代码。当前只完成下一纵切的精确文件、migration、契约、
  测试、文档和验收清单，不把完整 M7 数据、CI 或部署能力描述为已实现。

### 阻塞与风险

- offline 当前只由 RemoteTarget 列表访问或下一次 heartbeat reconciliation
  触发；Celery 周期 worker 尚未落地，不具备自主定时离线检测。
- M7-1 Environment/RemoteTarget/RemoteAgent 事件以 `task_id=null` 写入 EventLog；
  项目/环境查询 API 和实时 SSE 留到后续 M7。
- Environment `base_url` 在后续接入健康检查前必须经过服务端 profile/allowlist，
  不得直接变成任意 URL 请求入口。
- 真实 Gitea CI、registry OCI digest、ReleaseCandidate、两道审批、远端部署、
  控制台 M7 页面和 Linux staging E2E 均未交付。
- 当前项目版本继续保持 `0.5.1`；完整 M7 验证和真实远端 E2E 完成后才提升到
  `0.6.0`。

### 下一步

- 创建 `20260716_0008_create_m7_release_jobs.py`，实现
  `project_repository_bindings`、`release_candidates`、`workflow_jobs` 及
  upgrade/downgrade/check。
- repository binding API 只接受服务端 repository profile key，不接受任意 URL、
  token、workflow path、remote 或 refspec。
- ReleaseCandidate 必须绑定最新 M6 PullRequestRecord、完整 commit、受控 target
  ref、request hash 和第一道审批；审批前不产生 push 或 CI 副作用。
- 建立 `modules/workflow-engine` 的 Redis + Celery 基础，PostgreSQL
  `workflow_jobs` 作为业务权威；Celery message 只携带 job id，并完成短事务
  claim/lease/heartbeat/stale reclaim、hard-crash 与 `recovery_required` 测试。

### 涉及文件

- `modules/platform-api/migrations/versions/20260715_0007_create_m7_environment_remote_target.py`
- `modules/platform-api/src/cloudhelm_platform_api/{api,core,middleware,models,providers,repositories,schemas,services}/`
- `modules/platform-api/tests/test_m7_*.py`
- `modules/remote-agent/**`
- `packages/shared-contracts/openapi/*.yaml`
- `packages/shared-contracts/schemas/remote/*.schema.json`
- `packages/shared-contracts/schemas/events/task-event.schema.json`
- `docs/07-data/**`
- `docs/08-api/07-environment-deployment-api.md`
- `docs/10-security/00-security-boundary.md`
- `docs/14-roadmap/03-implementation-milestone-flow.md`
- `docs/15-detailed-design/{03-api-detail.md,04-data-detail.md,07-testing-acceptance-matrix.md,09-m7-ci-remote-deployment-flow.md}`
- `PROJECT_PLAN.md`

### 验证

- Platform API：`uv run pytest -q`，`153 passed, 1 skipped`。
- Remote Agent Windows：`uv sync --locked` 后 `uv run pytest -q`，
  `31 passed, 2 skipped`。
- Remote Agent Linux 容器：只读挂载仓库根后执行 locked sync 与 pytest，
  `33 passed`。首次只挂载模块目录时测试无法定位共享契约根；改为只读挂载完整
  仓库后回归通过，未修改生产代码或跟踪文件。
- Alembic：
  - 开始与结束 head 均为 `20260715_0007`。
  - downgrade 到 `20260714_0006` 后四张 M7-1 表全部消失，`tasks` 等 M1-M6
    表保留。
  - upgrade 回 `20260715_0007` 后四表恢复。
  - `uv run alembic check` 返回 `No new upgrade operations detected`。
- Platform OpenAPI 与 FastAPI 运行时精确一致；当前为 45 paths、64 schemas。
- 29 个共享 JSON Schema 均通过 Draft 2020-12 元校验。
- M7-1 暂存文件严格 UTF-8 解码错误 0、BOM 0；生产路径敏感模式命中 0。
- `git diff --cached --check` 在代码提交前通过；当前文档 diff 的严格 UTF-8
  解码错误 0、BOM 0、Markdown 本地链接缺失 0、敏感模式命中 0，
  `git diff --check` 通过。
- `306ae6b` 推送后执行 `git status --short` 无输出；
  `origin/feature/m7-remote-deploy-closure` 与本地 HEAD 一致。

## 2026-07-15（M7-1 首个代码纵切暂停点）

### 已完成

- M7-0 设计闭环已经提交并推送；当前功能分支为
  `feature/m7-remote-deploy-closure`，开始本次代码纵切前的远端基线为
  `091cab2`。
- 按 `PROJECT_PLAN.md` 启动首个真实代码纵切
  `Environment + RemoteTarget + machine-auth heartbeat`，并在用户要求暂停后
  中止 `m7_platform_slice_impl` 与 `m7_remote_agent_slice_impl` 两个写代码
  agent；当前没有继续运行的本纵切 subagent 或遗留 pytest/uv 子进程。
- Platform API 已落地但尚未收口的本地草稿包括：
  - `20260715_0007_create_m7_environment_remote_target.py` migration。
  - Environment、RemoteTarget、RemoteAgentCredential、
    RemoteAgentReplayNonce ORM。
  - RemoteTarget server-controlled profile 配置与 provider。
  - Environment/RemoteTarget repository 和 Pydantic schema 草稿。
- `modules/remote-agent` 已形成未提交的模块草稿，包含 `pyproject.toml`、
  `uv.lock`、README、`/health`、`/version`、`/capabilities`、凭据文件读取、
  HMAC canonical/signature、HTTPX heartbeat client、CLI/worker 和 20 个测试
  node id。
- 已在三份 M7 API/细化设计文档中补充 machine-auth 精确请求头和 canonical
  string：
  `METHOD\nPATH\nTIMESTAMP\nNONCE\nBODY_SHA256`，signature 为 lowercase hex
  HMAC-SHA256。
- 当前 32 个变更/新增文件均可严格 UTF-8 解码，BOM 0；`git diff --check`
  通过。

### 进行中

- 已按用户要求暂停。当前 Platform API 草稿尚未接入 service、API router、
  machine-auth dependency、heartbeat 状态事务、`main.py` 和测试夹具，因此
  Environment/RemoteTarget/heartbeat 端点目前不可调用。
- `modules/remote-agent` 文件与测试已经生成，但 agent 在返回最终验证结果前被
  中止；`.pytest_cache` 记录 20 个收集到的 node id 且没有 `lastfailed` 文件，
  该缓存不能替代本线程重新执行 `uv run pytest` 的正式证据。

### 阻塞与风险

- 本次暂停点包含未提交的生产代码草稿；这些代码未执行完整 review、pytest、
  Alembic upgrade/downgrade/check、OpenAPI 精确匹配或共享 JSON Schema 校验，
  不得描述为已实现。
- Platform API 基线回归 `uv run pytest -q` 在 184 秒命令上限处被终止，未取得
  通过或失败结论；终止时没有保留可用于判定的完整 pytest 结果。
- `20260715_0007` 尚未应用到开发库，也未验证 downgrade；当前已确认的开发库
  Alembic head 仍是 `20260714_0006`，暂停前 `alembic check` 为
  `No new upgrade operations detected`。
- OpenAPI、共享 Environment/RemoteTarget/Heartbeat JSON Schema、事件枚举、
  根 README、`.env.example` 和控制台类型尚未同步。
- 当前离线判断设计只计划由 target list/detail/heartbeat reconciliation
  触发；在 Redis/Celery 周期调度落地前，不能宣称自主实时离线检测。
- `EventLog` 当前仍主要按 Task 查询，Environment/RemoteTarget 事件的项目级查询
  与 M7 实时 SSE 尚未实现。
- Roadmap 继续只勾选 M7-0；数据、API、machine authentication、Remote Agent
  heartbeat 等 M7 实现项均保持未完成。

### 下一步

- 恢复时先重新检查 `git status --short` 和本暂停记录，再 review 当前未提交
  diff；不要直接把草稿标记完成。
- 完成 Platform API service/repository 事务边界、API router、machine-auth
  dependency、nonce 并发唯一、online/offline/recovery 事件与真实 PostgreSQL
  测试。
- 在本线程重新执行 `modules/remote-agent` 的 `uv sync --locked`、
  `uv run pytest` 和运行端点 smoke test，确认 agent 中止前生成的模块状态。
- 同步 OpenAPI、JSON Schema、事件契约、README、环境变量和 API 文档；完成
  Alembic upgrade/downgrade/upgrade/check、黑盒/白盒测试和敏感信息检查。
- 只有上述验证全部通过后，才更新 Roadmap 对应实现项、提交代码并推送当前
  功能分支。

### 涉及文件

- `modules/platform-api/migrations/versions/20260715_0007_create_m7_environment_remote_target.py`
- `modules/platform-api/src/cloudhelm_platform_api/core/config.py`
- `modules/platform-api/src/cloudhelm_platform_api/models/**`
- `modules/platform-api/src/cloudhelm_platform_api/providers/**`
- `modules/platform-api/src/cloudhelm_platform_api/repositories/**`
- `modules/platform-api/src/cloudhelm_platform_api/schemas/**`
- `modules/remote-agent/**`
- `modules/README.md`
- `docs/08-api/07-environment-deployment-api.md`
- `docs/15-detailed-design/03-api-detail.md`
- `docs/15-detailed-design/09-m7-ci-remote-deployment-flow.md`

### 验证

- 已执行 `git diff --check`，当前未提交 diff 通过。
- 已对 32 个变更/新增文件执行严格 UTF-8 与 BOM 检查，错误 0、BOM 0。
- 已执行 `docker compose -f infra/docker-compose.dev.yml ps`，本地 PostgreSQL
  容器为 healthy；`127.0.0.1:15432` TCP 可达。
- 已执行 `uv run alembic current`、`uv run alembic heads` 和
  `uv run alembic check`；暂停前数据库与代码 head 均为 `20260714_0006`，
  check 无待生成迁移。
- Platform API 全量 pytest 在 184 秒命令上限处被终止，未记录为通过。
- 未执行当前草稿的 migration、Platform API M7 测试、Remote Agent 正式测试、
  OpenAPI/JSON Schema 契约测试、前端测试或远端 E2E。

## 2026-07-15（M7-0 CI/CD 与远端部署设计闭环）

### 已完成

- 在 `feature/m7-remote-deploy-closure` 上完成 M7-0，工作基线为
  `b4243ef`；本次只收敛设计、契约、资料和执行计划，不提前宣称 M7
  生产能力已经实现。
- 新增 `docs/15-detailed-design/09-m7-ci-remote-deployment-flow.md`，固定
  Gitea CI、Release / Deploy Agent、Tool Gateway、Deployment Controller、
  Remote Agent、双审批、远端部署和 Monitoring 交接的完整拓扑、状态、身份、
  风险、失败恢复与 E2E 证据。
- 将异步执行器固定为 Redis + Celery，同时以 PostgreSQL `workflow_jobs`
  保存业务权威、claim、lease、heartbeat、retry、stale reclaim 和
  `recovery_required`；Celery task 只携带 `workflow_job_id`，不得携带 secret、
  任意 URL、Compose 或自由命令。
- 固定两道独立审批：release candidate approval 绑定 PullRequestRecord、精确
  commit、受控 repository binding 和 target ref；deployment approval 绑定
  CIRun、CI manifest、不可变 OCI digest、ReleasePlan、Environment 与
  RemoteTarget。实现代码、提交或 PR record 的 AgentRun 不得自批。
- 固定 CI 唯一触发方式为受控 ref 上的 `workflow_dispatch`；workflow 不监听
  push，CI 只执行 test/security/build/artifact，不执行 SSH、Compose 上线、
  Remote Agent 调用、服务重启或部署 webhook。
- 固定 Remote Agent 为 M7 唯一远端部署执行入口；SSH 仅允许审批后的固定只读
  诊断。M7 使用受控 Docker Compose、远端 credential file/store 和不可变 OCI
  digest，并在 pull 后复核 `RepoDigests`；Ansible、Kubernetes、Argo CD、
  交互终端和 production 属于后续增强范围。
- 明确 M7 只提供 Remote Agent 受限直读日志，M8 再接 Loki 集中检索；M7
  只生成 rollback candidate/request，不自动执行回滚。
- 同步总体设计书、架构、技术栈、部署工作流、数据、API、远程接管、详细设计、
  测试验收矩阵、文档索引和 Roadmap；移除旧 `POST /api/deployments`、可变
  `image_tag`、CI 直连部署与 M7 交互终端等冲突语义。
- 核验并补齐 `informations/m7-ci-remote-deploy/official-references.md` 与
  `reference-projects.md`。共检查 76 个唯一 URL，74 个在批量 HTTP 检查中直接
  成功；两个 Celery 官方页面因自动化请求频率返回 429，已单独打开官方页面
  确认内容可达。
- 细化 `PROJECT_PLAN.md` 的固定实施顺序、文件清单、逐任务验证、证据和 Roadmap
  映射；首个生产代码纵切固定为
  `Environment + RemoteTarget + machine-auth heartbeat`。
- 将 Roadmap 仅有证据支撑的 M7-0 设计项标记为完成；migration、worker、API、
  CI、Remote Agent、Controller、Tool、Agent、控制台和远端 E2E 等实现项继续
  保持未完成。
- M7-0 设计闭环提交为 `e7373b0`（`docs: 完成 M7 CI 与远端部署细化设计`），
  已推送并建立远端跟踪分支
  `origin/feature/m7-remote-deploy-closure`。

### 进行中

- M7 已从计划准备进入首个代码纵切实施前状态；尚未创建 M7 migration、生产
  API、Celery worker 或 Remote Agent 模块。

### 阻塞与风险

- 当前尚无真实 Gitea Actions run、registry OCI digest、Linux staging 主机、
  Remote Agent systemd 服务或远端部署 E2E 证据，因此 M7 总里程碑不得标记完成。
- M7 当前项目版本仍为 `0.5.1`；只有完整 M7 代码、契约、黑盒/白盒测试和真实
  远端 E2E 通过后才允许升级到 `0.6.0`。
- 官方 URL 批量检查可能触发站点限流；限流结果不等同于失效链接，后续资料更新
  应保留有界重试与单页复核记录。

### 下一步

- 先实现 Environment、RemoteTarget、machine credential/replay nonce 数据表和
  Alembic migration，并验证 upgrade、downgrade 与 `alembic check`。
- 按 `api -> schemas -> services -> repositories -> models` 分层实现 Environment
  创建/列表/详情、RemoteTarget 注册/列表和
  `POST /api/remote-agents/heartbeat`。
- machine authentication 签名覆盖
  `method + path + timestamp + nonce + body_sha256`，补齐跨 target、过期、
  撤销、重复 nonce 和新旧 key 轮换测试。
- 建立最小真实 `modules/remote-agent`，提供 `/health`、version/capabilities、
  `_FILE` credential 配置和签名 heartbeat client。
- 同步 OpenAPI、Heartbeat/Environment/RemoteTarget JSON Schema、事件文档和
  Roadmap；完成真实 PostgreSQL 黑盒/白盒测试后再勾选对应实现项。

### 涉及文件

- `PROJECT_PLAN.md`
- `PROJECT_PROGRESS.md`
- `云舵 CloudHelm 毕设设计书.md`
- `docs/00-project/02-references.md`
- `docs/01-architecture/**`
- `docs/02-tech-stack/**`
- `docs/06-workflows/**`
- `docs/07-data/01-database-schema.md`
- `docs/08-api/**`
- `docs/12-deployment/01-remote-demo-deployment.md`
- `docs/14-roadmap/03-implementation-milestone-flow.md`
- `docs/15-detailed-design/**`
- `informations/m7-ci-remote-deploy/**`

### 验证

- 已执行 `git diff --check`，通过。
- 已对 37 个变更/新增 Markdown 执行严格 UTF-8 解码和 BOM 检查，错误 0、
  BOM 0。
- 已检查上述 Markdown 中 189 个相对链接，失效 0。
- 已扫描旧 `POST /api/deployments`、可变 `image_tag`、CI 直连 Deployment
  Controller 和 M7 交互终端语义，有效冲突 0。
- 已扫描高置信私钥、Token、密码赋值和公网 IPv4，命中 0。
- 已执行 `git ls-remote --heads origin feature/m7-remote-deploy-closure`，
  远端分支指向 `e7373b09eee2c692a7f1eaf5da74a688b120748f`。
- 本次为文档、契约和资料闭环，未运行 pytest、Alembic、前端 build、真实 CI
  或远端 E2E；这些验证将在对应生产代码子任务完成后执行并记录。

## 2026-07-14 至 2026-07-15（M1-M6 成果核验与缺陷修复，0.5.1 已同步基线）

### 已完成

- 按 `AGENTS.md`、总体设计书、MVP 裁剪线、模块/API/Agent/Tool 契约和测试验收
  矩阵重新核验 M1-M6；新增
  `docs/13-testing/01-m1-m6-audit-report.md` 记录发现、处理和准确交付边界。
- 修复 Platform API 测试会重建开发库的问题：默认创建并删除会话级随机
  `cloudhelm_test_<pid>_<uuid>` 数据库；显式测试库必须包含独立 `test` 段并
  设置 `CLOUDHELM_TEST_ALLOW_SCHEMA_RESET=true`。
- 修正 Task 取消语义，只更新 `status=cancelled` 并保留最后
  `current_phase`；数据库异常响应不再回显 SQLAlchemy/SQL 细节，ToolCall
  `result_summary`、结果 JSON 和 Artifact API preview 均执行脱敏。
- 修复控制台 Task A→B 切换竞争：切换后立即隐藏旧详情，旧 HTTP、SSE 和
  timer 不能覆盖新 Task；失败/取消 AgentRun 按真实 `started_at` 排入
  Timeline。
- 使用真实 Platform API、隔离 PostgreSQL 数据库和 Playwright Edge 复核控制台：
  Project/Task 列表、Task B→A 切换、Requirement、Agent Timeline 与 Event Log
  均保持同一 Task 数据，桌面与 `390x844` 移动视口无框架错误。首次检查发现
  favicon 404，已补充 `public/favicon.svg`，复测控制台为 0 error / 0 warning。
- 为 M4 `start/run-next` 增加可选 `expected_phase` 前置条件和 Task 行锁；
  控制台始终发送当前阶段，阶段已变化时返回稳定
  `409 orchestration_phase_changed`，避免重复点击跨两个 Agent 步骤推进。
- 收紧 `local_structured`：只覆盖受控 auth/profile demo issue 与 CloudHelm
  自身 M4 核验任务；其他领域返回 `unsupported_local_recipe` 并暂停，不再
  保存固定伪设计。auth/profile 的 OpenAPI、SQLite `users` schema、安全设计
  和五步开发计划均与 sample recipe 对齐。
- Requirement、Architect、Planner 按输入、输出和风险项最高值传播风险；
  Requirement 新识别的更高风险写回 Task，L2-L4 设计强制人工审批，计划审批
  保留 Planner 最高风险，后续角色不能把已识别风险降级。
- execution recipe 升级为 `schema_version=1.1`，每条 AC 必须声明稳定
  `testcase_names`；Tester 读取真实 JUnit 逐 AC 映射，缺失/跳过为
  `not_covered`、failure/error 为 `failed`，XML 错误或截断不会宣称通过。
- Reviewer 增加完整证据门禁：`changed_files`、`diff_paths` 与 Git 工具结果
  必须非空、唯一且精确一致；patch 必须完整未截断，新增/修改/删除文件头必须
  正确；受控 auth/profile 还必须包含约定模块、测试文件和领域 marker。
- 修复 patch 证据链：ToolCall 只持久化脱敏安全投影和原始 patch SHA；
  `diff_patch`、`format_patch` Artifact 保存原始 UTF-8 bytes、大小和 SHA，
  原始结果只在执行进程和受控 Artifact 中使用。未跟踪文件 diff 补齐标准
  `diff --git` 文件头；Git Tool 先读取完整输出再按调用上限截断，确保
  `patch_truncated` 不会误报 `false`。`implementation.diff` 与 format patch
  均通过真实 `git apply --check`。
- 纠正文档漂移：当前 Orchestrator 是显式 Python 状态机，M6 Sandbox 是
  allowlist Task workspace + 受控 `subprocess`；LangGraph、独立 Docker
  sandbox、远端 PR/CI/部署、监控和 SRE 均未写成 M1-M6 已交付能力。
- 按用户新增要求复核 2026-07-14 最新 Codex manual，并把 Agent 使用与沟通
  规则固化到 `AGENTS.md`：root thread 保留目标/决策/汇总，显式 child 承担
  有界独立任务，read-heavy 可并行，写共享 workspace/Git 状态的任务串行或
  隔离，父线程只接收最终摘要和证据引用。
- 参考 Codex CLI 的 thread/subagent 协作模型，将 CloudHelm 自有配置固定为
  `max_depth=1`、`max_active_children=6`；该数量表示 active child，不描述为与
  Codex CLI 并发 thread 配置精确等价。child 权限按父级或更严格边界重新经 Tool Gateway 判定，
  最终摘要必须非空、脱敏且不超过 4000 字符。新增递归 spawn 拒绝、空/超长
  摘要拒绝和敏感摘要脱敏回归。
- 补齐 subagent 叶子优先生命周期与执行期门禁：`coder/scaffold` child、跨
  Task root、legacy role、终态 child 工具调用、存在 active AgentRun 或 active
  后代时提前完成和 Task paused 时 spawn 均有直接回归；Task terminal/cancel
  入口由 service guard 与取消级联覆盖。paused/cancelled/failed/done 下
  `complete_subagent` 的参数化直接回归仍应在后续补齐。每次 Tool Gateway 调用
  重新校验 active lineage 和父子工具交集。
- 幂等 replay 现在比较 execution-policy fingerprint；claim 前上下文拒绝和策略
  漂移会写入不含原始参数的 `ToolCallRejected` 事件，晚到结果继续保留
  subagent scope 与策略 fingerprint，不改写原 ToolCall 审计事实。
- 统一采用 Task-first 串行化：pause/resume/cancel、Requirement、Design、
  Approval 与 subagent conversation 写操作均先锁 Task，再按具体用例锁定所需
  AgentRun/ToolCall/Conversation/Approval；不把各路径描述为一条完全相同的总锁序。
  并发 pause/cancel、cancel/spawn、design review/spawn 回归未出现终态复活或
  active child 残留。
- 明确恢复边界：当前只承诺能够进入应用错误处理或留下幂等证据的失败恢复；
  进程 hard crash 后尚无 lease、heartbeat 或 stale reclaim。
- 形成并同步 M1-M6 核验修复版 `0.5.1`：项目、Platform API、Tool Gateway、控制台
  和 OpenAPI 为 `0.5.1`，Agent Runtime 为 `0.4.1`，未改动的 Orchestrator
  保持 `0.4.0`；本轮不创建 `v0.5.1` tag，M7 目标版本仍为 `0.6.0`。
- 按子系统完成并逐次推送 `dev`：`0bc15df`（Platform API、共享契约与并发/
  subagent 门禁）、`116ffc4`（Agent Runtime 与 Tool Gateway 证据链）、
  `63b0f05`（控制台竞态、Timeline 与 favicon）、`5e0d8e4`（文档、计划、
  审计报告与进度同步）。

### 进行中

- M1-M6 核验、修复、全量回归、文档和 Git 同步均已完成。M7 生产实现尚未
  开始，下一步严格按 `PROJECT_PLAN.md` 从已同步基线进入功能分支。

### 阻塞与风险

- Platform API 进程在终态持久化前被强制终止时，active AgentRun/ToolCall
  仍需依据数据库和 workspace 证据人工核验；该边界不应在答辩中描述为自动
  恢复。
- M4 当前为保证单步正确性，会在一次 Provider 调用期间持有 Task 行锁；
  单用户 MVP 可接受，但并发 worker 阶段应改为短事务 claim + lease，避免
  pause/cancel 长时间等待。
- M6 仍为受控本地 `subprocess`，没有 Docker CPU、内存、PID、只读挂载和
  网络隔离；M7 接入 staging/demo 前必须再次评估隔离方案。
- Codex CLI 的 steer 当前 turn / queue 下一 turn 尚未形成 CloudHelm 通用用户
  消息 API；M1-M6 当前只有审批上下文、暂停/取消与 subagent notification，
  已在契约中标明为后续交互能力。
- 同一恶意 replay 请求当前会逐次写入 `ToolCallRejected`，保证每次拒绝可审计；
  后续开放公网入口时可再增加请求级限流或事件去重，避免拒绝事件风暴。
- 外部 LLM/Prompt Cache 条件测试因未注入 endpoint/key 而显式跳过；Windows
  symlink 测试因当前账户权限显式跳过。其余本地 Provider、路径拒绝、契约、
  状态机和证据门禁均已执行。
- `informations/m7-ci-remote-deploy/` 是本轮开始后出现的 M7 资料目录，不属于
  M1-M6 核验修改，未纳入本轮 diff、测试结论或提交范围。

### 下一步

- 按 `PROJECT_PLAN.md` 从 `0.5.1` 已同步跟踪基线进入 M7，先核验并归档
  Gitea Actions、OCI digest、Remote Agent、Deployment Controller、TLS 和
  systemd 官方实践。
- 在 M7 worker/remote execution 设计中明确 lease、heartbeat、stale reclaim
  与人工恢复流程，不把 hard crash 残留记录留作隐含行为。
- 继续保持 CI 只生成不可变制品，真实部署只允许经 Release / Deploy Agent、
  Tool Gateway、Deployment Controller 和 Remote Agent 链路执行。

### 涉及文件

- `apps/control-console/**`
- `AGENTS.md`
- `modules/platform-api/**`
- `modules/agent-runtime/**`
- `modules/tool-gateway/**`
- `packages/shared-contracts/**`
- `examples/sample-repo-python/demo-issues/**`
- `.env.example`
- `README.md`
- `PROJECT_PLAN.md`
- `PROJECT_PROGRESS.md`
- `docs/01-architecture/**`
- `docs/03-modules/**`
- `docs/04-agents/**`
- `docs/06-workflows/00-development-to-pr.md`
- `docs/08-api/11-local-development-api.md`
- `docs/12-deployment/00-local-development.md`
- `docs/13-testing/**`
- `docs/14-roadmap/03-implementation-milestone-flow.md`
- `docs/15-detailed-design/**`
- `informations/m4-agent-context/codex-responses-context.md`
- `informations/m6-code-test-pr/official-references.md`

### 验证

- Tool Gateway：`uv lock --check`；`uv run pytest -q` ->
  `45 passed, 1 skipped`。skip 为 Windows symlink 权限条件。
- Agent Runtime：`uv lock --check`；`uv run pytest -q` ->
  `61 passed, 1 skipped`。skip 为外部 LLM/Prompt Cache 凭据条件。
- Orchestrator：`uv lock --check`；`uv run pytest -q` -> `7 passed`。
- Platform API：`uv lock --check`；`uv run pytest -q` ->
  `130 passed, 1 skipped`。skip 为外部模型配置条件；其中 Task-first 串行化与
  subagent 权限/生命周期定向回归 `16 passed`。
- 控制台：`npm.cmd test` -> `17 passed`；`npm.cmd run build` 成功，
  Vite 共转换 `77 modules`。
- 控制台浏览器黑盒：Browser 插件运行时未注入，记录 `agent=undefined` 后使用
  Playwright Edge；真实 API 页面加载、Task B→A 切换、详情/Requirement/
  Timeline/Event Log 一致性、桌面和 `390x844` 视口均通过，favicon 修复后
  console 为 0 error / 0 warning。
- sample repo：`uv lock --check`；`uv run pytest -q` -> `2 passed`；
  Bandit 为 0 finding；pip-audit 无已知漏洞，并按工具真实行为记录本地包
  `cloudhelm-sample-service==0.1.0` 不在 PyPI 而跳过。
- 数据库迁移：在隔离 PostgreSQL 临时库执行 `upgrade head -> alembic check
  -> downgrade base -> upgrade head`；结果为 `20260714_0006 (head)`、13 张
  业务/版本表且无 schema 漂移，临时库已删除。
- 真实 M4→M6 E2E 完成；`implementation.diff` 与 format patch 均通过
  `git apply --check`。
- sample Docker：`docker compose config`、真实 image build、容器
  `/health` 和 `/metrics` smoke 均通过；验证后已删除临时容器和镜像。
- FastAPI OpenAPI 与共享 YAML 反序列化后精确一致：
  `version=0.5.1`、`paths=41`、`schemas=56`、`operations=47`；全部 `26`
  份共享 JSON Schema 通过 Draft 2020-12 元 schema 校验。
- 开发库数据计数保持
  `projects=1 / tasks=1 / agent_runs=3 / tool_calls=0 / artifacts=0 /`
  `pull_request_records=0 / event_logs=23`，无残留 `cloudhelm_test_*` 数据库。
- 静态门禁：`git diff --check` 通过；本轮 84 个新增/修改生产源码均不超过
  300 行；588 个文本文件 UTF-8 解码错误 0、BOM 0；405 个 Markdown 相对链接
  失效 0；生产源码、配置和文档高置信凭据命中 0。测试目录中的 4 个模拟凭据
  均为脱敏功能 fixture，不进入生产路径。
- Git 收口：四个代码/契约/控制台/文档提交均已逐次 `git push origin dev`；
  `origin` 为 `https://github.com/ChaceQC/CloudHelm.git`。最终检查确认本轮
  跟踪文件 HEAD 与 `origin/dev` 一致；`informations/m7-ci-remote-deploy/`
  仍按下一阶段资料保持未跟踪，不属于本轮提交。

## 2026-07-14（M6 本地代码、测试与等价 PR 闭环完成，版本 0.5.0）

### 已完成

- 完成 M6 受控 sample repo：`examples/sample-repo-python` 提供真实 FastAPI
  `/health`、`/metrics`、pytest、Dockerfile、Compose、稳定 demo issue 和
  execution recipe；源 fixture 只读，Scaffold 为每个 Task 创建独立 workspace
  和 baseline Git。
- 实现 Scaffold、Coder、Tester、Reviewer、Security 五类普通 Agent；与
  Requirement、Architect、Planner 一起复用同一 Task root conversation，
  保持稳定扁平输出 schema、完整工具清单、真实 call/output 配对和供应商
  usage / Prompt Cache 证据。
- Coder 依据已审批 recipe 真实修改 sample repo；Tester 通过
  `test.run_pytest` 运行真实 pytest 和 JUnit；Reviewer 逐项核对真实 diff 与
  Acceptance Criteria；Security 通过 `security.run_bandit` 和
  `security.run_pip_audit` 保存真实扫描结果。
- Tool Gateway 增加 Scaffold/Test/Security/Git format-patch 生产工具、服务端
  workspace 绑定、Pydantic 参数校验、命令 profile、超时、输出上限、限流、
  幂等、审计和路径脱敏；M6 AgentRun 的工具名称、规范化参数和调用次数精确
  绑定已审批 execution recipe。
- 阻止公开 Tool Gateway HTTP 入口绕过 M6 executor；未批准调用只保存失败
  ToolCall 和 execution-policy 指纹，不执行文件、命令或 Git 副作用。
- 加固并发和失败恢复：PostgreSQL partial unique index 保证同一 Task 只有一个
  active M6 AgentRun；双 `run-next` 只有一个执行者；暂停/取消后的晚到工具
  结果不能覆盖终态；失败步骤保存真实 call/output 和
  `<failed_step_context>`，便于后续重试。
- 新增 `artifacts`、`pull_request_records`、AgentRun workflow identity、
  ToolCall provider identity 和 migration `20260714_0006`。Artifact 使用受控
  文件存储、SHA-256、大小、Task 级幂等和安全预览，不向 API 暴露 storage key
  或本机绝对路径。
- 完成本地 Git 收尾：创建 `codex/task-*` 分支、显式文件 commit、
  `format-patch` Artifact，以及 `provider=local`、`url=null` 的等价 PR
  record；diff/test/review/security 四类门禁证据必须属于同一
  DevelopmentPlan、recipe 和 evidence set。
- 状态聚合只读取当前 DevelopmentPlan 与当前 recipe 的 Artifact/PR；旧计划、
  旧 recipe 或无效门禁证据即使创建时间更晚也不会串入当前 M6 状态。
- Platform API 新增 M6 start/run-next/state、Artifact、PR record 接口和 13 类
  M6 事件；OpenAPI、事件 schema、Agent/Artifact/Tool JSON Schema 和前端类型
  已同步。
- 控制台新增本地开发动作、Diff、Test、Review、Security、本地 PR record 和
  M6 SSE 展示；真实浏览器 QA 发现并修复 1024px 下双列证据卡异常等高拉伸，
  单列断点调整为 1100px，grid item 改为顶部对齐。
- 同步 README、Agent/Tool/API/Data/Security/Testing/detailed-design 文档和
  `informations/m6-code-test-pr/official-references.md`；总排期 M6 已打钩。
- 项目版本提升到 `0.5.0`；Platform API、Tool Gateway 和控制台为 `0.5.0`，
  Agent Runtime 与 Orchestrator 为 `0.4.0`。`PROJECT_PLAN.md` 已按下一阶段
  重写为 M7“CI/CD 与远端部署闭环”详细执行计划，目标版本 `0.6.0`。

### 进行中

- M6 代码、契约、文档、测试、浏览器和本地 PR 验收均已完成。
- 下一阶段按新的 `PROJECT_PLAN.md` 准备 Gitea Actions、不可变制品、
  Release / Deploy Agent、Deployment Controller 和 Remote Agent 的 M7
  真实远端 staging/demo 闭环。

### 阻塞与风险

- M6 Sandbox 仍是服务端绑定的受控目录 + subprocess，不具备 Docker 的
  CPU、内存、PID、只读挂载和网络隔离；已在文档和 SecurityReport 中保留
  边界，M7 继续收敛 Docker/远端执行隔离。
- 当前进程未注入外部 LLM endpoint/key，因此外部 Agent 编排和真实供应商
  Prompt Cache 条件测试未执行；本地结构化 Provider、稳定 schema/tools、
  conversation 和失败恢复契约已完整回归。
- Windows 当前账户缺少创建测试 symlink 的权限，Tool Gateway 对应单项测试
  条件跳过；正常路径、越界和敏感路径拒绝均已执行。
- pip-audit 无已知第三方依赖漏洞，但本地包
  `cloudhelm-sample-service==0.1.0` 不在 PyPI，工具按真实行为记录跳过原因；
  未把该项伪造成已审计的零风险。
- M6 只产生本地 branch、commit、format patch 和等价 PR record，不 push、
  不创建真实 GitHub/Gitea PR，也不执行 CI/CD、SSH、远端部署或监控。

### 下一步

- 从干净 `dev` 创建 `feature/m7-remote-deploy-closure`，按 M7 计划先完成
  CI/远端部署细化设计与官方资料归档。
- 建立受控 Gitea Actions + runner + registry，确保 CI 只执行
  test/security/build/artifact，不在 CI 内部署。
- 实现 Release / Deploy Agent、Deploy Tool、Remote Control Tool、
  Deployment Controller 和 Remote Agent，并让 Task 在部署健康后进入
  `Monitoring`。
- 真实 Linux staging/demo 主机、TLS、registry 或远端 E2E 未就绪时，M7
  保持阻塞，不把本地 fake 或固定返回写成部署完成。

### 涉及文件

- `examples/sample-repo-python/**`
- `modules/agent-runtime/**`
- `modules/orchestrator/**`
- `modules/tool-gateway/**`
- `modules/platform-api/**`
- `apps/control-console/**`
- `packages/shared-contracts/**`
- `docs/03-modules/**`
- `docs/04-agents/**`
- `docs/05-tool-layer/**`
- `docs/06-workflows/00-development-to-pr.md`
- `docs/07-data/**`
- `docs/08-api/**`
- `docs/09-control-console/**`
- `docs/10-security/**`
- `docs/12-deployment/00-local-development.md`
- `docs/15-detailed-design/**`
- `informations/m6-code-test-pr/official-references.md`
- `.env.example`
- `.gitignore`
- `README.md`
- `PROJECT_PLAN.md`
- `docs/14-roadmap/03-implementation-milestone-flow.md`

### 验证

- 开发分支：`feature/m6-local-dev-closure`，基线为 `origin/dev` 的
  `615ab2e`。
- 按可验证范围提交：
  `a09d80c feat: 完成本地 Agent 工具与样例仓库闭环`、
  `da8a3ca feat: 持久化 M6 工作流证据与等价 PR`、
  `3d99fe4 feat: 展示 M6 本地开发与质量证据`、
  `a021709 docs: 同步 M6 验收并规划 M7`。功能分支已 push 到
  `origin/feature/m6-local-dev-closure`，随后以 fast-forward 合并到 `dev`
  并 push `origin/dev`。
- Platform API：`uv lock --check`；最新全量 `uv run pytest -q` ->
  `103 passed, 1 skipped`。唯一 skip 为未注入真实外部 LLM endpoint/key。
- 数据库：真实 PostgreSQL `127.0.0.1:15432`；执行
  `alembic downgrade 20260711_0005`、`alembic upgrade head`、
  `alembic check` 和 `alembic current`，结果为
  `20260714_0006 (head)` 且 `No new upgrade operations detected`。
- Agent Runtime：`uv lock --check`；`uv run pytest -q` ->
  `42 passed, 1 skipped`。唯一 skip 为外部 Prompt Cache 凭据条件。
- Tool Gateway：`uv lock --check`；`uv run pytest -q` ->
  `43 passed, 1 skipped`。唯一 skip 为 Windows symlink 权限条件。
- Orchestrator：`uv lock --check`；`uv run pytest -q` -> `7 passed`。
- sample repo：`uv lock --check`；`uv run pytest -q` -> `2 passed`；
  Bandit 对 `src` 扫描无发现；pip-audit 返回无已知漏洞并明确跳过本地包。
- sample Docker：`docker compose config` 通过；真实 `docker build` 成功；
  容器 `/health` 返回 `status=ok`，`/metrics` 返回 `200 text/plain`；验证后
  已删除 smoke container 和本地 smoke image tag。
- 控制台：`npm.cmd test` -> `13 passed`；`npm.cmd run build` 成功，
  Vite 7.3.6 共转换 75 modules。
- 真实 API + 浏览器 E2E：Task
  `4b85af2d-9dd9-412e-89a5-691a52fd5d5e` 完成 M4+M6 全链路，最终
  `PullRequestCreated`；local PR `provider=local`、`url=null`、commit
  `2badbf270e26a60749ce0f8b06f9373f360e936b`、10 个变更文件、8 类
  Artifact。生成代码的真实 pytest 为 `21 passed`，Review 覆盖 11 条 AC，
  Security 为 2 个 scanner、0 finding、PR 不阻断。
- 浏览器 1280×720、1024×768、375×812 均无 document 水平溢出；
  移动端 diff 仅在自身容器横向滚动；Diff/Test/Review/Security/本地 PR 五类
  证据可见，`url=null` 明确显示“本地等价 PR 记录 · 无远端链接”。稳定页面
  CDP 未产生 Vite、React 或业务异常。
- FastAPI OpenAPI 与共享 YAML 反序列化后精确一致：
  `version=0.5.0`、`paths=41`、`schemas=56`。
- 使用 Draft 2020-12 元 schema 检查共享 JSON Schema，共 `26` 份有效；
  ToolCall provider pair、Git/Repo/Sandbox/Scaffold/Test/Security schema 与
  Pydantic/registry 关键字段已加入精确一致性测试。
- 静态门禁：259 个生产 Python/TS/TSX 文件均不超过 300 行；生产代码无
  TODO/FIXME/NotImplemented/空 `pass`；558 个文本文件 UTF-8 解码通过；
  402 个本地 Markdown 链接存在；生产代码和文档敏感模式扫描 0 命中；
  `git diff --check` 通过；源 fixture 内没有嵌套 `.git`。

## 2026-07-11（Task 主会话、真实 Prompt Cache 与 Instructions v3 纠偏完成）

### 已完成

- 完成 `0.4.3` Task 级 Agent conversation 纠偏：Requirement、Architect、
  Planner 跨三个独立 `run-next` 请求加载同一个 root conversation，不再按
  Agent 角色隐式新建模型会话。
- 新增 `agent_conversations` ORM、repository、service 和
  `20260711_0005_create_agent_conversations.py` migration；PostgreSQL partial
  unique index 保证每个 Task 只有一个 root。
- 完整持久化并回放 developer/user message、assistant final answer、
  `reasoning.encrypted_content`、function/custom tool call/output、审批上下文
  和 subagent notification；`store=false` 只清理不可复用 item ID。
- AgentRun 新增 `conversation_id`、`conversation_turn`、
  `cached_input_tokens`、`provider_request_count`、`provider_requests`、
  `provider_response_id` 和 `prompt_cache_key`。总量和逐请求 usage 均来自
  供应商，`cache_hit` 只由 `cached_input_tokens > 0` 推导。
- 修复跨角色 Structured Output 缓存前缀：三个普通角色使用同一扁平
  `cloudhelm_agent_output_v1` 传输 schema，当前角色最终仍由专属 Pydantic
  model 严格校验；不再发送会破坏前缀的角色专属 schema。
- 完成 Instructions v3：Base/Role/Turn/Validation/Approval/Subagent 分层。
  Requirement、Architect、Planner Instructions 均详细覆盖输入字段权威含义、
  处理顺序、字段精度、ID/引用、工具 allowlist、审批/风险、禁止项和完成判定。
- 工具上下文采用 Responses function/custom call 与 output 形态，严格校验同一
  `call_id`；副作用仍只能经 Tool Gateway、Policy 和 Approval。
- 只有 `AgentConversationService.spawn_subagent` 可以创建 child；fresh child
  不继承父历史，full-history 只复制 system/developer/user 和 assistant
  final answer。child 完成只向父线程追加 `<subagent_notification>`。
- 设计/计划审批和拒绝会向现有 root 追加结构化 `<approval_context>`，审批
  reason 明确属于业务数据，不能覆盖 Base/Role/Tool Policy。
- 每个 Agent 步骤增加数据库 savepoint：业务产物、成功 AgentRun、
  conversation turn 与完成事件原子保存；晚期持久化失败会整体回滚，再单独
  提交失败 AgentRun。新增故障注入测试证明不会留下半成品。
- 按官方 Responses 形态修正显式缓存断点：启用时发送
  `prompt_cache_options.mode=explicit` 与 content
  `prompt_cache_breakpoint`，并随历史保留断点；当前兼容端点真实探测返回
  HTTP 502，因此默认关闭，不静默降级。
- 保持 HTTP SSE 流式传输、Codex User-Agent、originator、
  `x-client-request-id`、session/thread headers 和 child lineage headers；
  用户已明确不实现 WebSocket。
- 将 Provider contracts、usage、HTTP client、stream accumulator、prompt
  cache、request payload、local provider 和 subagent 管理按职责拆分；普通
  生产源码均不超过 300 行。
- 控制台继续按 Gemini 浅色主题重写，新增 AgentRun 卡片、Task 主会话 turn、
  成功 Agent 数、总缓存 token、待审批数、每次供应商请求 usage、response ID、
  conversation ID 和 cache key 展示。
- 项目版本提升到 `0.4.3`，Agent Runtime 提升到 `0.3.2`，控制台 package
  同步到 `0.4.3`；OpenAPI、事件 schema、README、Agent/API/Data/Workflow/
  Testing 文档和资料归档已同步。
- 新增 `informations/m4-agent-context/codex-responses-context.md`，记录 OpenAI
  官方 Prompt Caching/Reasoning/Function Calling/Streaming 资料、Codex 源码
  commit、源码审计结论、兼容端点能力探测和采用结论，不保存真实凭据或本机
  临时路径。
- 提交前关键 diff 复核发现拆分后的 `local_structured.py` 返回类型使用
  `Any` 但缺少显式 import；已补齐类型依赖，不改变运行行为。

### 进行中

- 本轮 Task conversation、Instructions、真实缓存、完整流程和控制台验收已完成。
- 下一阶段按已重写的 `PROJECT_PLAN.md` 执行 M6 本地代码实现、测试与等价
  PR 闭环。

### 阻塞与风险

- 当前兼容端点不支持官方显式 Prompt Cache breakpoint，真实请求返回 HTTP
  502；默认自动缓存已经稳定命中，因此保持配置关闭。
- Platform API 仍有 1 条 Starlette TestClient/httpx 弃用提示，不影响结果，
  M6 查阅当前迁移建议后处理。
- 上下文当前保存完整 ResponseItem；达到模型窗口前需要另立 compaction /
  truncation 设计，不能静默丢弃历史。
- Sandbox Tool 仍为本地受控 `subprocess`，Docker 资源与网络隔离属于 M6
  前置设计。

### 下一步

- 创建 `informations/m6-code-test-pr/official-references.md` 和 M6 本地开发流程
  细化设计，先确定 Sandbox/Docker 取舍。
- 创建 `examples/sample-repo-python`，实现真实 `/health`、`/metrics`、
  pytest、Dockerfile 和 demo issue。
- 扩展稳定跨角色 schema/工具定义，实现 Coder、Tester、Reviewer、Security
  Agent，继续复用同一 Task root conversation。
- 持久化 Artifact 和本地等价 PR record，控制台展示真实 diff、测试、安全、
  review 和 PR 证据。

### 涉及文件

- `PROJECT_PLAN.md`
- `PROJECT_PROGRESS.md`
- `.env.example`
- `README.md`
- `modules/agent-runtime/**`
- `modules/platform-api/**`
- `apps/control-console/**`
- `packages/shared-contracts/**`
- `docs/03-modules/**`
- `docs/04-agents/**`
- `docs/08-api/**`
- `docs/15-detailed-design/**`
- `informations/m4-agent-context/codex-responses-context.md`
- `docs/14-roadmap/03-implementation-milestone-flow.md`

### 验证

- `git branch --show-current` -> `dev`。
- Agent Runtime：`uv lock --check`；`uv run pytest -q` ->
  `25 passed, 1 skipped`。
- Tool Gateway：`uv lock --check`；`uv run pytest -q` ->
  `25 passed, 1 skipped`。
- Orchestrator：`uv lock --check`；`uv run pytest -q` -> `3 passed`。
- Platform API：执行 `alembic downgrade 20260710_0004`、`upgrade head`、
  `alembic check`，结果 `No new upgrade operations detected`；随后
  `uv run pytest -q` -> `49 passed, 1 skipped, 1 warning`。
- Control Console：`npm.cmd test` -> `7 passed`；
  `npm.cmd run build` 成功。
- FastAPI OpenAPI 与共享 YAML 反序列化后精确一致：
  `version=0.4.3`、`paths=34`、`schemas=43`。
- 使用 Draft 2020-12 元 schema 递归检查共享 JSON Schema，共 `15` 份有效。
- 真实五轮 Prompt Cache 再次通过，耗时 `187.90s`：

  ```text
  turn1 input=6511  cached=0
  turn2 input=11453 cached=5888
  turn3 input=16422 cached=11008
  turn4 input=21373 cached=16128
  turn5 input=26324 cached=21248
  ```

  五轮均为一个供应商请求、同一 conversation/key，response ID 均存在。
- 真实完整流程
  `Project -> Task -> Requirement -> Architect -> 设计审批 -> Planner -> 计划审批`
  通过，耗时 `827.34s`；两次人工审批由助手按用户要求代为批准。
- 完整流程数据库证据：

  ```text
  Requirement turn=1 requests=1 input=5363  cached=0     output=3254
  Architect   turn=2 requests=2 input=24795 cached=15872 output=31818
    request1 input=12026 cached=4864  output=15156
    request2 input=12769 cached=11008 output=16662
  Planner     turn=3 requests=1 input=30484 cached=12032 output=7084
  ```

  三个 AgentRun 的 `conversation_id` 和 `prompt_cache_key` 均唯一相同；数据库
  只有一个 root，`turn_count=3`；两次 Approval 均为 approved；共 22 个事件，
  其中 3 个 `AgentRunCompleted` 和 1 个 `AgentConversationCreated`。
- 官方显式 breakpoint 单请求能力探测：当前兼容端点返回 HTTP 502；未写入
  Key、端点地址或 prompt 正文。
- 应用内浏览器连接真实 Platform API/Vite：
  - 1280×720：`292px / 988px`，无水平溢出，3 个 AgentRun，逐请求证据数
    为 `[1, 2, 1]`。
  - 1024×768：`292px / 732px`，无水平溢出，3 个 AgentRun。
  - 窄屏实际内容宽 360：导航和主内容纵向排列，Agent card 328px、请求行
    290px，无水平溢出。
  - 展开 Architect usage 后正确展示 2 个真实请求、40%/86% 缓存比例、
    conversation/cache key/response ID。
  - 三种视口 console error/warn 均为 0；临时 API/Vite 进程已关闭。
- `git diff --check` 通过；真实 Key 和端点域名写入扫描均为 0。
- 生产源码未发现 TODO、FIXME、NotImplemented、空 `pass` 或超过 300 行文件。
- 通用 secret pattern 只命中 Tool Gateway 测试夹具中的脱敏样例。
- 补齐 `Any` import 后再次执行 Agent Runtime `uv lock --check` 和
  `uv run pytest -q`，结果保持 `25 passed, 1 skipped`；最终轻量门禁再次确认
  OpenAPI 精确一致、15 份 Draft 2020-12 Schema 有效且 `git diff --check`
  通过。

## 2026-07-11（M1-M5 二次审计修复完成与 v0.4.2）

### 已完成

- 完成数据/API 状态修复：Requirement、TechnicalDesign、DevelopmentPlan 真实递增版本；历史需求/设计评审返回稳定 stale 错误；新版本级联失效旧下游产物与审批。
- 严格校验分页 cursor，列表默认最新记录优先，Timeline 小页包含最新事件且页内保持时间正序；未处理异常统一返回 `internal_error`、`trace_id` 和 `X-Trace-Id`。
- 新增 `20260710_0004_harden_m1_m5.py`：持久化 `tool_calls.audit_json` 并同步数据库列注释。
- Tool Gateway 增加平台工作区 allowlist，空配置默认拒绝；Agent 调用同时要求 AgentRun 与 Task 为 `running`。
- ToolCall 参数、结果、stdout/stderr 落库前脱敏；文件正文只保存长度和 SHA-256；成功、审批和失败路径均生成一致的服务端审计主体。
- 内部 ToolCall 记录接口拒绝调用方伪造 `audit_json`，并忽略调用方提供的参数摘要，统一从脱敏参数键生成公开摘要；Authorization、API Key、Cookie 等 header 字段也会脱敏。
- Task 取消会级联关闭 active AgentRun、ToolCall 和 pending Approval，并写入取消/过期事件。
- 控制台接入最新请求门禁，快速切换 Project 时立即清空旧 Task；历史 Requirement/TechnicalDesign 评审按钮按最新版和状态禁用。
- 控制台 SSE 客户端实现固定退避重连、event id 去重和旧连接竞态隔离；浏览器回归发现其最初只刷新详情、未刷新左侧任务列表，修复后新事件会同步刷新 Task Detail 与 Task Board。
- `openai_compatible` provider 保持 Responses API `reasoning.effort=max`，增加可配置 timeout、最大尝试次数和指数退避；瞬时请求/无效结构化响应耗尽后把 Task 暂停在原阶段。
- 项目版本提升到 `0.4.2`；Agent Runtime 包版本提升到 `0.3.1`。
- 同步 FastAPI OpenAPI、15 个共享 JSON Schema、模块/API/安全/控制台文档和环境变量；`PROJECT_PLAN.md` 已重写为以 `v0.4.2` 为基线的 M6 详细计划。

### 进行中

- M1-M5 二次审计、修复、回归和文档同步已完成；下一阶段按 `PROJECT_PLAN.md` 执行 M6 本地代码实现、测试与等价 PR 闭环。

### 阻塞与风险

- 仓库没有真实外部模型 API Key，本次继续用隔离 HTTP 契约测试验证 `gpt-5.6-sol`、`reasoning.effort=max` 和重试行为，不执行外部计费请求。
- Windows 当前账户可能无法创建新 symlink；Tool Gateway 保留该平台能力测试跳过，同时覆盖允许目录、越界路径和既有 symlink。
- Sandbox Tool 仍是本地 `subprocess`，Docker、资源 quota 和网络隔离仍属于 M6 前置增强。
- Platform API 测试仍有 1 条 Starlette TestClient/httpx 弃用提示，不影响当前结果，M6 查阅当前官方迁移建议后处理。

### 下一步

- 创建 `informations/m6-code-test-pr/official-references.md`，完成 Sandbox/Docker 取舍设计。
- 准备 `examples/sample-repo-python`，实现真实 `/health`、`/metrics`、pytest 和 demo issue。
- 按 M6 计划实现 Coder、Tester、Reviewer、Security Agent、Artifact/PR record 和浅色控制台展示。

### 涉及文件

- `modules/platform-api/**`
- `modules/tool-gateway/**`
- `modules/agent-runtime/**`
- `apps/control-console/**`
- `packages/shared-contracts/**`
- `docs/**`
- `.env.example`、`README.md`、`PROJECT_PLAN.md`

### 验证

- Git 预检确认当前分支为 `dev`；`git diff --check` 通过，未修改 `main`。
- Tool Gateway：`uv lock --check`；`uv run pytest -q` -> `25 passed, 1 skipped`。跳过项为 Windows 新建 symlink 权限。
- Agent Runtime：`uv lock --check`；`uv run pytest -q` -> `11 passed`，覆盖 Responses API、`reasoning.effort=max`、瞬时请求重试、无效结构重试和不可重试 401。
- Orchestrator：`uv lock --check`；`uv run pytest -q` -> `3 passed`。
- Platform API：真实 PostgreSQL 执行 `alembic downgrade 20260708_0003`、`upgrade head`、`alembic check`；最终 `44 passed, 1 warning`。
- 回归过程中曾因新增安全摘要逻辑漏导入 `summarize_arguments` 出现 `2 failed, 42 passed`；补导入后重新执行并恢复为 `44 passed`，完成“发现 -> 修复 -> 回归”闭环。
- Control Console：`npm.cmd test` -> `7 passed`；`npm.cmd run build` 成功。
- FastAPI OpenAPI 与共享 YAML 反序列化后精确相等：`version=0.4.2`，`paths=34`。
- 递归解析 `packages/shared-contracts/schemas/**/*.json` 共 15 个，并验证 Requirement、Architect、Planner、ToolCallRequest、ToolCallResult 5 份代表性输出。
- 共享契约验证脚本首次因 Requirement 示例缺少至少 1 条 `constraints` 而失败；修正测试夹具后重新执行，15 个 Schema 解析和 5 份代表性输出验证全部通过。
- 应用内浏览器连接真实 Platform API 验证 1280×720：body 白色、侧栏 `rgb(240, 244, 249)`、`scrollWidth=1280`；1024×768：`292px / 732px`、无水平溢出；375×812：纵向布局、document `scrollWidth=clientWidth=360`。
- 浏览器验证快速切换 Alpha/Beta Project 后只显示当前项目 Task；历史 Requirement/Design 按钮禁用，当前 draft Design 可操作。
- 浏览器从外部 API 执行 pause/resume，不手工刷新即可看到 `TaskPaused`/`TaskResumed`，Task Detail 和左侧 Task Board 同步更新；全新页面 console 无 error/warn。
- 浏览器与临时 Platform API/Vite 服务已关闭；本地 PostgreSQL 容器保持原有运行状态。
- 静态扫描未发现生产代码 TODO、FIXME、NotImplemented 或空 `pass`；超过 300 行的只有 Agent Runtime 测试集合，生产源码无超限文件。凭据模式只命中用于脱敏验证的测试夹具。
- 提交前再次执行全部模块测试、Alembic `upgrade head/check`、控制台测试与生产构建、OpenAPI 精确比较、15 个 Schema 解析和 `git diff --check`，结果保持通过。
- 本轮按可验证小步整理提交：`ed75cfe` 为后端/Agent/Tool Gateway/共享契约，`43ace9e` 为控制台竞态与 SSE；两项均已推送 `origin/dev`，本进度与 M6 计划作为第三步文档提交同步。

## 2026-07-10（M1-M5 二次审计启动）

### 已完成

- 按用户要求重新从 `AGENTS.md`、M1-M5 总排期、模块契约、Agent/Tool 契约、数据设计、事件设计和安全边界建立审计基线，不沿用上一轮“已完成”结论。
- 重跑当前基线：Tool Gateway `20 passed, 1 skipped`、Agent Runtime `8 passed`、Orchestrator `3 passed`、Platform API `32 passed, 1 warning`、控制台 `4 passed` 且生产构建成功。
- 使用 `alembic check` 发现 ORM metadata 与已应用迁移存在注释差异，证明现有测试门禁仍不能覆盖全部 schema 一致性。
- 发现需要修复的实现问题：资源版本未递增、旧版本仍可评审、分页漏最新数据、未处理异常缺统一错误、Tool Gateway 工作区根目录由调用方任意指定、ToolCall 审计未持久化和脱敏、控制台 Project/Task 请求竞态及 SSE 无真正重连。
- 重写 `PROJECT_PLAN.md` 为本次 M1-M5 二次审计与修复的详细执行计划；本阶段不进入 M6。
- 已完成第一批数据/API 修复：Requirement、TechnicalDesign、DevelopmentPlan 真实递增版本；旧需求/设计评审返回稳定 stale 错误；新版本级联失效旧下游产物；手工审批推进到 Designing/Planning。
- 分页 cursor 改为严格非负十进制校验，列表优先返回最新记录，Timeline 小页仍包含最新事件并保持页内时间正序。
- 未处理异常现在返回统一 `internal_error`、JSON body、`trace_id` 和 `X-Trace-Id`，不泄露内部异常文本。

### 进行中

- 正在修复 Tool Gateway 工作区 allowlist、审计持久化、参数/结果脱敏和共享 Tool schema。

### 阻塞与风险

- Windows 当前账户仍可能无法创建 symlink；该项使用跳过测试并以既有 symlink、路径越界和允许根目录测试补充。
- M5 Sandbox 仍是本地 subprocess，不具备 Docker 资源和网络隔离；本次只收紧允许工作区、命令与审计边界。

### 下一步

- 实现 Requirement、TechnicalDesign、DevelopmentPlan 版本递增和最新版评审约束。
- 修复分页 cursor、统一 500 错误和最新记录排序。
- 新增 ToolCall audit migration、工作区 allowlist 与敏感结果脱敏。

### 涉及文件

- `PROJECT_PLAN.md`
- `PROJECT_PROGRESS.md`
- `modules/platform-api/**`
- `modules/tool-gateway/**`
- `apps/control-console/**`
- `packages/shared-contracts/**`

### 验证

- 已确认当前分支为 `dev`，工作区在审计开始前干净。
- 已执行全部现有自动化测试和前端构建。
- 已执行 `uv run alembic check` 并记录真实失败差异，未把该项伪装为通过。
- 第一批修复后 `modules/platform-api` 执行 `uv run pytest -q`，结果 `37 passed, 1 warning`。

## 2026-07-10（M1-M5 补全收尾与 v0.4.1）

### 已完成

- 完成 M1-M5 补全收尾，不进入 M6：修复需求、技术设计和开发计划返工时的下游产物与待审批记录级联失效，拒绝已过期审批继续作用于新产物。
- 统一开发计划审批语义：批准后写入 `approved` 并恢复可运行状态，拒绝后写入 `changes_requested` 并允许 Planner 重新生成；暂停期间完成审批后，恢复任务不会残留 `waiting_approval`。
- 收紧编排和 Tool Gateway 边界：暂停或终态任务不能继续推进 Agent；工具调用要求 `agent_run_id` 与 `agent_type` 成对出现，Platform API 只接受当前任务中处于 `running` 的 AgentRun。
- 收紧 Git Tool 提交范围：拒绝仓库根目录、目录 pathspec 和不存在且未跟踪的文件，保留显式文件清单、Git index 隔离、幂等抢占、审批拦截、审计和单实例限流。
- 修正共享 Task Event JSON Schema，使字段和事件枚举与真实 API、SSE 事件一致；前端同步监听 M2-M5 AgentRun、审批、开发计划和 ToolCall 事件。
- 完成 Gemini 式浅色控制台收尾：中文任务分组与操作文案、终态按钮禁用、编排按钮状态、ARIA 语义、响应式样式拆分，以及需求/设计/审批决策后详情和左侧任务列表同步刷新。
- `openai_compatible` provider 默认改用 Responses API，支持 `reasoning.effort=max`、`max_output_tokens`、`store=false` 和 JSON Schema 输出；用户配置的 `gpt-5.6-sol` 模型字符串原样透传，同时保留 `chat_completions` 兼容模式。
- 为外部模型网络失败和无效响应补充稳定错误码 `agent_provider_request_failed`、`agent_provider_response_invalid`，所有结构化结果继续由 Pydantic 二次校验。
- 项目版本提升到 `0.4.1`，同步 `.env.example`、README、OpenAPI、模块/API/工作流/控制台文档和 M6 前置基线。

### 进行中

- M1-M5 补全、回归和文档同步已完成；下一阶段仍为 `PROJECT_PLAN.md` 中的 M6“本地代码实现、测试与 PR 闭环”，本次没有实现 M6 sample repo、Coder/Tester/Reviewer/Security 或 PR record。

### 阻塞与风险

- OpenAI 公共模型目录已确认 `gpt-5.6-sol` 与 `max` reasoning effort；仓库没有真实 API Base 和密钥，因此本次通过请求契约单元测试验证，没有执行外部端点实调。
- Tool Gateway 限流仍是单实例内存滑动窗口，符合 M5 演示边界；多实例一致性后续需要共享存储。
- Windows 当前账户缺少 symlink 创建权限，Tool Gateway 路径安全测试跳过 1 项；普通目录、越界和既有 symlink 检查均已通过。
- Platform API 测试仍有 1 条 Starlette TestClient/httpx 弃用提示，不影响当前用例结果。

### 下一步

- 按 `PROJECT_PLAN.md` 先归档 M6 官方资料并评估 Docker sandbox，再创建受控 `examples/sample-repo-python`。
- 实现 Coder、Tester、Reviewer、Security Agent 的结构化契约和真实 Tool Gateway 调用闭环。
- 持久化真实 diff、测试、安全、review artifact 和本地等价 PR record，并沿用当前浅色控制台展示。

### 涉及文件

- `modules/agent-runtime/src/cloudhelm_agent_runtime/providers/**`
- `modules/orchestrator/**`
- `modules/platform-api/src/cloudhelm_platform_api/{api,repositories,schemas,services}/**`
- `modules/tool-gateway/src/cloudhelm_tool_gateway/**`
- `apps/control-console/**`
- `packages/shared-contracts/openapi/cloudhelm.openapi.yaml`
- `packages/shared-contracts/schemas/events/task-event.schema.json`
- `docs/03-modules/**`、`docs/04-agents/**`、`docs/05-tool-layer/**`
- `docs/08-api/**`、`docs/09-control-console/**`、`docs/15-detailed-design/**`
- `.env.example`、`README.md`、`PROJECT_PLAN.md`

### 验证

- 工作前确认当前分支为 `dev`，并保留既有未提交改动继续完成，不在 `main` 修改。
- `modules/tool-gateway`：`uv run pytest -q`，结果 `20 passed, 1 skipped`；跳过项为 Windows symlink 权限。
- `modules/agent-runtime`：`uv run pytest -q`，结果 `8 passed`，覆盖 Responses API、`reasoning.effort=max`、模型透传、Chat Completions fallback 和坏响应。
- `modules/orchestrator`：`uv run pytest -q`，结果 `3 passed`。
- `modules/platform-api`：真实 PostgreSQL 执行 `uv run alembic upgrade head` 和 `uv run pytest -q`，结果 `32 passed, 1 warning`。
- `apps/control-console`：`npm.cmd test` 结果 `4 passed`，覆盖任务操作/编排按钮状态策略和决策成功后的列表刷新边界；`npm.cmd run build` 成功，TypeScript 和 Vite 生产构建通过。
- 递归解析 `packages/shared-contracts/schemas/**/*.json`，共 `15` 个 JSON Schema 全部有效。
- FastAPI `create_app().openapi()` 与 `packages/shared-contracts/openapi/cloudhelm.openapi.yaml` 反序列化后精确相等，版本为 `0.4.1`，共 `34` 个 paths。
- 应用内浏览器连接真实 Platform API 验证 1280×720、1024×768、375×812：body 为白色、侧栏为 `rgb(240, 244, 249)`，三种宽度均无水平溢出，console 无 error/warn。
- 浏览器真实执行“启动编排 -> Requirement Agent -> Request Changes”，任务详情和左侧任务列表即时同步为 `running / RequirementClarifying`，验证最新状态刷新修复。
- 浏览器回归结束后已关闭测试标签页，并停止临时 Vite、Platform API 和 PostgreSQL 服务。
- `git diff --check` 通过；生产源码未发现 TODO、FIXME、NotImplemented、空 `pass` 或超过 300 行文件。

## 2026-07-10（控制台重写为 Gemini 式浅色布局）

### 已完成

- 按用户最新要求废弃上一版 Codex 深色视觉，不使用前端设计 Skill，基于网页版 Gemini 当前浅色界面的信息架构重新设计控制台。
- 将原“顶部状态栏 + 项目栏 + 任务栏 + 详情区”重排为双栏结构：左侧蓝灰导航整合品牌、项目空间、创建入口和最近任务，右侧白色主区只承载上下文栏和任务详情阅读流。
- 全量重写 `styles.css` 与 `console.css`：采用纯白页面、`#f0f4f9` 侧栏、浅蓝选择态、柔和圆角容器、弱边框和宽松留白，移除深色 token、终端式全局背景和密集三栏排版。
- 重写项目、任务和空状态排版；保留真实 API、状态操作、编排、评审、Timeline、ToolCall 和 Approval 功能，不添加 Gemini 品牌资产、聊天功能或静态假数据。
- 同步控制台页面结构文档、模块 README 和 M6 计划中的 UI 基线。

### 进行中

- 控制台浅色主题重写已完成；项目下一阶段仍为 M6 本地代码实现、测试与 PR 闭环。

### 阻塞与风险

- 当前只实现浅色主题，不提供深浅主题切换；如后续需要主题切换，应在共享 token 层扩展，不能复制两套组件样式。
- 375 像素宽度使用纵向“导航 -> 任务 -> 详情”布局，适合检查和审批；复杂 diff 的移动端专用交互仍属于 M6 Diff Viewer 实现范围。

### 下一步

- M6 新增 Diff Viewer、测试报告、安全报告和 PR record 面板时，继续使用当前浅色布局和主内容宽度。
- 为新增复杂交互补充键盘导航、空状态、加载态和移动端检查。

### 验证

- `apps/control-console` 执行 `npm.cmd run build`，TypeScript 与 Vite 生产构建成功。
- 应用内浏览器连接真实 Platform API 验证 1440x900：布局列为 `292px / 1148px`，body 为白色、侧栏为 `rgb(240, 244, 249)`，无告警和 console error/warn。
- 验证 1024x768：布局列为 `292px / 732px`，无水平溢出。
- 验证 375x812：自动切换纵向布局，`scrollWidth=375`，无水平溢出和 console error/warn。
- 截图验证完成后已关闭浏览器标签页、Platform API、Vite 服务和 PostgreSQL 容器。

## 2026-07-10（M1-M5 代码质量与进度一致性审计）

### 已完成

- 按 `AGENTS.md`、MVP 裁剪线、模块契约、API 契约、状态事件文档和总排期逐项复核 M1-M5 的真实生产代码，不以测试通过代替源码审查。
- 确认总排期已记录 M5 完成，但本文件此前缺少 M5 完成条目；本条补齐真实实现与验证证据，不新增或伪造里程碑。
- 重写 Tool Gateway 权限和执行边界：工具声明增加 Agent 白名单与系统调用许可；副作用工具必须绑定当前任务 AgentRun；补充跨任务归属校验、安全父目录创建、进程内滑动窗口限流和 Git index 隔离。
- 重写 Platform API Tool Gateway 幂等流程：先以独立短事务创建 `pending` ToolCall 并利用数据库唯一索引抢占幂等键，抢占成功后才执行文件、Sandbox 或 Git 副作用，再在第二事务写入结果、审批和终态事件。
- 修复任务暂停/恢复语义：暂停保留 `current_phase` 并记录原状态，恢复时还原 `created`、`running` 或 `waiting_approval`，不再统一恢复为 `running`。
- 修复 Requirement/TechnicalDesign 评审状态迁移和任务回退；设计审批绑定当前最新版设计的 AgentRun，旧审批不可批准新设计；审批、ToolCall、AgentRun 关联均校验任务归属。
- 将 560 行编排服务拆分为 provider factory、AgentRun lifecycle、审批协调、响应组装和步骤执行器；主服务只保留状态机决策、阶段迁移和事务协调，生产源码无超过 300 行文件。
- 修复控制台任务切换请求竞态和 SSE 历史事件刷新风暴；审批列表改为后端 `task_id` 过滤。
- 整体重写控制台为紧凑 Codex 风格：移除 Hero 和宣传页卡片布局，改为顶部状态栏、项目栏、任务栏、详情工作区；任务状态操作按合法状态禁用，ToolCall/Timeline 使用低饱和等宽日志样式。
- 同步共享 OpenAPI、前端 ToolDeclaration 类型、Task/ToolCall/Approval API 和工作流状态事件文档。

### 进行中

- M1-M5 已完成代码质量审计并达到当前文档边界；下一阶段仍为 M6“本地代码实现、测试与 PR 闭环”。

### 阻塞与风险

- Tool Gateway 限流仍为单实例内存滑动窗口；符合 M5 单实例演示边界，多实例一致性需后续迁移到 Redis 等共享存储。
- Windows 环境因当前账户缺少 symlink 创建权限，相关路径安全测试跳过 1 项；普通目录、越界与既有 symlink 校验测试均通过。
- Platform API 测试仍有 Starlette TestClient/httpx 弃用提示，不影响当前 26 项测试结果，后续依赖升级处理。
- M5 Sandbox Tool 仍是受控本地 subprocess；是否升级为 Docker sandbox 已列入 M6 前置评估，不能将其描述为容器隔离。

### 下一步

- 按 `PROJECT_PLAN.md` 执行 M6：先归档官方资料并评估 Docker sandbox，再准备独立 sample repo。
- 实现 Coder、Tester、Reviewer、Security Agent 的真实结构化输出与 Tool Gateway 调用闭环。
- 持久化真实 diff、测试、安全、review artifact 和本地 PR record，并在控制台展示。

### 涉及文件

- `modules/tool-gateway/src/cloudhelm_tool_gateway/**`
- `modules/platform-api/src/cloudhelm_platform_api/{api,repositories,schemas,services}/**`
- `apps/control-console/src/**`
- `packages/shared-contracts/openapi/cloudhelm.openapi.yaml`
- `docs/08-api/**`
- `docs/15-detailed-design/{03-api-detail,05-workflow-state-events}.md`
- `PROJECT_PROGRESS.md`
- `PROJECT_PLAN.md`

### 验证

- `modules/tool-gateway`：`uv run pytest -q`，结果 `18 passed, 1 skipped`；跳过项为 Windows symlink 权限。
- `modules/agent-runtime`：`uv run pytest -q`，结果 `5 passed`。
- `modules/orchestrator`：`uv run pytest -q`，结果 `3 passed`。
- `modules/platform-api`：真实 PostgreSQL 执行 `uv run alembic upgrade head` 和 `uv run pytest -q`，结果 `26 passed, 1 warning`。
- `apps/control-console`：`npm.cmd run build` 成功，TypeScript 和 Vite 生产构建通过。
- 共享 OpenAPI 与 FastAPI `create_app().openapi()` 比对通过：Approval 参数均为 `cursor/limit/status/task_id`，ToolDeclaration 均要求 `allowed_agent_types/allow_system_call`。
- 应用内浏览器连接真实 Platform API 验证 1440×900、1024×768、375×812：三种视口 `scrollWidth` 均等于视口宽度，无水平溢出，无 console error/warn；验证后已关闭浏览器标签页和临时前后端服务。
- `git diff --check` 通过；生产源码未发现 TODO、FIXME、NotImplemented、空 `pass` 或超过 300 行文件。

## 2026-07-08（M4 完成：Agent 编排与规格化闭环）

### 已完成

- 按 `PROJECT_PLAN.md` 完成 M4：Agent 编排与规格化闭环。
- 创建 `informations/m4-agent-orchestration/official-references.md`，归档 LangGraph、Pydantic、OpenAI structured outputs、FastAPI 后台任务和 pytest 资料及采用结论。
- 新增 `modules/agent-runtime`，实现 Requirement / Architect / Planner Agent、Pydantic 结构化输出 schema、`local_structured` provider 和 `openai_compatible` provider 配置错误路径。
- 新增 `modules/orchestrator`，实现 M4 显式状态机：`Created -> RequirementClarifying -> Designing -> WaitingDesignApproval / Planning`。
- 扩展 `modules/platform-api` 到 `0.3.0`，新增 Orchestration API、DevelopmentPlan API、`development_plans` 表、AgentRun 结构化输出字段和 M4 事务副作用事件。
- 新增迁移 `20260708_0002_create_m4_agent_tables.py`，新增 `development_plans` 和 AgentRun 错误/结构化输出字段。
- 新增共享 Agent 输出 JSON Schema：`packages/shared-contracts/schemas/agents/*.schema.json`。
- 重新生成 `packages/shared-contracts/openapi/cloudhelm.openapi.yaml`，版本为 `0.3.0`，覆盖 M4 新接口。
- 扩展控制台 Task Detail，新增 M4 编排区和 Development Plan 面板，调用真实 `start` / `run-next` / `development-plans` API。
- 按用户要求调整控制台 UI 参考 Codex 桌面端风格：低饱和、面板式布局、紧凑按钮、清晰边框，移除霓虹和玻璃拟态。
- 同步 README、`.env.example`、模块 README、Agent/API/控制台/详细设计文档和总排期。
- 将 `docs/14-roadmap/03-implementation-milestone-flow.md` 的 M4 任务全部打钩。
- 重写 `PROJECT_PLAN.md`，生成 M5“Tool Gateway 与本地工具层”的详细执行计划。

### 进行中

- M4 已完成并通过后端、Agent Runtime、Orchestrator、前端构建和浏览器主流程验证；下一阶段从 `dev` 执行 M5 Tool Gateway 与本地工具层。

### 阻塞与风险

- M4 默认使用 `local_structured` provider，以真实输入规则化生成结构化草案；未配置外部 LLM 时不阻塞 M4。若切换 `openai_compatible` 但缺少 `CLOUDHELM_LLM_API_BASE`、`CLOUDHELM_LLM_MODEL` 或 `CLOUDHELM_LLM_API_KEY`，会写入失败 AgentRun 和错误事件。
- M4 不执行 Coder/Tester/Reviewer、Tool Gateway、Git PR、远端部署或监控告警；这些能力进入 M5-M8。
- M2 SSE 仍为事件回放 + heartbeat，控制台继续通过操作后刷新详情和 Timeline 保证可见性。
- Platform API 测试仍有 Starlette/httpx 弃用提示，不影响测试结果，后续依赖升级时处理。

### 下一步

- 按新的 `PROJECT_PLAN.md` 执行 M5：创建 `modules/tool-gateway`，实现工具注册、参数校验、风险等级、审批拦截、审计和本地 Repo/Sandbox/Git 工具。
- 为 Tool Gateway 建立共享 tool schema、Platform API 调用入口、ToolCall 事件副作用和控制台真实 ToolCall 展示。
- 完成路径越界、敏感文件、命令超时、审批拦截和事务一致性的黑盒/白盒测试。

### 涉及文件

- `PROJECT_PLAN.md`
- `PROJECT_PROGRESS.md`
- `README.md`
- `.env.example`
- `.gitignore`
- `apps/control-console/**`
- `modules/agent-runtime/**`
- `modules/orchestrator/**`
- `modules/platform-api/**`
- `packages/shared-contracts/openapi/cloudhelm.openapi.yaml`
- `packages/shared-contracts/schemas/agents/**`
- `informations/m4-agent-orchestration/official-references.md`
- `docs/03-modules/modules/{agent-runtime,orchestrator,platform-api}.md`
- `docs/04-agents/**`
- `docs/08-api/**`
- `docs/09-control-console/**`
- `docs/14-roadmap/03-implementation-milestone-flow.md`
- `docs/15-detailed-design/**`

### 验证

- 已执行 `git branch --show-current`，确认当前分支为 `dev`。
- 已执行 `git status --short`，确认开始前工作区干净。
- 已阅读 M4 计划要求的 Agent、Tool Gateway、API、控制台、MVP、模块契约、数据和工作流文档；`docs/05-tool-layer/00-tool-gateway-overview.md` 在仓库中对应为 `docs/05-tool-layer/00-tool-gateway.md`。
- 已执行 `cd modules/agent-runtime; uv run pytest`，结果：`5 passed`。
- 已执行 `cd modules/orchestrator; uv run pytest`，结果：`3 passed`。
- 已执行 `cd modules/platform-api; $env:CLOUDHELM_DATABASE_URL='postgresql+psycopg://cloudhelm:cloudhelm_dev@127.0.0.1:15432/cloudhelm'; uv run alembic upgrade head; uv run pytest`，结果：`15 passed, 1 warning`。
- 已执行 `cd apps/control-console; npm.cmd run build`，结果：TypeScript 编译和 Vite build 成功。
- 已启动本地 Platform API 与 Vite dev server，使用 Playwright 浏览器执行手工 E2E：创建项目 -> 创建任务 -> 启动编排 -> 推进 Requirement -> 推进 Architect -> 审批 Design -> 恢复 Planning -> 推进 Planner -> 展示 Development Plan `STEP-001`。
- 浏览器验证最终状态：无 console error/warn，截图保存到本地忽略目录 `output/m4-codex-style-browser.png`。
- 已用 `app.openapi()` 重新生成 OpenAPI，确认版本为 `0.3.0` 且包含 32 个 paths。

## 2026-07-08（M3 完成：控制台任务主流程）

### 已完成

- 按 `PROJECT_PLAN.md` 完成 M3：控制台任务主流程。
- 新增 `informations/m3-control-console/official-references.md`，归档 React、TypeScript、Vite、EventSource、Vitest / Testing Library 资料和采用结论。
- 重构 `apps/control-console`，从单一健康检查页面升级为 Project Sidebar + Task Board + Task Detail 的主流程控制台。
- 将控制台样式拆分为 `styles.css` 和 `console.css`，避免单个 CSS 文件超过普通源码体量建议。
- 新增前端统一 API client：集中处理 `VITE_CLOUDHELM_API_BASE_URL`、查询参数、JSON 请求体、`code/message/detail/trace_id` 错误结构和 `EventSource` 事件流。
- 新增前端共享类型：Project、Task、RequirementSpec、TechnicalDesign、AgentRun、ToolCall、ApprovalRequest、EventLog、分页和错误结构。
- 实现 Project Sidebar，调用真实 `GET /api/projects` 和 `POST /api/projects`，覆盖加载态、空状态、错误态和创建刷新。
- 实现 Task Board 和需求输入表单，调用真实 `GET /api/tasks?project_id=...`、`POST /api/tasks`、`pause`、`resume`、`cancel`。
- 实现 Task Detail，展示真实任务详情、Requirement Spec、Acceptance Criteria、Technical Design、Agent Timeline、Event Log、Tool Calls 和 Approval。
- 实现 Requirement / Technical Design 基础评审交互，调用真实 approve / request-changes API。
- 实现 Approval Panel 基础交互，调用真实 approve / reject API，并展示操作结果或 trace_id 错误。
- 接入 M2 SSE 端点；因 M2 只回放已有事件和 heartbeat，控制台明确标注为轮询/重连式边界，并在任务操作后刷新详情与 Timeline。
- 修复浏览器验证中发现的 Task Board 操作后 Task Detail / Timeline 不刷新的问题，新增 `refreshKey` 触发详情回读。
- 将项目版本同步到 `0.2.1`，更新 README、`.env.example`、控制台 package、Platform API 默认版本和 OpenAPI 版本。
- 更新 `docs/09-control-console/`，记录 M3 页面结构和关键交互落地状态。
- 更新 `docs/14-roadmap/03-implementation-milestone-flow.md`，将 M3 所有任务打钩，并把当前下一步改为 M4。
- 重写 `PROJECT_PLAN.md`，生成 M4“Agent 编排与规格化闭环”的详细执行计划。

### 进行中

- M3 已完成并通过构建、后端测试和浏览器主流程验证；下一阶段从 `dev` 执行 M4 Agent 编排与规格化闭环。

### 阻塞与风险

- M2 SSE 仍只回放已有事件并追加 heartbeat，M3 已用刷新/重连方式处理；生产级持续推送留到后续事件总线阶段。
- M3 未新增前端自动化测试依赖，采用 TypeScript/Vite 构建 + 浏览器手工 E2E 验证；后续如前端逻辑继续增长，应补 Vitest / Testing Library 或 Playwright 自动化。
- 浏览器插件的 `domSnapshot()` 在当前环境报错，已改用同一浏览器插件内的 Playwright evaluate/locator/screenshot 验证；不影响被测应用本身。
- M3 不实现 Agent 自动生成 Requirement / Design，不执行 Tool Gateway、Git PR、远端部署或监控告警。

### 下一步

- 按新的 `PROJECT_PLAN.md` 执行 M4：创建 M4 资料归档，设计 Agent 输出 schema、Orchestrator 状态机和 Development Plan 数据结构。
- 实现 Requirement / Architect / Planner Agent 的结构化输出校验和真实持久化路径。
- 为控制台增加“启动/推进编排”入口，并展示 Development Plan。

### 涉及文件

- `PROJECT_PLAN.md`
- `PROJECT_PROGRESS.md`
- `README.md`
- `.env.example`
- `apps/control-console/**`
- `informations/m3-control-console/official-references.md`
- `modules/platform-api/pyproject.toml`
- `modules/platform-api/uv.lock`
- `modules/platform-api/src/cloudhelm_platform_api/core/config.py`
- `packages/shared-contracts/openapi/cloudhelm.openapi.yaml`
- `docs/09-control-console/00-page-structure.md`
- `docs/09-control-console/01-key-interactions.md`
- `docs/14-roadmap/03-implementation-milestone-flow.md`

### 验证

- 已执行 `git branch --show-current`，确认当前分支为 `dev`。
- 已执行 `git status --short`，确认开始前工作区干净。
- 已阅读 M3 计划要求的控制台、API、MVP、工作流和 OpenAPI 相关文档。
- 已执行 `cd modules/platform-api; $env:CLOUDHELM_DATABASE_URL='postgresql+psycopg://cloudhelm:cloudhelm_dev@127.0.0.1:15432/cloudhelm'; uv run alembic upgrade head; uv run pytest`，结果：`11 passed, 1 warning`。
- 已执行 `cd apps/control-console; npm.cmd run build`，结果：TypeScript 编译和 Vite build 成功。
- 已启动本地 Platform API 与 Vite dev server，使用浏览器执行手工 E2E：创建项目 -> 创建任务 -> Pause -> Resume -> Cancel -> Task Detail / Timeline 展示 `TaskCreated`、`TaskPaused`、`TaskResumed`、`TaskCancelled`。
- 浏览器验证最终状态：页面无 Vite/framework error overlay，console error/warn 为空，移动宽度首屏包含标题、Project Sidebar 和 Task Board。
- 已用 `yaml.safe_load` 验证 `packages/shared-contracts/openapi/cloudhelm.openapi.yaml`，确认版本为 `0.2.1` 且包含 `/api/tasks`。
- 已执行 `git diff --cached --check`，发现并修复资料归档尾随空格后通过。
- 已在 `dev` 提交 `6631383`：`feat: 完成 M3 控制台任务主流程`。
- 已执行 `git push origin dev`，远端 `dev` 更新到 `6631383`。

## 2026-07-08（M2 完成：数据模型、API 与事件底座）

### 已完成

- 按 `PROJECT_PLAN.md` 完成 M2：数据模型、API 与事件底座。
- 新增 `infra/docker-compose.dev.yml`，提供本地 PostgreSQL 开发服务；Redis 仅通过 optional profile 预留，M2 生产代码路径未接入。
- 在 `modules/platform-api` 中接入 SQLAlchemy 2.x、Alembic、`psycopg[binary]`，版本同步为 `0.2.0`。
- 新增数据库分层：`db`、`models`、`repositories`、`services`、`schemas`、`api`。
- 新增 Alembic 迁移 `20260708_0001_create_core_m2_tables.py`，创建 `projects`、`tasks`、`requirement_specs`、`technical_designs`、`agent_runs`、`tool_calls`、`approval_requests`、`event_logs`。
- 实现 Project API、Task API、Requirement / Design API、AgentRun API、ToolCall API、Approval API、Event Timeline / SSE API。
- 写操作由 service 层在同一事务内写业务表和 `event_logs`；Task 创建、暂停、恢复、取消均写入真实事件。
- 实现统一错误结构 `code/message/detail/trace_id` 和 offset cursor 分页响应。
- 扩展测试：新增数据库迁移、Project、Task、Requirement / Design、AgentRun / ToolCall / Approval、Timeline / SSE 覆盖，共 11 个后端测试。
- 同步 `packages/shared-contracts/openapi/cloudhelm.openapi.yaml`、事件 schema、工具风险等级 schema、`docs/08-api/`、`docs/15-detailed-design/`、数据表文档、README 和本地开发命令。
- 创建 `informations/m2-data-api/official-references.md`，归档 FastAPI、SQLAlchemy、Alembic、PostgreSQL、Pydantic、pytest 和 StreamingResponse 官方资料。
- 更新 `docs/14-roadmap/03-implementation-milestone-flow.md`，将 M2 任务全部打钩，并把当前下一步改为 M3。
- 重写 `PROJECT_PLAN.md`，生成 M3“控制台任务主流程”的详细执行计划。

### 进行中

- M2 已完成并通过验证；下一阶段从 `dev` 执行 M3 控制台任务主流程。

### 阻塞与风险

- FastAPI TestClient 仍触发 Starlette 关于 `httpx` 的弃用提示；当前不影响测试结果，后续可在依赖升级或测试客户端调整时处理。
- M2 SSE 端点基于真实 `event_logs` 输出当前事件和 heartbeat，不维护长连接实时推送；该边界已写入文档，M3 控制台可先采用轮询或重连刷新。
- AgentRun、ToolCall、Approval 的创建接口仅用于内部联调和真实记录，不代表 Agent 或 Tool Gateway 已经自动执行。

### 下一步

- 按新的 `PROJECT_PLAN.md` 执行 M3：实现 Project Sidebar、Task Board、Task Detail、需求输入表单、Timeline、ToolCall 和 Approval 基础交互。
- 创建 `informations/m3-control-console/official-references.md`，归档 React、TypeScript、Vite、SSE 和前端测试资料。
- 前端必须调用真实 M2 API，不得使用静态假任务或假事件。

### 涉及文件

- `PROJECT_PLAN.md`
- `PROJECT_PROGRESS.md`
- `README.md`
- `.env.example`
- `apps/control-console/README.md`
- `apps/control-console/src/App.tsx`
- `infra/docker-compose.dev.yml`
- `informations/m2-data-api/official-references.md`
- `modules/platform-api/**`
- `packages/shared-contracts/**`
- `docs/03-modules/modules/platform-api.md`
- `docs/03-modules/packages/shared-contracts.md`
- `docs/07-data/01-database-schema.md`
- `docs/08-api/*.md`
- `docs/12-deployment/00-local-development.md`
- `docs/14-roadmap/03-implementation-milestone-flow.md`
- `docs/15-detailed-design/03-api-detail.md`
- `docs/15-detailed-design/04-data-detail.md`
- `docs/15-detailed-design/05-workflow-state-events.md`

### 验证

- 已执行 `git branch --show-current`，确认当前分支为 `dev`。
- 已执行 `git status --short`，确认开始前工作区干净。
- 已执行 `uv --version`、`python --version`、`docker --version`、`docker compose version`、`git --version`，确认本机工具可用。
- 已执行 `docker compose -f infra/docker-compose.dev.yml up -d postgres` 和 `docker compose -f infra/docker-compose.dev.yml ps`，PostgreSQL 容器状态 `healthy`。
- 已执行 `cd modules/platform-api; $env:CLOUDHELM_DATABASE_URL='postgresql+psycopg://cloudhelm:cloudhelm_dev@127.0.0.1:15432/cloudhelm'; uv run alembic upgrade head`，迁移应用成功。
- 已执行 `uv run pytest`，结果：`11 passed, 1 warning`。
- 已执行 `cd apps/control-console; npm.cmd run build`，结果：TypeScript 编译和 Vite build 成功。
- 已执行 `python -m json.tool` 验证事件 schema 和工具风险等级 schema。
- 已用 `yaml.safe_load` 验证 `packages/shared-contracts/openapi/cloudhelm.openapi.yaml`，确认版本为 `0.2.0` 且包含 `/api/tasks`。
- 已执行 `git diff --check`，结果通过。
- 已在 `dev` 提交 `d163eb2`：`feat: 完成 M2 数据模型与 API 底座`。
- 首次执行 `git push origin dev` 遇到 TLS 握手失败，已立即重试成功，远端 `dev` 更新到 `d163eb2`。
- 合并 `dev` 到 `main` 前已再次执行 `uv run pytest`（`11 passed, 1 warning`）和 `npm.cmd run build`（成功）。
- 已执行 `git diff main..dev --stat`、`git log --oneline --decorate --graph --max-count=20` 和 `git status --short`，确认合并前差异与 M2 范围一致且工作区干净。
- 已执行 `git switch main; git merge --ff-only dev; git push origin main; git switch dev`，远端 `main` 更新到 `d163eb2`，当前工作分支恢复为 `dev`。

## 2026-07-08（测试流程规范补充）

### 已完成

- 根据用户要求更新 `AGENTS.md` 的“测试与验证”章节，明确软件测试必须同时符合黑盒测试和白盒测试流程。
- 补充测试流程总要求：测试对象、范围、测试类型、测试数据、通过标准、不测范围、需求追溯和缺陷闭环。
- 补充黑盒测试要求：从用户、控制台、API 调用方、Agent 调用方或运维人员视角覆盖正常路径、边界值、异常输入、状态码、错误码、权限、分页、幂等和事件副作用。
- 补充白盒测试要求：从源码、状态机、事务边界、service/repository/workflow/policy 和工具风险等级视角覆盖分支、异常、回滚、事件写入、审批拦截和失败恢复。
- 补充提交与合并前测试门禁：提交到 `dev` 前必须执行匹配范围的黑盒/白盒测试，从 `dev` 合并到 `main` 前必须执行当前阶段完整验证。

### 进行中

- 本次测试规范补充已提交并同步到 `origin/dev` 与 `origin/main`。

### 阻塞与风险

- 本次为文档规范变更，不涉及生产代码；代码级黑盒/白盒测试不适用，但仍需做文档 diff 和 Git 状态检查。

### 下一步

- 下一阶段继续从 `dev` 执行 M2。

### 涉及文件

- `AGENTS.md`
- `PROJECT_PROGRESS.md`

### 验证

- 已用 UTF-8 读取 `AGENTS.md` 的测试章节。
- 已用 `apply_patch` 更新 `AGENTS.md` 和 `PROJECT_PROGRESS.md`。
- 已执行 `git diff --check`，结果通过。
- 已执行 `git diff --stat`，确认本次只修改 `AGENTS.md` 和 `PROJECT_PROGRESS.md`。
- 已在 `dev` 提交 `91313ce`：`docs: 补充黑盒与白盒测试流程规范`。
- 已执行 `git push origin dev`，远端 `dev` 更新到 `91313ce`。
- 已执行 `git diff main..dev --stat`，确认同步 `main` 前差异只包含 `AGENTS.md` 和 `PROJECT_PROGRESS.md`。
- 已执行 `git push origin main`，远端 `main` 更新到 `91313ce`。

## 2026-07-08（Git 管理约束补充）

### 已完成

- 根据用户提醒更新 `AGENTS.md` 的“Git 与提交”章节，明确项目必须使用 Git 管理。
- 补充无 `.git` 时的初始化要求、默认 `main` 分支、`.gitignore` 首次提交前检查、里程碑分支建议、提交前验证和 diff 复查要求。
- 明确无法执行 Git、仓库未初始化或用户暂不允许提交时，必须在 `PROJECT_PROGRESS.md` 和最终说明中记录原因与后续 Git 操作。
- 补充 `.gitignore` 忽略 `.obsidian/`，避免提交本地编辑器工作区配置。
- 已执行 `git init -b main` 初始化当前仓库，并设置本仓库 `core.quotepath=false` 以便中文文件名按 UTF-8 显示。
- 根据用户要求再次更新 `AGENTS.md`，明确开发分支固定为 `dev`，所有改动只能在 `dev` 或从 `dev` 拉出的功能分支进行，验证通过后才能合并入 `main`。
- 已执行 `git switch -c dev`，当前工作分支切换为 `dev`；此前 `main` 尚无提交，未把未验证改动提交到 `main`。
- 根据用户要求创建公开 GitHub 仓库：`https://github.com/ChaceQC/CloudHelm`，并将远端命名为 `origin`。
- 根据用户要求更新 `AGENTS.md`，补充 GitHub 同步和 push 规则：本地提交后必须同步 push `dev`，`main` 只接收已验证 `dev` 合并，创建远端后记录 URL、可见性和推送分支。
- 已在 `dev` 创建初始提交 `f3973b2`：`feat: 初始化 CloudHelm M1 工程基线`，并执行 `git push -u origin dev` 同步到 GitHub。
- 已在重新验证后将已验证的 `dev` 同步为 `main` 稳定分支，并执行 `git push -u origin main`。
- 已将 GitHub 默认分支设置为 `main`，远端 `dev` 和 `main` 当前都指向 `f3973b2`。

### 进行中

- M1 基线已同步到 GitHub；当前补记同步结果，补记后需要再次提交并推送 `dev`，再同步 `main`。

### 阻塞与风险

- 当前仓库已初始化 Git 且当前分支为 `dev`；后续禁止在 `main` 上直接修改或提交。
- 需要在提交前确认 `.gitignore` 已排除依赖目录、构建产物、缓存和本地编辑器目录。
- GitHub 仓库按用户要求为 public，后续不得提交真实密钥、Token、Cookie、服务器地址或私有凭据。

### 下一步

- 提交本次 `PROJECT_PROGRESS.md` 补记，并推送 `dev`。
- 重新同步 `main` 到已验证的 `dev` 最新提交。
- 下一阶段从 `dev` 开始执行 M2。

### 涉及文件

- `AGENTS.md`
- `PROJECT_PROGRESS.md`

### 验证

- 已用 UTF-8 读取 `AGENTS.md` 的 Git 章节。
- 已用 `apply_patch` 更新 `AGENTS.md` 和 `PROJECT_PROGRESS.md`。
- 已执行 `git init -b main`。
- 已执行 `git switch -c dev`。
- 已执行 `git branch --show-current`，确认当前分支为 `dev`。
- 已执行 `git status --short`，确认当前仓库进入 Git 管理且改动仍未提交。
- 已执行 `gh repo create CloudHelm --public --description 'CloudHelm graduation design multi-agent DevOps system' --source . --remote origin`。
- 已执行 `git remote -v`，确认 `origin` 指向 `https://github.com/ChaceQC/CloudHelm.git`。
- 已执行 `git diff --cached --stat` 和 `git status --ignored --short`，确认暂存内容并确认 `.obsidian/`、`node_modules/`、`dist/`、`.venv/` 已被忽略。
- 已执行 `uv run pytest`，结果：`1 passed, 1 warning`。
- 已执行 `npm.cmd run build`，结果：TypeScript 编译和 Vite build 成功。
- 已执行 `git push -u origin dev`，远端创建 `dev`。
- 已执行 `git push -u origin main`，远端创建 `main`。
- 已执行 `gh repo edit ChaceQC/CloudHelm --default-branch main`。
- 已执行 `gh repo view ChaceQC/CloudHelm --json nameWithOwner,visibility,url,defaultBranchRef`，确认仓库 `PUBLIC`、默认分支 `main`。

## 2026-07-08（M1 完成）

### 已完成

- 按 `PROJECT_PLAN.md` 完成 M1：Monorepo 骨架与最小工程。
- 创建 `apps/`、`modules/`、`packages/`、`infra/`、`examples/`、`tests/`、`informations/` 根目录，并补充非空 README 说明职责边界。
- 初始化 `modules/platform-api` 最小 FastAPI 工程，包含 `api`、`core`、`schemas` 分层和真实 `/health`。
- 使用 Pydantic response schema 返回服务名、状态、版本、运行环境和服务端 UTC 时间。
- 初始化 `apps/control-console` React + TypeScript + Vite 控制台骨架，`HealthPanel` 通过 `VITE_CLOUDHELM_API_BASE_URL` 调用真实 `/health`，不展示假任务、假 Agent 或假部署数据。
- 初始化 `packages/shared-contracts`，新增 `/health` OpenAPI、Task Event JSON Schema、Tool Risk Level JSON Schema 和类型预留目录。
- 创建根目录 `README.md`、`.gitignore`、`.env.example`，记录当前阶段、目录结构、启动/验证命令、环境变量和未实现能力边界。
- 更新 `informations/m1-foundation/official-references.md`，记录本机工具版本、`npm.cmd` 使用原因、`uv`/`npm` 实际命令和 Tauri 延后原因。
- 更新 `docs/12-deployment/00-local-development.md`，补充 M1 本地最小工程命令。
- 更新 `docs/14-roadmap/03-implementation-milestone-flow.md`，将 M1 所有任务打钩，并把当前下一步改为 M2。
- 重写 `PROJECT_PLAN.md`，生成 M2“数据模型、API 与事件底座”的详细执行计划。

### 进行中

- M2 尚未开始实现；当前已准备好 M2 的文档依据、任务拆分、预检步骤和完成判定。

### 阻塞与风险

- 当前目录已补做 Git 初始化；M1 相关改动将在复查暂存区后进入初始提交。
- Tauri/Rust 工具链中 `rustc`、`cargo` 可用，但 M1 只要求 React/TypeScript 骨架；`src-tauri` 延后到控制台主流程阶段接入，避免提前扩大桌面端范围。
- `uv run pytest` 通过，但 FastAPI TestClient 触发 Starlette 关于 `httpx` 的弃用提示；不影响 M1，通过 M2 依赖升级或测试客户端调整再处理。
- Windows PowerShell 会拦截 `npm.ps1`，前端命令需使用 `npm.cmd`。

### 下一步

- 执行 M2 预检：确认 Docker、PostgreSQL 开发环境和 M1 基线验证。
- 创建 `informations/m2-data-api/official-references.md`，归档 FastAPI、SQLAlchemy、Alembic、PostgreSQL、Pydantic 和 pytest 官方资料。
- 在 `modules/platform-api` 中实现数据库连接、迁移、models、repositories、services、schemas 和 M2 API。
- 同步扩展 OpenAPI、事件 schema、API 文档和本地开发命令。

### 涉及文件

- `README.md`
- `.gitignore`
- `.env.example`
- `apps/README.md`
- `apps/control-console/**`
- `modules/README.md`
- `modules/platform-api/**`
- `packages/README.md`
- `packages/shared-contracts/**`
- `infra/README.md`
- `examples/README.md`
- `tests/README.md`
- `informations/m1-foundation/official-references.md`
- `docs/12-deployment/00-local-development.md`
- `docs/14-roadmap/03-implementation-milestone-flow.md`
- `PROJECT_PLAN.md`
- `PROJECT_PROGRESS.md`

### 验证

- 已执行 `Get-ChildItem -Force` 和 `Get-ChildItem apps,modules,packages,infra,examples,tests,informations`，确认 M1 根目录和 README 存在。
- 已执行 `uv run pytest`，结果：`1 passed, 1 warning`。
- 已执行 `npm.cmd install`，结果：生成 `package-lock.json`，`found 0 vulnerabilities`。
- 已执行 `npm.cmd run build`，结果：TypeScript 编译和 Vite build 成功。
- 已启动 `uv run uvicorn cloudhelm_platform_api.main:app --host 127.0.0.1 --port 18080` 并执行 `Invoke-RestMethod http://127.0.0.1:18080/health`，结果返回 `status=ok`、`version=0.1.0`、`environment=development`。
- 已用 `python -m json.tool` 验证 `task-event.schema.json`、`tool-risk-level.schema.json` 和 `apps/control-console/package.json` JSON 语法。

## 2026-07-08

### 已完成

- 创建并持续完善 `AGENTS.md`，形成仓库协作约束。
- 补充版本号控制、Git 提交、架构边界、代码结构、测试验证、文档同步和安全要求。
- 补充“优先使用成熟方案和语言/框架特性，不重复造轮子”的实现原则。
- 补充代码注释规范、API/跨模块接口文档要求、禁止用模拟或简化方式代替完整功能实现的规则。
- 删除错误定位的 `PROJECT_PLAN.md`；该文件不应保存总项目计划，而应只保存下一步要落实的详细执行计划。
- 创建 `PROJECT_PROGRESS.md`，建立后续进度记录格式。
- 更新 `AGENTS.md` 中 `PROJECT_PLAN.md` 的语义，明确它是阶段性执行计划文件。
- 新增 `docs/14-roadmap/03-implementation-milestone-flow.md`，按 M0-M10 生成整个项目总排期流程。
- 在总排期中将 M0 的具体任务复选框标记为已完成。
- 更新 `docs/14-roadmap/README.md` 和 `docs/README.md`，加入总排期流程入口。
- 更新 `AGENTS.md`，明确完成每个可验证任务或阶段后必须在总排期流程中打钩，并重写 `PROJECT_PLAN.md` 指向下一个未完成阶段。
- 重新创建 `PROJECT_PLAN.md`，内容聚焦 M1“Monorepo 骨架与最小工程”的详细执行计划。
- 更新 `AGENTS.md` 的技术选型与实现原则，要求写代码前实时参考设计文档、接口契约、当前计划和相关开源项目实践，不得盲目实现。
- 按 `AGENTS.md` 和总排期规则，将 `PROJECT_PLAN.md` 细化为可执行的 M1 计划，补充预检步骤、参考资料、任务拆分、命令示例、打钩规则、完成判定和风险处理。
- 更新 `AGENTS.md` 和总排期流程，明确后续每个阶段的 `PROJECT_PLAN.md` 都必须达到当前 M1 计划的详细程度。
- 更新 `AGENTS.md` 和 `PROJECT_PLAN.md`，明确缺少工具或依赖时优先项目内、模块内或隔离环境安装，尽量避免全局安装，并要求记录依赖来源和安装命令。
- 更新 `AGENTS.md`，明确搜索到的官方文档、开源项目资料、技术选型依据和命令来源可按层级保存到 `informations/`。
- 创建 `informations/README.md` 和 `informations/m1-foundation/official-references.md`，归档 M1 阶段官方资料来源、采用结论和禁止保存内容。
- 同步更新 `PROJECT_PLAN.md` 和 `docs/14-roadmap/03-implementation-milestone-flow.md`，把 `informations/` 纳入 M1 根目录和验证范围。

### 进行中

- 将 CloudHelm 从设计文档阶段推进到可实现的项目基线阶段。

### 阻塞与风险

- 当前仓库尚未初始化实际源码目录和可运行应用代码。
- 尚未确认远端 demo/staging 服务器配置、域名、端口和部署凭据。
- M1 尚未开始实现，需要按 `PROJECT_PLAN.md` 创建 Monorepo 源码目录骨架。

### 下一步

- 按 `PROJECT_PLAN.md` 执行 M1，创建 Monorepo 源码目录骨架。
- 初始化 `apps/control-console`、`modules/platform-api`、`packages/shared-contracts` 的最小可运行工程。
- 维护 `informations/m1-foundation/official-references.md`，在执行 M1 时补充实际采用的版本、命令和取舍结论。
- 为 Task API、Agent Run API、Tool Call API 补充实现前接口文档检查。

### 涉及文件

- `AGENTS.md`
- `PROJECT_PLAN.md`
- `PROJECT_PROGRESS.md`
- `docs/14-roadmap/03-implementation-milestone-flow.md`
- `docs/14-roadmap/README.md`
- `docs/README.md`

### 验证

- 已使用 UTF-8 读取并检查 `AGENTS.md`。
- 已确认并删除错误定位的 `PROJECT_PLAN.md`。
- 已重新创建聚焦 M1 的 `PROJECT_PLAN.md`。
- 已使用 UTF-8 检查总排期入口和计划文件。
- 已用 `apply_patch` 更新 `AGENTS.md` 和 `PROJECT_PROGRESS.md`。
- 已用 UTF-8 读取 `PROJECT_PLAN.md`、总排期、模块图和 MVP 技术组合后生成详细计划。
- 已同步 `docs/14-roadmap/03-implementation-milestone-flow.md` 的计划详细度要求。
- 已同步当前 M1 计划中的工具/依赖安装约束。
- 已用 UTF-8 检查并更新 `AGENTS.md`、`PROJECT_PLAN.md`、`PROJECT_PROGRESS.md` 和总排期流程中的 `informations/` 资料归档规则。
- 已对 `informations/m1-foundation/official-references.md` 中的官方链接执行 HTTP HEAD 检查，FastAPI、uv、Vite、Tauri、OpenAPI、JSON Schema 链接均返回 200。

## 2026-07-08

### 已完成

- 完成 M5：新增 `modules/tool-gateway` 独立模块，包含 `ToolRegistry`、`ToolGateway`、`ToolPolicy`、审计摘要和默认本地工具注册。
- 实现 Requirement Tool、Design Tool、Repo Tool、Sandbox Tool、Git Tool 和 L3 审批占位工具 `approval.request_remote_action`。
- Repo Tool 支持受控 `workspace_root` 内真实读、搜、列、写，并拒绝越界、symlink 越界、敏感文件、依赖目录和构建产物。
- Sandbox Tool 支持本地受控目录命令执行、超时、环境变量白名单、stdout/stderr 摘要和 artifact 元数据收集；Docker sandbox 暂未接入，已记录为 M6 前置增强。
- Git Tool 支持本地 `status`、`diff`、`create_branch`、`commit`，不实现 push、rebase、tag、远端 PR。
- Platform API 新增 `GET /api/tool-gateway/tools` 和 `POST /api/tasks/{task_id}/tool-gateway/call`，工具调用写入 `tool_calls` 与 `event_logs`，L3 调用创建 `approval_requests` 且 ToolCall 为 `waiting_approval`。
- 为 `tool_calls` 增加 `idempotency_key`、`arguments_summary`、`result_summary`、`stdout_summary`、`stderr_summary`、`duration_ms`、`error_code` 字段和任务内幂等唯一索引。
- 控制台 ToolCall 面板展示真实工具名、风险等级、状态、参数摘要、幂等键、耗时、错误码、审批 ID、stdout/stderr 摘要和 result JSON；UI 保持 Codex 式低饱和面板风格。
- 新增 M5 工具 schema、更新 OpenAPI、README、`.env.example`、Tool Layer、安全、API、控制台、详细设计和共享契约文档。
- 创建 `informations/m5-tool-gateway/official-references.md`，归档 Pydantic、Python pathlib/subprocess、Git、Docker、MCP、pytest 官方资料和采用结论。
- 更新总排期流程，将 M5 任务标记完成；重写 `PROJECT_PLAN.md` 指向 M6“本地代码实现、测试与 PR 闭环”详细计划。

### 进行中

- M6 尚未开始实现；当前已准备好 M6 的文档依据、任务拆分、预检步骤和完成判定。

### 阻塞与风险

- Sandbox Tool 目前是本地受控目录 + `subprocess` 超时，并非 Docker sandbox；已在 README、M5 资料归档、安全文档和 M6 计划中记录，M6 前需评估是否增强隔离。
- `uv run pytest` 仍出现 FastAPI/Starlette TestClient 关于 `httpx` 的弃用提示，不影响 M5 通过；后续可在依赖升级阶段处理。
- M5 不执行远端部署、不 push、不创建真实远端 PR；这些能力留到 M6/M7 后续阶段。

### 下一步

- 按 `PROJECT_PLAN.md` 执行 M6，创建 `examples/sample-repo-python` 和 M6 资料归档。
- 扩展 Coder/Tester/Reviewer/Security Agent 结构化输出和 Orchestrator M6 状态机。
- 在 Platform API 增加 artifact、test/security report、review 结论和 PR record 数据流。
- 控制台展示真实 diff、测试报告、安全结果、review 结论和 PR record。

### 涉及文件

- `modules/tool-gateway/**`
- `modules/platform-api/**`
- `apps/control-console/**`
- `packages/shared-contracts/**`
- `informations/m5-tool-gateway/official-references.md`
- `docs/05-tool-layer/**`
- `docs/08-api/**`
- `docs/09-control-console/**`
- `docs/10-security/**`
- `docs/15-detailed-design/**`
- `docs/14-roadmap/03-implementation-milestone-flow.md`
- `README.md`
- `.env.example`
- `PROJECT_PLAN.md`
- `PROJECT_PROGRESS.md`

### 验证

- 已执行 `docker compose -f infra/docker-compose.dev.yml up -d postgres`，PostgreSQL 容器处于 Running。
- 已执行 `cd modules/tool-gateway; uv run pytest`，结果：`14 passed`。
- 已执行 `cd modules/platform-api; uv run alembic upgrade head`，结果：迁移到 head 成功。
- 已执行 `cd modules/platform-api; uv run pytest`，结果：`21 passed, 1 warning`。
- 已执行 `cd modules/agent-runtime; uv run pytest`，结果：`5 passed`。
- 已执行 `cd modules/orchestrator; uv run pytest`，结果：`3 passed`。
- 已执行 `cd apps/control-console; npm.cmd run build`，结果：TypeScript 编译和 Vite build 成功。
- 已执行 `python -m json.tool` 验证 `packages/shared-contracts/schemas/**/*.json`，结果：15 个 JSON schema 文件语法有效。
- 已用 PyYAML 解析 `packages/shared-contracts/openapi/cloudhelm.openapi.yaml`，结果：`version=0.4.0`，paths 数量为 34。
