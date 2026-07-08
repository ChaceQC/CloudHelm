# PROJECT_PLAN.md

本文件只记录当前下一步要落实的详细执行计划，不保存总项目规划。总流程和打钩清单见 `docs/14-roadmap/03-implementation-milestone-flow.md`。

## 1. 当前阶段

M3：控制台任务主流程。

## 2. 阶段目标

在 M2 数据模型、API 与事件底座之上，让 `apps/control-console` 从最小健康检查界面升级为可操作的任务主流程控制台。M3 必须调用真实 Platform API，不得使用静态假数据、内存 mock 或固定任务列表冒充完成。

本阶段目标：

- 实现 Project Sidebar，展示真实 Project 列表并支持创建/选择项目。
- 实现 Task Board 和 Task Detail，展示真实 Task 列表、状态、风险等级、阶段和详情。
- 实现需求输入表单，调用真实 `POST /api/tasks` 创建任务。
- 展示 Requirement Spec、Acceptance Criteria、Technical Design 的真实后端数据结构。
- 接入 Timeline / SSE，展示 Agent Timeline、Tool Calls、Event Log。
- 实现 Design Review Panel 和 Approval Panel 的基础交互，调用真实 approve / reject / request-changes API。
- 同步更新控制台 README、API client 类型、共享契约使用说明、测试记录和总排期。

本阶段不实现 Agent 自动生成 Requirement / Design，不实现 Tool Gateway 真实工具执行，不实现 Git PR、远端部署、监控告警或 Tauri 完整桌面壳。如需展示 AgentRun、ToolCall、Approval，只能读取 M2 数据库真实记录或调用明确标注为“内部联调”的创建接口。

版本影响：本阶段属于兼容新增前端能力；如仅修改控制台和文档，可保持项目版本 `0.2.x`，完成后建议提升补丁版本到 `0.2.1` 并同步 `README.md`、`apps/control-console/package.json`、必要的 OpenAPI/文档说明。

## 3. 必须先参考的资料

开始编码前必须阅读：

- `AGENTS.md`
- `docs/14-roadmap/03-implementation-milestone-flow.md`
- `docs/09-control-console/00-page-structure.md`
- `docs/09-control-console/01-key-interactions.md`
- `docs/08-api/00-api-overview.md`
- `docs/08-api/01-task-api.md`
- `docs/08-api/02-requirement-design-api.md`
- `docs/08-api/03-agent-run-api.md`
- `docs/08-api/04-tool-call-api.md`
- `docs/08-api/05-approval-api.md`
- `docs/08-api/06-event-stream-api.md`
- `docs/15-detailed-design/00-mvp-scope-and-cutline.md`
- `docs/15-detailed-design/03-api-detail.md`
- `docs/15-detailed-design/05-workflow-state-events.md`
- `packages/shared-contracts/openapi/cloudhelm.openapi.yaml`
- `apps/control-console/README.md`

实现时应参考成熟方案和官方文档：

- React 官方组件、state、effect、表单和错误边界实践。
- TypeScript 类型建模和 API client 类型推导。
- Vite 环境变量和构建配置。
- 浏览器 `EventSource` / SSE 或 fetch 轮询实践。
- 前端测试：Vitest / React Testing Library 或 Playwright。若暂未引入测试框架，必须记录原因和替代验证步骤。

本阶段搜索或查阅到的外部资料应归档到：

- `informations/m3-control-console/official-references.md`

## 4. 本阶段不做的事项

- 不实现真实 Agent 自动运行。
- 不在前端硬编码假项目、假任务、假事件、假审批作为完成状态。
- 不绕过 Platform API 直接访问数据库。
- 不实现真实 Git diff、PR、Tool Gateway 执行、远端部署、监控告警。
- 不把 M2 内部联调创建接口包装成“Agent 已自动完成”。
- 不引入大型 UI 框架或状态库，除非先说明用途、替代方案和维护成本。

## 5. 预检步骤

### 5.1 Git 与工作区

```powershell
git branch --show-current
git status --short
```

确认当前分支为 `dev`。若在 `main`，必须先切回 `dev`。

### 5.2 后端 M2 基线

