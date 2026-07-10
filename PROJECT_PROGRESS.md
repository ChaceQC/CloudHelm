# PROJECT_PROGRESS.md

本文件记录 CloudHelm 每次设计、实现、测试、部署和范围调整的进度。每完成一个可验证小步后必须更新。

## 2026-07-10（M1-M5 二次审计启动）

### 已完成

- 按用户要求重新从 `AGENTS.md`、M1-M5 总排期、模块契约、Agent/Tool 契约、数据设计、事件设计和安全边界建立审计基线，不沿用上一轮“已完成”结论。
- 重跑当前基线：Tool Gateway `20 passed, 1 skipped`、Agent Runtime `8 passed`、Orchestrator `3 passed`、Platform API `32 passed, 1 warning`、控制台 `4 passed` 且生产构建成功。
- 使用 `alembic check` 发现 ORM metadata 与已应用迁移存在注释差异，证明现有测试门禁仍不能覆盖全部 schema 一致性。
- 发现需要修复的实现问题：资源版本未递增、旧版本仍可评审、分页漏最新数据、未处理异常缺统一错误、Tool Gateway 工作区根目录由调用方任意指定、ToolCall 审计未持久化和脱敏、控制台 Project/Task 请求竞态及 SSE 无真正重连。
- 重写 `PROJECT_PLAN.md` 为本次 M1-M5 二次审计与修复的详细执行计划；本阶段不进入 M6。

### 进行中

- 正在按计划先修复数据/API/状态不变量，再修复 Tool Gateway 和控制台。

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
