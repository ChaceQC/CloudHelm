# 测试与验收矩阵细化

> 来源：设计书 17、22 章  
> 目的：把 MVP 验收标准转成可执行测试项和答辩演示证据。

## 0. 当前验收边界

- M1-M6 当前闭环止于：Project/Task → Requirement/Design/Plan → 真实本地
  workspace 文件修改 → pytest/JUnit → Review → Bandit/pip-audit → branch/commit
  → `provider=local` 的等价 PR record。
- M7 的 CI、真实远端 PR、Release / Deploy 和 M8 的远端监控/SRE 尚未进入
  M1-M6 完成判定；下文相应测试项标记为“规划”，不得用静态数据或假返回冒充。
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

### 1.1 M7-M8 规划测试矩阵

|模块|规划测试项|计划工具|
|---|---|---|
|sandbox-runner|容器创建、只读挂载、命令超时、CPU/内存/PID/网络限制、清理|pytest + Docker|
|deployment-controller|release plan、Compose 渲染、健康检查、回滚计划与幂等|pytest + Docker Compose|
|remote-agent|heartbeat、service status、日志流、命令审批和断线恢复|pytest + 远端 fixture|
|monitoring-collector|Prometheus/Loki 查询、告警转换、Incident 事件|pytest + 真实观测栈|

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
|IT-011|M7 规划|部署审批|Release / Deploy 请求 staging|ApprovalRequest 风险 L3|
|IT-012|M7 规划|Agent 化远端部署|审批后调用 Deployment Controller|DeploymentHealthy 与可追溯发布记录|
|IT-013|M8 规划|日志查询|控制台打开服务日志|返回远端业务日志|
|IT-014|M8 规划|指标查询|查询 service_up/error_rate|返回真实指标|
|IT-015|M8 规划|告警处理|触发服务不可用|ProjectAlertFired 和 Incident|
|IT-016|M8 规划|SRE 分析|触发 SRE Agent|生成 IncidentAnalysis 和 RunbookProposal|

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

### 3.2 M7-M8 后续演示

真实远端 PR/CI、部署审批、staging 发布、Remote Agent、日志指标、告警和 SRE
分析在对应里程碑完成后追加；当前不纳入 M1-M6 演示通过结论。

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

### 4.1 M7-M8 规划验收映射

|设计书验收点|测试编号|计划证据|
|---|---|---|
|L3 部署动作进入审批|IT-011|ApprovalRequest|
|Release / Deploy Agent 部署到远端 staging/demo|IT-012|DeploymentHealthy|
|Remote Agent 回传心跳和状态|IT-012|Remote status|
|控制台查看远端日志、指标|IT-013、IT-014|Logs / Metrics panel|
|远端异常触发告警|IT-015|Alert / Incident|
|SRE Agent 给出分析|IT-016|IncidentAnalysis|

## 5. 当前失败恢复验证边界

- 已覆盖：进入应用异常处理的 provider/CLI/文件系统错误、事务回滚、Task
  pause/cancel、ToolCall/Artifact/PR record 幂等重试。
- 未覆盖：Platform API 进程在终态持久化前被强制终止。当前
  `pending/running` AgentRun/ToolCall 没有 lease、heartbeat 或 stale reclaim，
  因此不得把“进程 hard crash 后自动恢复”写入 M6 通过结论。
- 在 lease/recovery 实现前，演示和测试应把该场景登记为剩余风险，并通过数据库
  审计与人工处置恢复。

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

M7-M8 完成后再追加 `deployment_result.json`、远端日志/指标证据和
`incident_analysis.md`。
