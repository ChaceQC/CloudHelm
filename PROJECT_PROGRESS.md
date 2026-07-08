# PROJECT_PROGRESS.md

本文件记录 CloudHelm 每次设计、实现、测试、部署和范围调整的进度。每完成一个可验证小步后必须更新。

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
