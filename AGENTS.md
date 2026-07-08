# Repository Guidelines

本文件是 CloudHelm 毕业设计仓库的开发与文档协作约束。后续进行设计书维护、代码实现、重构、测试、部署配置和答辩材料整理时，都应优先遵守本文件。

## 1. 基本要求

- 文件读写和终端输入输出统一使用 UTF-8。
- 修改文件优先使用 `apply_patch`。
- 开发环境默认为 Windows；远端演示/部署环境默认为 Linux + Docker Compose。
- 面向用户的说明文字、README、项目文档、答辩材料和代码注释默认使用中文；命令、变量名、API 字段、协议名、第三方产品名和行业通用术语可保留英文。
- 新增目录名、包名、环境变量名、接口路径和真实存储文件名优先使用英文、数字、短横线或下划线。既有中文设计书文件名保持不变。
- 所有实现必须服务于 `云舵 CloudHelm 毕设设计书.md` 和 `docs/15-detailed-design/00-mvp-scope-and-cutline.md` 的 MVP 边界。
- 必须维护 `PROJECT_PLAN.md` 和 `PROJECT_PROGRESS.md`。其中 `PROJECT_PLAN.md` 不是总项目规划，而是“下一步要落实的详细执行计划”；如果当前没有进入具体实施步骤，可以暂不创建。`PROJECT_PROGRESS.md` 必须持续记录每次设计、实现、测试、部署或范围调整。
- 不要把临时方案伪装成最终方案；临时实现必须在文档、进度记录或最终说明中标明原因和后续处理。

## 2. 版本号控制

- 项目版本号采用 `X.Y.Z` 语义化版本格式。
- Git tag 和发布名称采用 `vX.Y.Z` 格式，例如 `v0.1.0`。
- 毕设开发期和未稳定版本统一使用 `v0.y.z`。
- 答辩可演示的稳定版本可以标记为 `v1.0.0`。
- 破坏性变更提升 `X`，新增兼容能力提升 `Y`，修复、文档补充、测试补充和小型重构提升 `Z`。
- 修改 API 契约、数据库 schema、工具 schema、Agent 职责、部署方式或安全策略时，必须同步说明版本影响。
- 如果后续创建 `VERSION` 文件，则该文件必须只保存当前版本号，例如 `0.2.0`，并与 Git tag 保持一致。

## 3. 项目结构

- `云舵 CloudHelm 毕设设计书.md`：总体设计书，作为最高层设计来源。
- `docs/00-project/`：项目定位、目标和参考资料。
- `docs/01-architecture/`：系统架构、本地/远端边界、核心原则。
- `docs/02-tech-stack/`：技术栈、MVP 组合、远端运维采集链路。
- `docs/03-modules/`：计划中的 Monorepo 模块边界。
- `docs/04-agents/`：多 Agent 角色、职责、状态机和结构化输出。
- `docs/05-tool-layer/`：Tool Gateway、MCP 工具、风险等级和审批规则。
- `docs/06-workflows/`：开发到 PR、部署、CI 修复、告警分析和远程接管流程。
- `docs/07-data/`：核心实体和数据库表设计。
- `docs/08-api/`：Task、Agent Run、Tool Call、Approval、Deployment、Monitoring 等 API。
- `docs/09-control-console/`：桌面端页面结构和关键交互。
- `docs/10-security/`：权限边界、安全策略和审计要求。
- `docs/15-detailed-design/`：MVP 裁剪线、模块契约、API、数据、事件、部署观测和验收矩阵。
- `informations/`：实现前检索到的官方文档、开源项目资料、技术选型依据和命令来源归档，按阶段、主题或来源分层保存。

开始编码后，源码目录应与 `docs/03-modules/00-module-map.md` 保持一致，例如 `apps/control-console`、`modules/platform-api`、`modules/orchestrator`、`modules/agent-runtime`、`modules/tool-gateway`。

## 4. Git 与提交

