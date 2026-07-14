# M6 本地代码实现、测试与等价 PR 闭环细化设计

## 1. 目标与边界

M6 在已审批的最新版 `DevelopmentPlan` 上执行一个受控 sample repo 的本地
开发闭环：

```text
Planning
  -> Scaffolding
  -> Implementing
  -> Testing
  -> Reviewing
  -> SecurityScanning
  -> ReadyForPR
  -> PullRequestCreated
```

`PullRequestCreated` 表示已经生成真实本地 branch、commit、patch artifact 和
`provider=local` 的等价 PR record。它不是远端 Git PR，也不是 Task 终态。
`WaitingMergeApproval -> Deploying -> Monitoring -> Done` 留给 M7/M8。

M6 不执行远端 push、SSH、部署、服务重启或生产操作。

## 2. Sandbox 决策

M6 继续使用受控本地 `subprocess`，不把 Docker daemon 设为必需前置条件。

允许边界：

- workspace 根目录由 Platform API 根据 Task、Project 和配置绑定，API 请求与
  模型工具参数不能传入任意本机路径。
- 只执行命令数组，不经过 shell。
- pytest、Bandit、pip-audit 和 Git 使用独立正向 command profile。
- 环境变量使用白名单；移除凭据、代理、用户级 Python/Node 注入变量。
- 每种 profile 有独立超时和输出上限；超时终止进程树。
- 工具结果、stdout、stderr 和参数在持久化前脱敏。
- `.env`、私钥、`.git`、依赖目录、缓存和构建产物不能被 Repo Tool 读取或写入。

已知限制：

- 本地进程没有 Docker 的 CPU、内存、PID、只读挂载与内核级网络隔离。
- `pip-audit` 可能访问漏洞数据源；不可达时报告基础设施阻塞。
- Docker 一次性 sandbox 作为 M7 前增强：使用只读 source、可写 worktree、
  `--network none`（不需要联网的步骤）、CPU/内存/PID 限制、超时和 `--rm`。

## 3. Workspace 与 Scaffold

源 fixture 固定为：

```text
examples/sample-repo-python/
```

Platform API 不直接在该目录修改。Scaffold 步骤通过 Tool Gateway：

1. 把 fixture 复制到 `CLOUDHELM_M6_WORKSPACE_ROOT/<task_id>/repo`。
2. 排除 `.git`、`.venv`、缓存、构建产物和报告目录。
3. 初始化独立 Git 仓库、`main` 分支和 baseline commit。
4. 返回受控 workspace key、base branch、baseline commit 和文件清单。

相同 Task 的重复 Scaffold 调用使用同一幂等键；已存在且 baseline 一致时返回
原结果，不重新覆盖 Coder 产生的文件。

## 4. Agent 与会话

普通角色共八类：

- Requirement
- Architect
- Planner
- Scaffold
- Coder
- Tester
- Reviewer
- Security

共同约束：

- 共享唯一 Task root `agent_conversations`。
- Base Instructions、`cloudhelm_agent_output_v1` 和模型可见 tools 数组在同一
  root 中保持稳定。
- 角色权限由 `<role_contract>`、Tool Gateway registry 和 Policy 三重限制，
  不通过删除 tools 改变请求前缀。
- workspace/repo root 等服务端参数不进入模型 schema，由 Platform API 注入。
- Responses function tool 暂用 `strict=false`；Tool Gateway 继续使用 Pydantic
  严格校验真实参数。
- 每个 provider tool call 和数据库 ToolCall 保存同一 `provider_call_id`。
- 一个 Agent 步骤可以包含多次 provider 请求和多次工具调用，但最终只增加
  一个逻辑 conversation turn。
- 只有最终结构化输出通过角色 Pydantic schema 后，才提交该 Agent turn。

## 5. 工具循环

