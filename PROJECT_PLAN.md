# PROJECT_PLAN.md

本文件只记录当前下一步要落实的详细执行计划，不保存总项目规划。总流程和打钩清单见 `docs/14-roadmap/03-implementation-milestone-flow.md`。

## 1. 当前阶段

M4：Agent 编排与规格化闭环。

## 2. 阶段目标

在 M2 真实数据 API 与 M3 控制台主流程之上，实现从 Task 创建后进入 Requirement / Architect / Planner 的最小可验收编排闭环。M4 必须产生可校验、可持久化、可在控制台展示的真实结构化记录，不得用前端假数据、固定返回、空实现或测试夹具冒充 Agent 输出。

本阶段目标：

- 实现 Orchestrator 状态机：`Created -> RequirementClarifying -> Designing -> WaitingDesignApproval / Planning`。
- 实现 Requirement Agent，读取真实 Task 输入并写入 `requirement_specs`。
- 实现 Architect Agent，基于已通过或最新 Requirement 写入 `technical_designs`。
- 实现 Planner Agent，输出可持久化的 Development Plan / task graph。
- 为 Agent 输入、输出、运行结果、失败恢复和结构化输出 schema 建立后端契约。
- 控制台新增“启动/推进编排”入口，并能展示 Requirement、Technical Design、Development Plan 与状态迁移事件。
- 同步 OpenAPI、数据库文档、Agent/Tool 契约、控制台说明、测试记录和总排期。

本阶段不实现 Coder/Tester/Reviewer，不执行 Repo 写入、Sandbox 命令、Git PR、Tool Gateway 真实工具调用、远端部署、监控告警或生产级多租户权限。M4 中 Agent 只允许写入需求、设计和开发计划类数据库记录；任何需要真实工具执行的动作只能生成后续计划或审批建议。

版本影响：M4 新增 Agent 编排、Development Plan、状态迁移和可能的新 API / DB schema，属于兼容新增能力。完成后建议将项目版本提升到 `0.3.0`，并同步 `README.md`、`.env.example`、`modules/platform-api/pyproject.toml`、`apps/control-console/package.json`、OpenAPI 和相关文档。

## 3. 必须先参考的资料

开始编码前必须阅读：

- `AGENTS.md`
- `docs/14-roadmap/03-implementation-milestone-flow.md`
- `docs/04-agents/00-agent-layer.md`
- `docs/04-agents/01-collaboration-state-machine.md`
- `docs/04-agents/02-structured-output-contract.md`
- `docs/05-tool-layer/00-tool-gateway-overview.md`
- `docs/08-api/00-api-overview.md`
- `docs/08-api/01-task-api.md`
- `docs/08-api/02-requirement-design-api.md`
- `docs/08-api/03-agent-run-api.md`
- `docs/08-api/05-approval-api.md`
- `docs/08-api/06-event-stream-api.md`
- `docs/09-control-console/00-page-structure.md`
- `docs/09-control-console/01-key-interactions.md`
- `docs/15-detailed-design/00-mvp-scope-and-cutline.md`
- `docs/15-detailed-design/01-module-contracts.md`
- `docs/15-detailed-design/02-agent-tool-contract.md`
- `docs/15-detailed-design/03-api-detail.md`
- `docs/15-detailed-design/04-data-detail.md`
- `docs/15-detailed-design/05-workflow-state-events.md`
- `packages/shared-contracts/openapi/cloudhelm.openapi.yaml`
- `apps/control-console/README.md`
- `modules/platform-api/README.md`

实现时应参考成熟方案和官方文档：

- LangGraph / LangChain 状态图和 checkpoint 思路；如果暂不引入依赖，必须说明取舍原因。
- Pydantic 2 结构化输出、JSON Schema 与模型校验。
- OpenAI / 兼容 LLM 的 structured outputs 或 JSON schema 输出实践；不得把未校验自然语言直接写入核心字段。
- FastAPI dependency、service/repository 分层和后台任务边界。
- React 表单、状态同步和错误边界实践。
- pytest 对状态机、schema 校验、异常分支和事务副作用的白盒测试实践。

本阶段搜索或查阅到的外部资料应归档到：

```text
informations/m4-agent-orchestration/official-references.md
```

## 4. 本阶段不做的事项