- 项目必须使用 Git 管理，稳定主分支固定为 `main`，开发分支固定为 `dev`。
- 所有设计、文档、代码、配置和测试改动只能在 `dev` 或从 `dev` 拉出的功能分支上进行；禁止直接在 `main` 开发、修改、提交或积累未提交改动。
- `main` 只接收已经在 `dev` 验证通过的合并；合并前必须确认验证命令、`PROJECT_PROGRESS.md`、总排期打钩和 `PROJECT_PLAN.md` 下一阶段计划均已同步。
- 如果发现根目录没有 `.git`，应先执行 `git init -b main`（旧版 Git 可用 `git init` 后 `git branch -M main`），再立即创建并切换到 `dev`：`git switch -c dev`；初始化和切换命令必须记录到 `PROJECT_PROGRESS.md`。
- 每次开始工作前必须执行 `git branch --show-current` 和 `git status --short`；如果当前分支是 `main`，必须先切换到 `dev` 或从 `dev` 创建功能分支后才能修改文件。
- 日常开发默认在 `dev` 进行；需要隔离较大功能时，从 `dev` 创建功能分支，例如 `feature/m2-data-api`，验证后先合并回 `dev`，再由 `dev` 合并入 `main`。
- 提交前必须检查 `git status` 和 `git diff`，避免混入无关改动。
- 每完成一个可验证小步就提交，不要累计大量无关修改。
- commit message 使用中文说明；可以保留 `docs:`、`feat:`、`fix:`、`refactor:`、`test:`、`chore:` 等英文类型前缀。
- 示例：`docs: 补充版本号控制规则`、`feat: 新增任务状态机原型`。
- 禁止提交 `.env`、密钥、证书私钥、依赖目录、构建产物、日志、临时备份文件和真实服务器凭据。
- 依赖锁文件、数据库迁移、接口契约、示例配置和部署脚本应随相关代码一起提交。
- `.gitignore` 必须在首次提交前创建或更新，至少覆盖 `.env`、依赖目录、构建产物、日志、缓存、临时文件和系统/编辑器文件。
- 每个里程碑建议使用独立功能分支，例如 `feature/m1-foundation`、`feature/m2-data-api`；紧急文档修正可使用 `docs/...` 分支，但都必须从 `dev` 拉出并先合并回 `dev`。
- 每次提交前必须完成与改动范围匹配的验证，并把关键命令和结果写入 `PROJECT_PROGRESS.md`；验证失败不得把对应任务标记为完成。
- 提交粒度应按“可验证小步”划分，例如目录骨架、后端 `/health`、前端控制台、共享契约、数据库迁移、API 分组分别提交。
- 提交前必须复查 `git diff --stat` 和关键文件 diff；发现无关格式化、构建产物、缓存或真实凭据时，必须先移除再提交。
- 从 `dev` 合并到 `main` 前必须再次执行完整验证，并检查 `git log --oneline --decorate --graph --max-count=20`、`git status --short` 和 `git diff main..dev --stat`。
- GitHub 远端默认命名为 `origin`；如用户未另行指定，仓库名使用项目名 `CloudHelm`，可公开或私有必须按用户明确要求执行。
- 创建或关联 GitHub 远端后，必须执行 `git remote -v` 确认地址，并把仓库 URL、可见性和默认推送分支记录到 `PROJECT_PROGRESS.md`。
- 每次本地提交后必须同步 push 当前开发分支：`git push -u origin dev`（首次）或 `git push origin dev`（后续）；不得只本地提交而忘记同步远端。
- `main` 只能由已验证的 `dev` 合并产生；合并到 `main` 后必须执行 `git push origin main`，并确认 `dev` 与 `main` 在远端都存在。
- push 前必须确认当前分支不是 `main`，除非正在执行已验证的合并发布；常规开发 push 只允许推送 `dev` 或从 `dev` 拉出的功能分支。
- push 前必须确认 `.gitignore` 和 `.gitattributes` 已覆盖依赖目录、构建产物、缓存、临时文件、编辑器目录和行尾策略，避免把无关文件或 CRLF 转换风险同步到 GitHub。
- push 后必须执行 `git status --short` 和必要的 `git log --oneline --decorate --max-count=5`，确认工作区状态、提交位置和远端分支同步结果。
- 如果当前环境无法执行 Git 命令、仓库尚未初始化或用户暂不允许提交，必须在 `PROJECT_PROGRESS.md` 和最终说明中明确记录原因、已验证状态和建议的后续 Git 操作。
- 不允许用一次大提交掩盖未验证改动；不允许在未检查 diff 的情况下提交；不允许把临时方案、阻塞项或未完成能力写成“已完成”提交。