```text
AgentRun running
  -> Provider 返回 function_call
  -> Platform API 绑定 workspace 与角色
  -> Tool Gateway 创建/复用幂等 ToolCall
  -> 执行真实文件、命令或 Git 副作用
  -> function_call_output 使用原 call_id 回到 root history
  -> Provider 继续生成 tool call 或最终结构化 JSON
  -> 角色 Pydantic 校验
  -> Artifact / AgentRun / conversation / phase / EventLog 原子提交
```

稳定 tools 清单按名称排序。M6 至少包含：

- `scaffold.prepare_workspace`
- `repo.list_files`
- `repo.read_file`
- `repo.search_text`
- `repo.write_file`
- `sandbox.run_command`
- `test.run_pytest`
- `security.run_bandit`
- `security.run_pip_audit`
- `git.status`
- `git.create_branch`
- `git.diff`
- `git.commit`
- `git.format_patch`

模型能看到完整工具声明，但 Gateway 按 `agent_type` 拒绝越权调用。

## 6. 分阶段行为

### 6.1 Start

前置条件：

- Task 不处于 paused/failed/done/cancelled。
- 最新 TechnicalDesign 为 approved。
- 最新 DevelopmentPlan 关联该设计且为 approved。
- Project 映射到配置中的 local sample repo。

成功后只执行 `Planning -> Scaffolding`，Task 设为 running，并写
`LocalDevelopmentStarted` 与 `TaskPhaseChanged`。

### 6.2 Scaffold

Scaffold Agent 生成受控 workspace 请求；Tool Gateway 创建 fixture 副本和
baseline commit。成功后进入 `Implementing`。

### 6.3 Coder

Coder 基于真实 Requirement AC、TechnicalDesign、DevelopmentPlan、当前
workspace 文件和失败反馈提出结构化文件/Git 工具请求：

- 创建 `codex/task-<short-id>` 分支。
- 写入或修改显式文件。
- 读取 `git.status`、changed files、stat 和 patch。
- 生成非空 `diff_patch` Artifact。

Coder 最终输出引用真实 ToolCall，不直接声明未执行结果。成功后进入 Testing。

### 6.4 Tester

Tester 使用 `test.run_pytest` 执行：

```text
uv run pytest -q --junitxml=.cloudhelm/artifacts/junit.xml
```

保存 TestReport 与 JUnit Artifact。退出码、JUnit 统计或报告解析任一不一致都
视为测试未通过，并回到 Implementing；测试基础设施错误则暂停在 Testing。

### 6.5 Reviewer

Reviewer 读取当前 patch、Requirement AC 和通过的 TestReport：

- 每条 AC 必须有 `passed/failed/not_covered` 映射。
- issue 包含 severity、file、line、message 和建议。
- 只有 verdict 为 approved 且 `proceed_to_security=true` 才进入
  SecurityScanning。
- changes_requested 回到 Implementing。

### 6.6 Security

Security 使用真实 Bandit 与 pip-audit 结果生成 SecurityReport：

- scanner 状态区分 succeeded、findings、unavailable、failed。
- finding 保存规则、文件/依赖、严重级别、说明和阻断标记。
- 工具缺失、输出损坏或漏洞源不可达返回 partial/blocked。
- blocking finding 回到 Implementing；非阻断或明确 partial 风险由报告保留，
  只有服务层允许的 non-blocking 结论进入 ReadyForPR。

### 6.7 Git 与本地 PR record

ReadyForPR 门禁再次读取同一 Task 的：

- 非空 diff patch。
- 通过的 TestReport。
- approved ReviewReport。
- non-blocking SecurityReport。

之后：

1. `git.commit` 只提交 changed files 显式列表。
2. 获取 commit SHA、base/head、changed files 和 diff stat。
3. `git.format_patch` 生成 commit patch Artifact。
4. 创建唯一 `provider=local` 的 PullRequestRecord，`url=null`。
5. 阶段进入 `PullRequestCreated`，Task 保持 running，等待 M7 合并/部署流程。

## 7. Artifact

Artifact 文件保存在 `CLOUDHELM_ARTIFACT_ROOT` 下，数据库只保存相对
`storage_key`。API：

