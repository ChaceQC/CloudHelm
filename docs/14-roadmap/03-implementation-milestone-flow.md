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
|M7|CI/CD 与远端部署闭环|审批后部署 sample repo 到远端 staging/demo 并健康检查|M6|
|M8|远端监控、告警与 SRE 分析|采集日志指标告警，生成 incident 分析和 runbook 建议|M7|
|M9|审批、安全与可观测性加固|完善 L3/L4 审批、安全扫描、审计、trace、成本统计|M5-M8|
|M10|答辩演示与最终验收|完成演示脚本、验收矩阵、截图、报告和最终版本|M1-M9|

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

完成判定：输入真实需求后，系统能生成结构化需求、技术方案和开发计划，并进入审批状态。

### M5 Tool Gateway 与本地工具层

- [ ] 实现 Tool Gateway 参数校验、权限判断、风险等级、限流和审计记录。
- [ ] 实现 Requirement Tool 和 Design Tool。
- [ ] 实现 Repo Tool，支持真实读取和写入 worktree。
- [ ] 实现 Sandbox Tool，支持 Docker sandbox 命令执行、超时和 artifact 收集。
- [ ] 实现 Git Tool，支持 diff、branch、commit。
- [ ] 控制台展示 tool_calls 的工具名、参数摘要、风险等级、状态和输出摘要。

完成判定：Agent 工具调用必须经过 Tool Gateway，且 `tool_calls` 有完整记录。

### M6 本地代码实现、测试与 PR 闭环

- [ ] 准备 `examples/sample-repo-python`，包含 FastAPI `/health`、`/metrics`、pytest 和 Dockerfile。
- [ ] 实现 Scaffold Agent。
- [ ] 实现 Coder Agent，真实修改 sample repo。
- [ ] 实现 Tester Agent，真实运行 pytest 并生成测试报告。
- [ ] 实现 Reviewer Agent，检查 diff 与验收标准。
- [ ] 实现 Security Agent，运行 Semgrep / Trivy / dependency audit。
- [ ] 创建 branch、commit、PR 或等价 PR record。
- [ ] 控制台展示 diff、测试报告、安全扫描、审查结论和 PR 链接/记录。

完成判定：能从功能需求生成真实代码变更、测试报告、审查结论和 PR/等价记录。

### M7 CI/CD 与远端部署闭环

- [ ] 准备远端 Linux staging/demo 主机和 Docker Compose 环境。
- [ ] 实现 Remote Agent 心跳、服务状态上报和日志流。
- [ ] 实现 Release / Deploy Agent 的 release plan、部署审批、部署执行和健康检查。
- [ ] 实现 Deployment Controller。
- [ ] 实现 Deploy Tool 和 Remote Control Tool。
- [ ] 渲染 compose 文件和 `.env`，执行真实远端部署。
- [ ] 控制台展示远端环境、部署版本、服务状态和健康检查结果。

完成判定：审批后能把 sample repo 部署到远端 staging/demo，且 `/health` 成功。

### M8 远端监控、告警与 SRE 分析

- [ ] 部署或接入 Prometheus、Loki、Alertmanager 或设计书允许的等价真实采集链路。
- [ ] 实现 Monitoring Tool：query_metrics、search_logs、list_alerts、get_recent_deployments。
- [ ] 实现 ProjectAlert / Incident 数据流。
- [ ] 实现 SRE Agent 告警分析。
- [ ] 生成 runbook proposal。
- [ ] 对重启服务、回滚版本等动作接入审批。

完成判定：远端异常能触发告警或 incident，SRE Agent 能基于日志、指标和部署记录给出分析与建议。

### M9 审批、安全与可观测性加固

- [ ] 完善 Approval API 和审批面板。
- [ ] 完成 L3/L4 风险操作审批、拒绝、暂停、接管记录。
- [ ] 接入 Semgrep / Trivy / dependency audit 的报告展示。
- [ ] 完善 audit log、event log、tool call trace。
- [ ] 接入平台自身指标和基础 dashboard。
- [ ] 实现 token/cost 统计。
- [ ] 检查公网暴露面和敏感日志。

完成判定：高风险操作必须审批，安全扫描、审计、指标和成本信息可查看。

### M10 答辩演示与最终验收

- [ ] 编写完整 E2E 演示脚本。
- [ ] 按 `docs/15-detailed-design/07-testing-acceptance-matrix.md` 执行验收。
- [ ] 归档 requirement、design、diff、test report、security report、deployment result、incident analysis。
- [ ] 准备截图、录屏、测试报告和答辩讲解材料。
- [ ] 检查 `docs/14-roadmap/02-mvp-acceptance-and-extension.md` 的 21 项 MVP 验收点。
- [ ] 标记最终版本，例如 `v1.0.0`。

完成判定：完整 E2E 演示可复现，验收证据完整，最终版本可用于答辩。

## 4. 当前下一步

当前 M0、M1、M2、M3、M4 已完成。下一步执行 M5：Tool Gateway 与本地工具层。详细执行计划见根目录 `PROJECT_PLAN.md`。