## 5. 架构边界

- `apps/control-console`：桌面端控制台，负责需求输入、任务视图、diff、审批、日志、监控面板和远程接管。
- `modules/platform-api`：统一 API 服务，只负责接口、鉴权、DTO、请求校验和编排入口。
- `modules/orchestrator`：核心流程状态机，负责“需求 -> 设计 -> 实现 -> 测试 -> PR -> 部署 -> 监控”。
- `modules/agent-runtime`：Requirement、Planner、Architect、Coder、Tester、Reviewer、Security、Release / Deploy、SRE 等 Agent 实现。
- `modules/tool-gateway`：所有工具调用的统一入口，负责权限、审批、审计、限流和 MCP 路由。
- `modules/sandbox-runner`：本地隔离开发和测试环境，不作为远端运维对象。
- `modules/remote-agent`、`modules/deployment-controller`、`modules/monitoring-collector`：负责远端 demo/staging 部署、状态回传、日志、指标和告警。

不要把业务规则堆在 API 路由、前端页面或 Agent prompt 中；复杂逻辑应沉到 service、workflow、tool 或 policy 层。

## 6. 技术选型与实现原则

- 写代码前必须先查阅相关设计文档、接口契约、模块说明和当前 `PROJECT_PLAN.md`，不得凭印象或猜测实现。
- 实现涉及 Agent、Tool Gateway、CI/CD、部署、监控、安全、远程控制等复杂能力时，必须参考设计书中列出的相关开源项目或成熟项目实践，再结合本项目 MVP 边界落地。
- 参考开源项目时，只借鉴架构、接口形态、流程和工程实践；不得直接复制不兼容代码或引入不清楚许可证的实现。
- 搜索到的官方文档、开源项目资料、技术选型依据和命令来源，可按阶段、主题或来源层级保存到 `informations/`，例如 `informations/m1-foundation/official-references.md`、`informations/m5-tool-gateway/reference-projects.md`。
- `informations/` 中只保存链接、检索日期、摘要、适用阶段、取舍结论和少量必要摘录；不得保存真实密钥、账号、Cookie、服务器地址、许可证不明的大段代码或第三方文档全文。
- 如果某阶段实现依赖外部资料，`PROJECT_PLAN.md` 应列出对应 `informations/` 归档文件或官方链接，完成后在 `PROJECT_PROGRESS.md` 记录已查阅资料和采用结论。
- 如果设计文档、开源实践和当前实现计划冲突，必须先更新 `PROJECT_PLAN.md` 或相关 `docs/` 文档，再开始编码。
- 不得为了赶进度盲目实现“看起来能跑”的临时代码；没有文档依据、接口依据或成熟实践依据的核心实现必须先补设计。
- 优先使用成熟、现成、可维护的开源方案和框架能力，不要为了展示技术而重复造轮子。
- 优先使用语言和框架自带特性，例如 Python 标准库、Pydantic、FastAPI dependency、SQLAlchemy session、TypeScript 类型系统、React hooks、TanStack Query 等。
- 只有当现成方案无法满足 MVP 需求、引入成本明显过高或会破坏架构边界时，才允许自研实现。
- 自研通用组件前，必须先检查是否已有标准库、框架内置能力、项目内公共模块或设计书推荐方案可用。
- 不要自研加密算法、权限框架、任务队列、日志系统、HTTP client、ORM、测试框架、包管理流程或 Docker 编排方案。
- 新增依赖必须说明用途和替代方案，避免引入维护成本高、无人维护或与目标部署环境不兼容的库。
- 简单需求优先用简单实现；不要把 MVP 功能过度抽象成插件市场、多租户平台或生产级云管系统。
- 缺少工具或依赖时，优先使用项目内、模块内或临时隔离环境安装，尽量不要全局安装。Python 依赖优先使用 `uv`/虚拟环境并落到对应模块；Node 依赖必须写入对应 `package.json` 和 lock 文件；CLI 工具优先使用 `npx`、项目 devDependency、局部 `.venv` 或 `tools/` 目录。
- 不得为了方便污染系统全局环境；确实必须全局安装时，必须先说明原因、影响范围和卸载方式，并记录到 `PROJECT_PROGRESS.md`。
- 每个模块应尽量拥有可复现的独享依赖环境，依赖版本、安装命令和启动命令必须写入 README 或对应文档。
- 写某个功能时必须正常、完整实现功能，不得用 mock、假数据、固定返回、空实现、TODO、跳过校验、跳过错误处理、只写前端不接后端、只写接口不落库等模拟或简化方式代替真实功能。
- 测试代码可以使用 mock/stub/fake，但必须只存在于 `tests` 或测试夹具中，不得进入生产代码路径。
- 如果某项能力因外部条件暂时无法完整实现，必须先在 `PROJECT_PROGRESS.md` 记录阻塞原因，并把该能力从“已完成”改为“阻塞”或“待实现”，不得标记为完成。