```powershell
docker compose -f infra/docker-compose.dev.yml up -d postgres
cd modules/platform-api
$env:CLOUDHELM_DATABASE_URL='postgresql+psycopg://cloudhelm:cloudhelm_dev@127.0.0.1:15432/cloudhelm'
uv run alembic upgrade head
uv run pytest
uv run uvicorn cloudhelm_platform_api.main:app --host 127.0.0.1 --port 18080
```

在另一个终端验证：

```powershell
Invoke-RestMethod http://127.0.0.1:18080/health
```

### 5.3 前端基线

```powershell
cd apps/control-console
npm.cmd install
npm.cmd run build
```

确认 M1 控制台仍可构建。

## 6. 详细任务拆分

### 6.1 创建 M3 资料归档

创建或更新：

```text
informations/m3-control-console/official-references.md
```

必须覆盖：

- React state/effect/form 官方实践。
- TypeScript 类型和 Vite 环境变量。
- EventSource / SSE 或 fetch 轮询参考。
- 前端测试或浏览器验证方案。

完成后在 `PROJECT_PROGRESS.md` 记录已查阅资料和采用结论。

### 6.2 建立前端 API client 和类型

建议新增：

```text
apps/control-console/src/shared/api/
  client.ts
  cloudhelmApi.ts
apps/control-console/src/shared/types/
  api.ts
  events.ts
```

要求：

- API base URL 来自 `VITE_CLOUDHELM_API_BASE_URL`。
- 所有请求必须处理 HTTP 错误结构 `code/message/detail/trace_id`。
- 类型与 `packages/shared-contracts/openapi/cloudhelm.openapi.yaml` 保持字段一致。
- 不在组件里散落 `fetch` URL 拼接；统一通过 API client 调用。
- 记录必要注释：调用方、返回值、错误边界、M2/M3 功能边界。

### 6.3 实现 Project Sidebar

建议新增：

```text
apps/control-console/src/features/projects/
  ProjectSidebar.tsx
  ProjectCreateForm.tsx
  useProjects.ts
```

要求：

- 调用 `GET /api/projects` 展示真实项目列表。
- 调用 `POST /api/projects` 创建项目。
- 支持选择当前项目，并把 `project_id` 传给任务列表。
- 覆盖加载态、空状态、错误态和创建成功刷新。

完成后在总流程中勾选：

```markdown
- [x] 实现 Project Sidebar。
```

### 6.4 实现 Task Board 和 Task Detail

建议新增：

```text
apps/control-console/src/features/tasks/
  TaskBoard.tsx
  TaskDetail.tsx
  TaskCreateForm.tsx
  TaskStatusBadge.tsx
  useTasks.ts
```

要求：

- 调用 `GET /api/tasks?project_id=...` 展示真实任务。
- 调用 `GET /api/tasks/{task_id}` 展示任务详情。
- 调用 `POST /api/tasks` 创建任务。
- 支持 pause / resume / cancel 操作，并刷新任务和时间线。
- 状态、风险等级和阶段展示必须来自后端响应。

完成后在总流程中勾选：

```markdown
- [x] 实现 Task Board 和 Task Detail。
- [x] 实现需求输入表单，并调用真实 Task API。
```

### 6.5 展示 Requirement / Design 数据

建议新增：

```text
apps/control-console/src/features/design-review/
  RequirementPanel.tsx
  TechnicalDesignPanel.tsx
  DesignReviewPanel.tsx
```

要求：

- 调用 `GET /api/tasks/{task_id}/requirements`。
- 调用 `GET /api/tasks/{task_id}/technical-designs`。
- 展示 `raw_input`、`user_story`、`acceptance_criteria_json`、`constraints_json`、`content_markdown`、`openapi_json`、`db_schema_json`。
- 支持 approve / request-changes 基础交互，调用真实 API。
- 若当前任务没有 Requirement / Design，显示真实空状态，不展示假内容。

完成后在总流程中勾选：

```markdown
- [x] 展示 Requirement Spec、Acceptance Criteria、Technical Design 的真实后端数据结构。
```

### 6.6 接入 Timeline、Tool Calls 和 Approval

建议新增：