- 列表返回元数据和 `artifact://<id>`。
- 详情通过 `preview.kind=text/json` 返回受限长度的 `text` 或
  `json_value`，并携带 `truncated` 和 `bytes_returned`。
- 不返回 `storage_key`、workspace root 或任意绝对路径。
- 每个 Artifact 使用 Task 级幂等键、SHA-256 和大小校验。

类型至少包括：

- `workspace_manifest`
- `implementation_report`
- `diff_patch`
- `test_report`
- `junit_xml`
- `review_report`
- `security_report`
- `format_patch`

## 8. 数据库与幂等

新增 `artifacts`、`pull_request_records`，并扩展：

- `agent_runs.workflow_step`
- `agent_runs.attempt`
- `agent_runs.idempotency_key`
- `tool_calls.provider_call_id`
- `tool_calls.provider_item_type`
- `agent_conversations.revision`

幂等规则：

- M6 ToolCall 的 `idempotency_key` 由 Task 范围、workflow step、attempt 和
  provider `call_id` 形成；工具名、风险和规范化参数 hash 作为冲突校验。
- execution recipe 指纹独立按工具名、移除服务端绑定字段后的 Pydantic 规范化
  参数和允许次数计算，不能用新 call_id 绕过未批准参数或超额调用。
- 相同幂等键但工具或参数不同返回冲突。
- Artifact 使用 `(task_id, idempotency_key)` 唯一约束。
- PR record 使用 `(task_id, idempotency_key)` 和 `(task_id, commit_sha)`
  唯一约束。
- commit 已成功但 PR record 事务失败时，重试复用已有 commit ToolCall。

## 9. API

```text
GET  /api/tasks/{task_id}/local-development
POST /api/tasks/{task_id}/local-development/start
POST /api/tasks/{task_id}/local-development/run-next
GET  /api/tasks/{task_id}/artifacts
GET  /api/artifacts/{artifact_id}
GET  /api/tasks/{task_id}/pull-request-records
GET  /api/pull-request-records/{record_id}
```

start/run-next 请求只接收 actor 和 reason，不接收 workspace、分支、命令、文件
路径或 artifact root。

## 10. 事件

M6 至少写入：

- `LocalDevelopmentStarted`
- `ScaffoldCompleted`
- `CodePatchGenerated`
- `TestRunStarted`
- `TestRunPassed`
- `TestRunFailed`
- `ReviewCompleted`
- `SecurityScanCompleted`
- `SecurityScanBlocked`
- `ArtifactCreated`
- `BranchCreated`
- `CommitCreated`
- `PullRequestRecordCreated`

所有事件携带 Task ID、阶段、相关 AgentRun/ToolCall/Artifact ID 和可公开摘要，
不携带绝对路径、源码正文或凭据。

## 11. 失败恢复

- Provider/CLI/文件系统基础设施异常：AgentRun failed，Task paused，phase 保持；
  恢复后重试当前步骤。
- 工具调用已经落库但步骤未完成时，保存配对 provider call/output 和
  `<failed_step_context>`，失败 AgentRun 关联该 conversation turn；不生成成功
  角色产物。
- 测试失败、Review 要求修改、安全代码问题：AgentRun succeeded，保存真实报告，
  phase 回到 Implementing。
- pause/cancel 后不创建新 ToolCall；cancel 沿用现有级联关闭 active 记录。
- 外部工具副作用已经发生而最终事务失败时，重试通过 ToolCall/Artifact/PR
  幂等记录恢复，不重复写文件、commit 或 PR record。

## 12. 验收

M6 完成必须同时证明：

- sample repo 可独立运行 `/health`、`/metrics` 和 pytest。
- 八类普通 Agent 的稳定输出协议一致，五个 M6 Agent 有生产实现与测试。
- 同一 Task root 中 call/output `call_id` 配对且顺序有效。
- sample workspace 产生真实 diff、测试、安全、review、branch 和 commit。
- Artifact 与本地 PR record 可由 API 和控制台读取。
- 三种视口、SSE、OpenAPI、JSON Schema、migration、模块测试与静态门禁通过。