## 7. 代码结构要求

后续开始实现时，必须按 Monorepo 思路组织代码，不要把前端、后端、Agent、工具、部署脚本混在同一目录。

推荐结构：

```text
apps/
  control-console/        # Tauri + React 桌面端
modules/
  platform-api/           # FastAPI API 服务
  orchestrator/           # 工作流状态机
  agent-runtime/          # Agent 实现、prompt、模型适配
  tool-gateway/           # 工具入口、权限、审批、审计
  toolservers/            # MCP 工具服务
  sandbox-runner/         # Docker sandbox 执行
  deployment-controller/  # 部署计划、健康检查、回滚计划
  remote-agent/           # 远端主机轻量 Agent
  monitoring-collector/   # 日志、指标、告警采集
  policy-engine/          # 风险等级和权限策略
packages/
  shared-contracts/       # OpenAPI、事件 schema、工具 schema、共享类型
infra/                    # Docker Compose、CI、监控、部署配置
examples/                 # sample repo、演示 issue、演示脚本
tests/                    # 跨模块集成测试和 E2E 测试
informations/             # 官方文档、开源项目资料和阶段性调研摘要
```

### 7.1 注释规范

所有新增代码都必须有必要注释，注释规范参考华为代码注释风格，强调“准确、必要、同步、说明意图”：

- 文件、类、公共函数、公共组件、公开 API、复杂 workflow、复杂 policy 必须写注释。
- 注释应说明“为什么这样做、输入输出、边界条件、副作用、异常情况”，不要重复描述代码表面含义。
- Python 使用 docstring 描述模块、类和公共函数；TypeScript/React 使用 JSDoc 或清晰的行内注释。
- 对外接口、跨模块接口、工具 schema、事件 schema 必须说明参数、返回值、错误码、权限、审计字段和示例。
- 修改代码时必须同步更新相关注释，禁止留下过期注释。
- TODO 必须写明原因、负责人或后续动作，例如 `TODO: 补充真实 Gitea PR 集成，当前由 deployment milestone 阻塞`。
- 不允许用注释解释错误设计；如果需要大量注释解释混乱逻辑，应优先重构。

### 7.2 后端代码分层

`modules/platform-api` 和其他 Python 后端模块应保持分层清晰：