- 不实现 Coder、Tester、Reviewer、Security、Release / Deploy、SRE Agent 的真实执行。
- 不让 Agent 绕过 Orchestrator 或 Platform API 直接写数据库。
- 不让 Agent 绕过 Tool Gateway 调用命令、文件、Git、Docker、SSH 或远端服务。
- 不在生产代码中写固定 Requirement / Design / Plan 作为“自动生成”结果。
- 不把缺少 LLM 凭据时的测试 fake 当作生产 fallback。
- 不新增大型状态库、消息队列或插件系统，除非先补充取舍说明和验证计划。
- 不把 `approval_requests` 的内部联调记录包装成真实高风险动作已自动执行。

## 5. 预检步骤

### 5.1 Git 与工作区

```powershell
git branch --show-current
git status --short
```

确认当前分支为 `dev`。若在 `main`，必须先切回 `dev` 或从 `dev` 拉出功能分支。

### 5.2 后端 M3 基线

```powershell
docker compose -f infra/docker-compose.dev.yml up -d postgres
cd modules/platform-api
$env:CLOUDHELM_DATABASE_URL='postgresql+psycopg://cloudhelm:cloudhelm_dev@127.0.0.1:15432/cloudhelm'
uv run alembic upgrade head
uv run pytest
```

### 5.3 前端 M3 基线

```powershell
cd apps/control-console
npm.cmd install
npm.cmd run build
```

### 5.4 配置预检

检查是否存在本阶段需要的模型配置。推荐预留但不提交真实密钥：

```powershell
$env:CLOUDHELM_LLM_PROVIDER
$env:CLOUDHELM_LLM_MODEL
$env:CLOUDHELM_LLM_API_KEY
```

如果缺少真实模型凭据，M4 生产路径不得标记为完整完成；可以先实现 provider 接口、schema、状态机和测试 fake，并在 `PROJECT_PROGRESS.md` 记录阻塞范围。

## 6. 详细任务拆分

### 6.1 创建 M4 资料归档

创建或更新：

```text
informations/m4-agent-orchestration/official-references.md
```

必须覆盖：

- LangGraph / 状态机实践。
- Pydantic JSON Schema / validation。
- LLM structured outputs / JSON schema 输出。
- FastAPI 后台任务或同步 service 调用边界。
- pytest 状态机与 schema 测试参考。

完成后在 `PROJECT_PROGRESS.md` 记录已查阅资料和采用结论。

### 6.2 补充共享契约与数据库 schema

建议新增或更新：

```text
packages/shared-contracts/schemas/agents/
  agent-run-output.schema.json
  requirement-agent-output.schema.json
  architect-agent-output.schema.json
  planner-agent-output.schema.json
  development-plan.schema.json
packages/shared-contracts/openapi/cloudhelm.openapi.yaml
docs/15-detailed-design/02-agent-tool-contract.md
docs/15-detailed-design/04-data-detail.md
```

后端建议新增：

```text
modules/platform-api/src/cloudhelm_platform_api/models/development_plan.py
modules/platform-api/src/cloudhelm_platform_api/schemas/development_plan.py
modules/platform-api/src/cloudhelm_platform_api/repositories/development_plan_repository.py
modules/platform-api/src/cloudhelm_platform_api/services/development_plan_service.py
modules/platform-api/src/cloudhelm_platform_api/api/development_plans.py
migrations/versions/20260708_0002_create_m4_agent_tables.py
```

要求：

- 新增 `development_plans` 表，至少包含 `id`、`task_id`、`project_id`、`technical_design_id`、`summary`、`steps_json`、`risks_json`、`status`、`version`、`created_by_agent_run_id`、`created_at`、`updated_at`。
- 评估是否给 `agent_runs` 增加 `summary`、`structured_output_type`、`structured_output_json`、`error_code`、`error_message`；如果不改表，必须说明输出落库位置。
- 所有 JSON 字段使用 PostgreSQL JSONB，并在 Pydantic 层校验结构。
- 更新 OpenAPI 和数据文档，说明版本影响。

### 6.3 建立 agent-runtime 模块

建议新增：

```text
modules/agent-runtime/
  pyproject.toml
  README.md
  src/cloudhelm_agent_runtime/
    __init__.py
    agents/
      requirement_agent.py
      architect_agent.py
      planner_agent.py
    schemas/
      agent_io.py
      requirement.py
      design.py
      development_plan.py
    providers/
      base.py
      openai_compatible.py
    prompts/
      requirement.md
      architect.md
      planner.md
    tests/
      test_agent_output_validation.py
```