```text
apps/control-console/src/features/tasks/
  TaskTimeline.tsx
apps/control-console/src/features/approvals/
  ApprovalPanel.tsx
apps/control-console/src/features/tool-calls/
  ToolCallList.tsx
```

要求：

- 调用 `GET /api/tasks/{task_id}/timeline` 展示事件。
- 优先尝试 `EventSource` 连接 `GET /api/tasks/{task_id}/events/stream`；若 M2 SSE 只输出当前事件和 heartbeat，则记录为“轮询/重连式事件流边界”。
- 调用 `GET /api/tasks/{task_id}/tool-calls` 展示工具名、风险等级、状态、参数摘要。
- 调用 `GET /api/approvals` 和 approve / reject API 展示基础审批卡片。
- Approval 操作必须显示成功/失败结果和 trace_id。

完成后在总流程中勾选：

```markdown
- [x] 接入事件流，展示 Agent Timeline、Tool Calls、Event Log。
- [x] 实现 Design Review Panel 和 Approval Panel 的基础交互。
```

### 6.7 前端布局与交互整合

修改：

```text
apps/control-console/src/App.tsx
apps/control-console/src/App.css
apps/control-console/src/main.tsx
```

要求：

- 页面结构遵循 `docs/09-control-console/00-page-structure.md`。
- 不堆积业务逻辑到 `App.tsx`，复杂逻辑拆入 features/hooks。
- 保留 `/health` 状态展示，但不让健康检查替代任务主流程验证。
- 中文 UI 文案清晰标注 M2/M3 边界，例如“当前未接入自动 Agent”。

### 6.8 测试与验证

至少执行：

```powershell
cd modules/platform-api
$env:CLOUDHELM_DATABASE_URL='postgresql+psycopg://cloudhelm:cloudhelm_dev@127.0.0.1:15432/cloudhelm'
uv run pytest

cd ..\..\apps\control-console
npm.cmd run build
```

建议补充：

- 前端 API client 单元测试。
- 使用浏览器或 Playwright 验证：创建项目 -> 创建任务 -> 查看详情 -> 暂停/恢复/取消 -> 时间线更新。
- 若暂不引入自动化浏览器测试，必须在 `PROJECT_PROGRESS.md` 写明人工验证步骤、输入、预期和实际结果。

## 7. 完成后的同步动作

M3 所有任务完成后必须：

1. 更新 `docs/14-roadmap/03-implementation-milestone-flow.md`，将 M3 下所有任务打钩。
2. 更新 `PROJECT_PROGRESS.md`，记录创建或修改的文件、验证命令、失败修复和遗留风险。
3. 根据下一个未完成阶段 M4 重写 `PROJECT_PLAN.md`。
4. 同步 `README.md`、`apps/control-console/README.md`、`docs/09-control-console/` 和必要的 API 使用说明。
5. 如提升版本到 `0.2.1`，同步所有版本字段并说明版本影响。

## 8. M3 完成判定

只有全部满足才算 M3 完成：

- 控制台能从真实 API 加载和创建 Project。
- 控制台能从真实 API 加载、创建、暂停、恢复、取消 Task。
- 控制台能展示真实 Task Detail、Requirement、Technical Design、Timeline、ToolCall、Approval 数据。
- 控制台没有静态假任务、假 AgentRun、假 ToolCall 或假审批。
- 后端 `uv run pytest` 通过。
- 前端 `npm.cmd run build` 通过。
- 必要的人工或自动化浏览器验证已记录。
- `PROJECT_PROGRESS.md` 和总排期流程已同步。

## 9. 风险与处理

- 如果后端 API 未启动：前端必须显示错误态和重试入口，不得静默显示假数据。
- 如果 M2 SSE 不能实时推送：记录为 M2/M3 边界，可用轮询或重连刷新，但必须说明原因。
- 如果前端状态逻辑开始膨胀：优先拆分 hooks 和 feature 组件，不引入过重状态库。
- 如果需要新增依赖：先说明用途、替代方案和维护成本，写入对应 `package.json` 和 lock 文件。
- 如果验证失败：不得把 M3 任务打钩，必须修复后回归测试。