- `api`：路由、请求参数、依赖注入、响应模型。
- `schemas`：Pydantic DTO、请求/响应结构。
- `services`：业务用例和领域规则。
- `repositories`：数据库访问。
- `models`：ORM 模型。
- `workflows`：状态机、任务推进、重试和补偿逻辑。
- `providers` 或 `adapters`：外部系统适配，例如 Git、Docker、Prometheus、Loki、SSH、LLM。
- `policies`：权限判断、风险等级、审批规则。
- `tests`：单元测试和集成测试。

路由函数不得直接写数据库访问、远程命令、LLM 调用或复杂业务判断。

### 7.3 前端代码分层

`apps/control-console` 应按业务能力拆分：

- `features/projects`：项目列表、仓库状态。
- `features/tasks`：任务看板、任务详情、Agent Timeline。
- `features/design-review`：需求规格、ADR、OpenAPI、DB schema 审查。
- `features/diff-viewer`：变更文件、diff、review comment。
- `features/approvals`：审批卡片、拒绝、暂停、接管。
- `features/remote-ops`：远端状态、日志、终端接管。
- `features/monitoring`：指标、告警、incident 分析。
- `shared/components`、`shared/api`、`shared/types`：通用 UI、API client、共享类型。

页面文件只负责组合，不堆积请求、状态机、表单校验和复杂业务逻辑。

### 7.4 Agent 与 Tool 结构

- 每个 Agent 必须有独立目录或文件，包含职责说明、输入结构、输出结构和允许工具列表。
- Agent 输出必须尽量结构化，优先使用 JSON schema / Pydantic model / typed contract。
- Tool Server 的每个工具必须声明：工具名、参数 schema、返回 schema、风险等级、是否需要审批、审计字段。
- Tool Gateway 是唯一工具入口；Agent 不得绕过 Tool Gateway 直接执行高风险命令。

### 7.5 API 与接口文档要求

凡是需要其他模块调用，或需要对外提供的 API、事件、工具、SDK、CLI、WebSocket、配置文件格式，都必须在 `docs/` 下提供详细说明文档。

接口文档至少包含：

- 接口用途和适用场景。
- 调用方与提供方。
- 路径、方法、认证方式和权限要求。
- 请求参数、响应结构、错误码、分页/过滤/排序规则。
- 事件名称、状态流转、幂等性、重试策略和超时策略。
- 风险等级、是否需要审批、审计字段。
- 真实调用示例和典型失败示例。
- 版本兼容性和变更记录。

API 文档优先放在 `docs/08-api/`，Agent/Tool 契约放在 `docs/15-detailed-design/02-agent-tool-contract.md` 或对应细分文件，模块间契约放在 `docs/15-detailed-design/01-module-contracts.md`。

### 7.6 文件体量与拆分

- 普通源码文件建议不超过 300 行。
- 复杂 service、workflow、React 页面超过 400 行时必须评估拆分。
- 单个函数建议不超过 60 行。
- 一个文件只承担一个主要职责。
- 同类逻辑复制 3 次以上，应抽取公共函数、类、hook、组件、adapter 或 policy。
- 允许较长的文件：数据库迁移、生成文件、schema 集合、设计文档和答辩材料。

### 7.7 命名与配置

- Python 文件、目录和模块名使用 `snake_case`。
- TypeScript/React 组件文件可使用 `PascalCase.tsx`，普通工具文件使用 `camelCase.ts` 或 `kebab-case.ts`，同一模块内保持一致。
- API 路径使用小写短横线，例如 `/api/tasks/{task_id}/agent-runs`。
- 环境变量使用大写下划线，例如 `CLOUDHELM_DATABASE_URL`。
- 端口、域名、数据库连接、模型供应商、Token、远端主机、CORS、Trusted Host、部署路径等环境相关配置必须放在配置文件或环境变量中，不得硬编码在业务代码里。

## 8. 测试与验证

当前仓库主要是文档，可使用：

- `Get-ChildItem docs -Recurse`：检查文档结构。
- `Select-String -Path docs/**/*.md -Pattern "MVP"`：检索设计内容。
- `git diff -- *.md`：提交前检查 Markdown 修改。

后续实现代码后，根据变更范围执行验证：