要求：

- 每个 Agent 必须有职责说明、输入结构、输出结构和允许工具列表注释。
- Agent 输出必须先过 Pydantic / JSON Schema 校验，再交给 Orchestrator 写入 Platform API。
- Provider 层只负责模型调用和返回文本/JSON，不写业务表。
- 测试 fake 只能放在 `tests` 或测试夹具中，不得进入生产路径作为默认 Agent。
- 缺少真实 LLM 配置时，生产运行应返回明确错误并进入可恢复状态，不得静默写固定内容。

### 6.4 建立 orchestrator 模块与状态机

建议新增：

```text
modules/orchestrator/
  pyproject.toml
  README.md
  src/cloudhelm_orchestrator/
    __init__.py
    state_machine.py
    services/
      orchestration_service.py
      task_context_loader.py
      agent_result_applier.py
    tests/
      test_state_machine.py
      test_orchestration_service.py
```

要求：

- 状态机只覆盖 M4 范围：`Created`、`RequirementClarifying`、`Designing`、`WaitingDesignApproval`、`Planning`。
- 每次迁移必须调用 Platform API service 写入 Task 状态/阶段和 EventLog。
- Requirement Agent 成功后写 `RequirementSpecCreated`，进入 `Designing`。
- Architect Agent 成功后写 `TechnicalDesignCreated`；若风险等级为 `L2` 及以上或设计包含 migration / deployment 相关风险，进入 `WaitingDesignApproval` 并创建 ApprovalRequest，否则进入 `Planning`。
- Planner Agent 成功后写 `DevelopmentPlanCreated`，任务进入 M4 定义的等待后续实现状态。
- 失败时写结构化失败事件，任务不得直接伪装为完成。

### 6.5 扩展 Platform API 编排入口

建议新增或修改：

```text
modules/platform-api/src/cloudhelm_platform_api/api/orchestration.py
modules/platform-api/src/cloudhelm_platform_api/schemas/orchestration.py
modules/platform-api/src/cloudhelm_platform_api/services/task_service.py
modules/platform-api/src/cloudhelm_platform_api/services/event_service.py
```

建议接口：

```text
POST /api/tasks/{task_id}/start
POST /api/tasks/{task_id}/run-next
GET  /api/tasks/{task_id}/development-plans
GET  /api/development-plans/{plan_id}
```

要求：

- `start` 只能从 `created` 或可恢复状态启动，重复启动必须返回状态冲突或幂等结果。
- `run-next` 根据当前阶段推进一个最小 Agent 步骤，便于 M4 验证和答辩演示。
- API 必须返回真实 DTO，并保留 `trace_id` 错误结构。
- 写操作必须在 service 层完成事务与事件副作用，路由层不得直接写数据库。

### 6.6 控制台接入 M4 编排交互

建议新增或修改：

```text
apps/control-console/src/shared/types/api.ts
apps/control-console/src/shared/api/cloudhelmApi.ts
apps/control-console/src/features/tasks/TaskBoard.tsx
apps/control-console/src/features/tasks/TaskDetail.tsx
apps/control-console/src/features/design-review/
apps/control-console/src/features/planning/
  DevelopmentPlanPanel.tsx
```

要求：

- Task Board 或 Task Detail 提供“启动编排 / 推进一步”按钮，调用真实 `start` / `run-next` API。
- 控制台展示 Requirement、Technical Design 和 Development Plan 的真实结构化内容。
- 若缺少模型配置或 Agent 输出失败，展示真实错误和 trace_id，不展示假结果。
- Design Review Panel 继续复用 approve / request-changes API；审批后允许继续推进到 Planning。
- 明确 UI 文案：M4 只覆盖 Requirement / Architect / Planner，不执行代码修改和工具调用。

### 6.7 测试与验证设计

后端至少新增：

```text
modules/platform-api/tests/test_orchestration_api.py
modules/platform-api/tests/test_development_plan_api.py
modules/orchestrator/tests/test_state_machine.py
modules/agent-runtime/tests/test_agent_output_validation.py
```

黑盒测试要求：

- 创建 Project -> Task -> start -> 查询 Requirement / Timeline。
- 通过 Requirement -> run-next -> 查询 Technical Design。
- 审批 Design 或低风险自动进入 Planning -> 查询 Development Plan。
- 缺少 LLM 配置时返回明确错误，状态和事件可追溯。
- 非法状态重复 start / run-next 返回稳定错误码和 trace_id。

白盒测试要求：

- Pydantic schema 校验正常、边界和异常 JSON。
- 状态机每个允许迁移和禁止迁移分支。
- service 事务：AgentRun、业务记录、EventLog 同步写入或同步回滚。
- 审批触发规则：高风险设计进入 `waiting_approval`，低风险设计可进入 `planning`。

至少执行：

```powershell
cd modules/platform-api
$env:CLOUDHELM_DATABASE_URL='postgresql+psycopg://cloudhelm:cloudhelm_dev@127.0.0.1:15432/cloudhelm'
uv run alembic upgrade head
uv run pytest

cd ..\..\apps\control-console
npm.cmd run build
```

如果新增 `modules/orchestrator` 或 `modules/agent-runtime` 独立环境，还必须执行对应模块测试命令，并写入 README。

### 6.8 文档同步

必须更新：

```text
README.md
.env.example
apps/control-console/README.md
modules/platform-api/README.md
docs/04-agents/*.md
docs/08-api/*.md
docs/09-control-console/*.md
docs/15-detailed-design/01-module-contracts.md
docs/15-detailed-design/02-agent-tool-contract.md
docs/15-detailed-design/03-api-detail.md
docs/15-detailed-design/04-data-detail.md
docs/15-detailed-design/05-workflow-state-events.md
docs/14-roadmap/03-implementation-milestone-flow.md
PROJECT_PROGRESS.md
```

要求：

- 文档必须说明 M4 能力边界：只完成需求、设计、计划闭环，不写代码、不执行工具。
- 若引入 LLM provider、LangGraph 或新依赖，必须说明用途、替代方案和维护成本。
- OpenAPI、数据库 schema、事件名称和控制台文案必须保持一致。

## 7. 完成后的同步动作

M4 所有任务完成后必须：

1. 更新 `docs/14-roadmap/03-implementation-milestone-flow.md`，将 M4 下所有任务打钩。
2. 更新 `PROJECT_PROGRESS.md`，记录创建或修改的文件、验证命令、失败修复、遗留风险和模型配置状态。
3. 根据下一个未完成阶段 M5 重写或更新 `PROJECT_PLAN.md`。
4. 同步 `README.md`、模块 README、控制台 README、API 文档、Agent/Tool 契约和 OpenAPI。
5. 如提升版本到 `0.3.0`，同步所有版本字段并说明版本影响。

## 8. M4 完成判定

只有全部满足才算 M4 完成：

- Orchestrator 能从真实 Task 推进 Requirement / Architect / Planner 状态。
- Requirement Agent 输出通过 schema 校验并写入真实 `requirement_specs`。
- Architect Agent 输出通过 schema 校验并写入真实 `technical_designs`。
- Planner Agent 输出通过 schema 校验并写入真实 Development Plan。
- 每次状态迁移、AgentRun 和业务记录写入真实 EventLog。
- 控制台能通过真实 API 启动/推进编排并展示 Requirement、Design、Plan、Timeline。
- 缺少模型配置、结构化输出失败、非法状态迁移等异常路径可见且可追溯。
- 后端、Agent Runtime、Orchestrator 和前端构建/测试通过。
- `PROJECT_PROGRESS.md`、总排期流程和下一阶段 `PROJECT_PLAN.md` 已同步。

## 9. 风险与处理

- 如果没有真实 LLM 凭据：生产 Agent 路径不得标记完成；先完成 schema、状态机、API、测试 fake 和阻塞记录。
- 如果 LangGraph 引入成本过高：可以先用显式状态机实现 M4 最小闭环，但必须在资料归档和进度中说明取舍。
- 如果 Agent 输出 schema 不稳定：增加格式修复重试和失败事件，不得把解析失败的自然语言写入核心表。
- 如果状态机和现有 TaskService 冲突：先补模块契约和 API 文档，再改 service。
- 如果控制台状态刷新出现滞后：以 Timeline 和详情刷新为准，记录 SSE 边界，不展示本地推测状态。
- 如果验证失败：不得把 M4 任务打钩，不得提交“完成”类 commit；修复后必须执行回归测试。