- 前端：运行 lint、typecheck、build 或 E2E。
- 后端：运行相关 `pytest`。
- Agent/工具：验证结构化输出、工具调用记录、风险等级和审批流。
- 部署：检查 Docker Compose、环境变量、远端 `/health` 和日志回传。
- 安全：检查敏感信息、权限边界、审计日志和公网暴露端口。

如果某项验证无法执行，必须在最终说明中写明原因和验证边界。

## 9. 文档同步

以下变化必须同步更新设计文档：

- MVP 范围、阶段计划或验收标准变化。
- 模块职责、目录结构或 API 契约变化。
- 数据库表、事件 schema、工具 schema 变化。
- 对外 API、跨模块接口、CLI、WebSocket、配置文件格式变化。
- Agent 职责、审批策略、风险等级变化。
- 部署方式、监控指标、安全边界变化。
- 启动方式、测试方式、演示流程或答辩材料变化。
- 新增功能完整实现状态、阻塞原因或验证方式变化。

文档修改应优先更新对应章节文件，再视情况同步总设计书或 `docs/README.md`。

`docs/14-roadmap/03-implementation-milestone-flow.md` 是项目总排期流程和里程碑打钩清单。每完成一个可验证任务或阶段后，必须同时完成以下动作：

- 确认对应任务或阶段的完成判定已经满足。
- 将总排期流程中的对应复选框从 `[ ]` 改为 `[x]`。
- 更新 `PROJECT_PROGRESS.md`，记录完成内容、验证方式、遗留风险和下一步。
- 根据下一个未完成 M 阶段重写或更新 `PROJECT_PLAN.md`。

`PROJECT_PLAN.md` 只用于记录下一步要落实的详细执行计划，不用于重复保存总项目规划或长期路线图。它应在准备开始某个具体实施阶段前创建或更新，内容至少包含：

- 本阶段目标。
- 需要修改或创建的文件。
- 具体任务拆分。
- 依赖的设计文档或接口文档。
- 写代码前必须查阅的开源项目、官方文档或成熟实践。
- 预检步骤和环境检查命令。
- 每个子任务的建议目录结构、实现要求、命令示例和完成后需要打钩的位置。
- 验证方式。
- 完成判定。
- 风险、阻塞条件和处理方式。

后续每个阶段的 `PROJECT_PLAN.md` 都必须达到当前 M1 计划的详细程度，不能只写粗略任务列表。计划必须具体到文件、目录、命令、接口文档、验证方式和完成判定，确保可以直接按步骤执行。

阶段完成后，应把结果写入 `PROJECT_PROGRESS.md`，再根据下一阶段目标重写或更新 `PROJECT_PLAN.md`。

`PROJECT_PROGRESS.md` 必须在每次可验证改动后更新，至少包含：

- 当前日期。
- 已完成事项。
- 正在进行的事项。
- 阻塞问题或风险。
- 下一步具体任务。
- 涉及的主要文件或模块。
- 已执行的验证方式。

推荐格式：

```markdown
## 2026-07-08

### 已完成

- 补充 Agent 协作状态机设计。

### 进行中

- 细化 Tool Gateway 审批流程。

### 阻塞与风险

- 待确认远端 demo 服务器配置。

### 下一步

- 编写部署闭环验收脚本。

### 验证

- 已检查 `docs/15-detailed-design/05-workflow-state-events.md`。
```

不能只写“继续完善”“后续优化”等模糊下一步。

## 10. 安全要求

- Agent 默认不得拥有生产权限，高风险操作必须人工审批。
- 远端命令、部署、回滚、日志查看和人工接管必须写入审计记录。
- 不得在代码、文档示例、日志或截图中写入真实密钥、Token、Cookie、数据库连接串、服务器私钥或公网管理入口。
- 公网演示时只暴露必要入口，不得直接暴露数据库、Redis、内部调试端口、私有文件目录或未鉴权管理接口。
- L3/L4 风险操作必须经过 Tool Gateway、Policy Engine 和 Approval 记录。
