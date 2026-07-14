# Agent 与 Tool 契约细化

> 来源：设计书 8-9 章、14 章  
> 目的：约束 Agent 输出、工具调用、审批和审计，避免“自然语言驱动不可控执行”。

## 1. AgentRun 标准输入

每个 Agent 运行都应接收统一上下文：

```json
{
  "task": {
    "id": "uuid",
    "project_id": "uuid",
    "title": "string",
    "description": "string",
    "current_phase": "Designing",
    "risk_level": "L1"
  },
  "project": {
    "repo_url": "string",
    "default_branch": "main",
    "stack": ["FastAPI", "React", "PostgreSQL"]
  },
  "artifacts": {
    "requirement_spec_id": "uuid",
    "technical_design_id": "uuid",
    "latest_diff_id": "uuid"
  },
  "constraints": [
    "只能在 sandbox worktree 中修改文件",
    "部署 staging 前必须审批"
  ],
  "available_tools": [
    "repo.read_file",
    "repo.search_text",
    "test.run_pytest"
  ]
}
```

## 2. AgentRun 标准输出

```json
{
  "agent_type": "coder",
  "status": "succeeded",
  "summary": "实现用户注册、登录和个人资料接口",
  "structured_output_type": "coder_agent_output",
  "structured_output": {},
  "tool_requests": [],
  "approval_request": null,
  "next_recommended_phase": "Testing",
  "risks": [],
  "artifacts": []
}
```

字段要求：

|字段|说明|
|---|---|
|agent_type|必须等于当前 Agent 角色|
|status|`succeeded` / `failed` / `needs_clarification` / `needs_approval`|
|summary|给控制台展示的人类可读摘要|
|structured_output_type|用于选择 Pydantic schema|
|structured_output|必须可 JSON Schema 校验|
|tool_requests|需要执行的工具调用请求|
|approval_request|高风险动作的审批说明|
|next_recommended_phase|给 Orchestrator 的下一步建议|
|risks|风险列表|
|artifacts|产物引用|

## 2.1 M4 结构化输出落地

M4 已将以下 schema 落地到共享契约：

|文件|生产者|入库位置|
|---|---|---|
|`packages/shared-contracts/schemas/agents/requirement-agent-output.schema.json`|Requirement Agent|`requirement_specs`、`agent_runs.structured_output_json`|
|`packages/shared-contracts/schemas/agents/architect-agent-output.schema.json`|Architect Agent|`technical_designs`、`agent_runs.structured_output_json`|
|`packages/shared-contracts/schemas/agents/planner-agent-output.schema.json`|Planner Agent|`development_plans`、`agent_runs.structured_output_json`|
|`packages/shared-contracts/schemas/agents/agent-run-output.schema.json`|Orchestrator|`agent_runs.structured_output_json`|

M4 中 `tool_requests` 必须为空；任何 Repo、Sandbox、Git、Docker、SSH 或部署动作只能写入 DevelopmentPlan 或 ApprovalRequest，不能自动执行。

风险等级必须单调不降：Requirement 输出取 Task 输入与模型输出最高值，并把
新识别的更高风险写回 Task；Architect 取当前 Task 与设计输出最高值，L2-L4
强制设计审批；Planner 再取设计、计划输出和各风险项最高值，计划审批保留该
最高等级。

## 2.2 M6 Tester / Reviewer 证据门禁

### Tester

- execution recipe 当前为 `schema_version=1.1`。
- 每条 `acceptance_evidence` 必须提供唯一、稳定且以 `test_` 开头的
  `testcase_names`，并绑定一个 Requirement AC。
- Tester 解析真实 JUnit XML，按函数名、参数化用例基名和
  `classname.testcase` 收集结果；一条 AC 的全部映射 testcase 都存在且通过时
  才能标记 `passed`。
- 任一 testcase 失败则 AC 为 `failed`；缺失、跳过或 JUnit 缺失/解析失败则为
  `not_covered`，不能用“整批 pytest 退出码为 0”替代逐 AC 证据。
- pytest 命令不存在、超时、执行基础设施失败或 JUnit 不可解析时，Task 按
  基础设施失败暂停；真实测试失败保存报告并回到 Implementing。

### Reviewer

- `changed_files`、`diff_paths`、`git.diff.changed_files` 和
  `git.diff.paths` 必须非空、无重复且集合精确一致。
- Reviewer 读取的是持久化安全投影 diff，而不是含敏感值的 raw patch。该投影
  必须保留 Git 结构、路径和领域 marker，并且非空、未截断；
  `patch_truncated=true` 或正文含截断标记时阻止批准。
- 每个 changed file 必须在 patch 中具有与 `created/updated/deleted` 语义匹配
  的 `diff --git`、`---` 和 `+++` 文件头。
- 对受控 auth/profile recipe，patch 还必须覆盖约定的认证路由、安全原语、
  users 持久化、应用装配、黑盒/白盒测试路径与领域 marker。
- 原始 UTF-8 patch bytes/SHA 只在同进程用于创建 lossless Artifact 和执行 Git
  最终门禁；ToolCall 数据库存储与 API preview 继续脱敏。
- 证据缺失或领域门禁失败时必须生成 ReviewIssue，并令
  `verdict=changes_requested`、`proceed_to_security=false`；只有完整安全投影
  diff、测试证据和全部 AC 均满足时才允许进入 SecurityScanning。

## 3. ToolCallRequest 契约

```json
{
  "task_id": "uuid",
  "agent_run_id": "uuid",
  "agent_type": "coder",
  "provider_call_id": "call_001",
  "provider_item_type": "function_call",
  "tool_name": "repo.write_file",
  "risk_level": "L1",
  "idempotency_key": "task_001:write_file:001",
  "arguments": {
    "workspace_root": "<server-bound>",
    "path": "backend/app/api/auth.py",
    "content": "UTF-8 source text",
    "mode": "replace",
    "expected_sha256": "missing"
  },
  "reason": "实现登录接口"
}
```

`agent_run_id` 与 `agent_type` 必须同时存在或同时为空；
`provider_call_id` 与 `provider_item_type` 也必须成对出现。模型工具调用必须提供
provider pair；Platform API 公开 Tool Gateway 请求不接受 `agent_type`，而是从
AgentRun 解析后构造内部 ToolCallRequest。

## 4. ToolResult 契约

```json
{
  "status": "succeeded",
  "summary": "已写入 backend/app/api/auth.py",
  "result_json": {
    "path": "backend/app/api/auth.py",
    "sha256": "sha256:..."
  },
  "stdout_summary": null,
  "stderr_summary": null,
  "duration_ms": 120,
  "started_at": "2026-07-07T10:00:00Z",
  "finished_at": "2026-07-07T10:00:01Z",
  "error_code": null,
  "requires_approval": false,
  "approval_reason": null,
  "arguments_summary": "{\"path\":\"backend/app/api/auth.py\"}",
  "audit_json": {}
}
```

失败时：

```json
{
  "status": "failed",
  "summary": "sandbox command timed out",
  "result_json": null,
  "stdout_summary": null,
  "stderr_summary": "process exceeded timeout",
  "duration_ms": 60000,
  "started_at": "2026-07-07T10:00:00Z",
  "finished_at": "2026-07-07T10:01:00Z",
  "error_code": "command_timeout",
  "requires_approval": false,
  "approval_reason": null,
  "arguments_summary": "{\"command\":[\"...\"]}",
  "audit_json": {}
}
```

## 5. 审批触发规则

|场景|风险等级|处理|
|---|---|---|
|读取文件、读取日志、查询指标|L0|直接执行，记录审计|
|写 sandbox worktree、运行测试|L1|默认允许，记录审计|
|创建 commit、PR、Issue 评论|L2|可自动执行，控制台可配置是否要求审批|
|部署 staging、重启 staging 服务、清缓存|L3|必须创建 ApprovalRequest|
|production 回滚、数据库 destructive migration、删除数据|L4|必须人工审批，MVP 不自动执行|

ApprovalRequest 示例：

```json
{
  "task_id": "uuid",
  "action": "deploy.deploy_staging",
  "risk_level": "L3",
  "reason": "将 sample-repo-python 的 commit abc123 部署到 staging",
  "arguments_summary": {
    "project_id": "uuid",
    "environment": "staging",
    "version": "20260707-001"
  }
}
```

## 6. Agent 权限矩阵

|Agent|可读|可写|需审批|
|---|---|---|---|
|Requirement|需求、repo 只读|requirement_spec|无|
|Planner|spec、repo 只读、日志指标只读|development_plan|无|
|Architect|spec、repo 只读|technical_design、OpenAPI 草案、DB schema 草案|高风险设计、migration 生成|
|Scaffold|template、spec|sandbox worktree|覆盖大量文件时|
|Coder|spec、repo、diff|sandbox worktree、测试文件|commit、PR|
|Tester|approved recipe、ImplementationResult、pytest/JUnit|TestReport、JUnit Artifact|无|
|Reviewer|完整、未截断的安全投影 diff、changed files、Requirement AC、TestReport|ReviewReport|无|
|Security|repo、依赖、镜像|security report|无|
|Release / Deploy|CI、deployment plan、release status|release plan、deployment result、rollback plan|deploy、rollback|
|SRE|metrics、logs、alerts、deployments|incident analysis、runbook proposal|runbook 执行、重启、回滚|

## 7. 结构化输出 schema 清单

|schema|生产者|消费者|
|---|---|---|
|RequirementSpec|Requirement Agent|Architect、Planner、Console|
|AcceptanceCriteria|Requirement Agent|Tester、Reviewer、Console|
|TechnicalDesign|Architect Agent|Planner、Coder、Reviewer、Console|
|DevelopmentPlan|Planner Agent|Orchestrator、Coder、Tester|
|ImplementationResult|Coder Agent|Tester、Reviewer|
|TestReport|Tester Agent|Reviewer、Console|
|ReviewReport|Reviewer Agent|Orchestrator、Console|
|SecurityReport|Security Agent|Reviewer、Release / Deploy Agent|
|ReleasePlan|Release / Deploy Agent|Approval、Deployment Controller|
|IncidentAnalysis|SRE Agent|Console、Runbook|

M4 已实现 RequirementSpec、TechnicalDesign、DevelopmentPlan；M6 已实现
Scaffold、Coder/Implementation、TestReport、ReviewReport 和 SecurityReport
角色输出及对应 Artifact。ReleasePlan 与 IncidentAnalysis 分别留给 M7、M8。

## 8. Prompt 与输出稳定性要求

- Base Instructions 在整个 conversation 内保持完全稳定；当前角色的详细
  Instructions 作为 developer ResponseItem 进入当前 turn。
- Requirement、Architect、Planner 以及后续普通角色属于同一 Task root
  conversation，不按 `agent_type` 创建新会话。
- Responses 请求发送完整有序历史：developer/user message、assistant final
  answer、`reasoning.encrypted_content`、function/custom tool call、匹配的
  tool output、审批上下文和 subagent notification。
- `store=false` 只移除不可复用 item id 和内部 metadata，不删除 message phase、
  reasoning、call status 或 call_id。
- Responses `text.format` 使用稳定扁平 `cloudhelm_agent_output_v1`，覆盖当前
  八个普通角色全部字段；当前角色输出仍由专属 Pydantic model 严格校验。禁止按角色
  切换 schema，因为 Structured Output schema 位于消息前缀之前，会破坏缓存。
- 校验失败时只在当前重试追加 `<validation_repair>`，不修改 Base Instructions，
  不提交失败尝试的 ResponseItem，也不重复调用高风险工具。
- M6 工具步骤已经产生真实 ToolCall 后若发生基础设施失败，Platform API 会保存
  配对的 function/custom call 与 output，并追加 `<failed_step_context>`。该
  失败 turn 不产生成功角色输出，与结构化格式修复的未提交尝试语义不同。
- `prompt_cache_key` 基于 conversation ID；普通角色共用，显式 child 使用新 key。
- `cache_hit` 只能由供应商 usage 中 `cached_input_tokens > 0` 推导。AgentRun
  记录总量，同时用 `provider_requests` 保存每次格式修复请求的原始 usage。
- 当前真实兼容端点支持 `reasoning.context=all_turns`、encrypted reasoning、
  Codex headers、稳定扁平 schema 和自动缓存。官方显式断点协议启用时发送
  `prompt_cache_options.mode=explicit` 与 content `prompt_cache_breakpoint`；
  2026-07-11 单请求真实探测返回 HTTP 502，根级 `anyOf/$ref` schema 探测也
  返回 502。因此两项能力不进入默认请求，且不得静默吞掉启用后的真实错误。

## 8.1 Instructions 分层

|层|内容|稳定性|
|---|---|---|
|Base Instructions|会话、可信边界、ResponseItem、输出、工具、审批、风险、subagent、真实性与完成判定|整个 conversation 固定|
|Role Instructions|目标、输入解释、处理顺序、字段精度、allowlist、禁止项、完成判定|当前 turn 追加|
|Turn envelope|input/output contract、Task 输入、conversation scope|当前 turn 追加|
|Validation repair|Pydantic 错误、只允许修复的字段和禁止动作|仅失败重试追加|
|Approval context|action/status/actor/resource/version 事实和可信边界|审批决策后追加|
|Subagent contract|parent、role、depth、fork mode、权限和回传策略|child 创建时固定|

扁平传输 schema 只是缓存稳定的跨角色字段集合，不表达当前角色的完整必填和
嵌套约束。模型必须根据 `<role_contract>.output_contract` 输出当前角色对象，
并由专属 Pydantic model 严格校验；不得额外包裹
`agent_type/output/result` 或输出其他角色专属字段。

## 8.2 Root 与 subagent conversation

- 每个 Task 通过 partial unique index 只能有一个 root conversation。
- root 不绑定单一 agent role；角色变化只增加 turn。
- 只有 `spawn_subagent` 可以创建 child，并校验父会话 active、父 AgentRun
  running、Task running、同 Task、最大深度、active 数量、非空 objective 和
  expected result。
- 默认 `max_depth=1`、`max_threads=6`，参考 Codex CLI 只允许 root 创建直接
  child；递归委派必须显式调整配置并记录风险。
- fresh child 不复制父历史；full-history child 只复制
  system/developer/user message 与 assistant final answer。
- reasoning、tool call、tool output 和内部 metadata 不跨 child fork。
- child 完成、失败或取消时，只向父 conversation 追加
  `<subagent_notification>`；摘要必须非空、脱敏且不超过 4000 字符，隐藏
  reasoning、原始日志和完整工具历史不合并。
- child 有效工具为 child role 与全部父级 AgentRun role allowlist 的交集；
  Tool Gateway 每次调用沿 active conversation lineage 重新计算，越权请求写入
  失败 ToolCall、`subagent_tool_not_allowed` 和权限指纹。claim 前上下文拒绝
  或策略漂移重放不改写原 ToolCall，而是写 `ToolCallRejected` 安全事件。
  工具仍需经过 Policy、Approval、workspace allowlist、限流和审计。
- child 完成采用叶子优先顺序；当前 child 存在 active AgentRun 或任一 active
  后代 conversation 时返回稳定 `409`，避免结束父 child 后把后代留成孤儿。
  暂停/终态 Task 不允许创建或完成 child，Task cancel 统一级联关闭。
- 每个普通 Agent 成功步骤通过数据库 savepoint 原子保存业务产物、
  AgentRun、conversation turn 和完成事件；晚期失败回滚全部成功侧写入后再
  单独记录失败 AgentRun。
- M6 失败步骤若已有真实工具调用，失败 AgentRun 会关联保存 call/output 与失败
  上下文后的 conversation turn，便于恢复时重放真实证据。

## 8.3 Codex CLI 协作模型映射与当前边界

- Task root conversation 对应 Codex CLI 主 agent thread，负责用户目标、决策、
  审批上下文和最终汇总；角色顺序推进是同一 thread 的连续 turn。
- 显式 subagent 对应独立 child agent thread。spawn 必须提供 role、objective、
  expected result、fork mode 和完成判定；父线程只接收最终通知。
- read-heavy 探索、测试分析、安全审查和文档核验可并行；会写入同一 workspace、
  Git index 或共享状态的任务必须串行，或使用隔离 worktree/workspace。
- 父线程必须等待所需 child 完成，或明确记录 failed/cancelled/timeout 后再形成
  汇总结论，不能把未返回结果写成已完成。
- 上述并行、隔离和等待规则当前用于仓库开发协作与后续调度设计。M1-M6 产品
  代码只交付内部 root/child conversation、配额、父运行绑定、工具权限交集、
  摘要和取消生命周期原语；尚无 Orchestrator/provider control tool 调用点、
  child AgentRun 执行、wait-all barrier、conversation list/detail API 或独立
  thread UI。
- Codex CLI 的 steer/queue 区分作为后续交互契约：steer 只追加到当前 active
  turn，queue 只进入下一 turn。M1-M6 当前只实现审批上下文、暂停/取消和
  subagent notification，尚未提供通用用户消息 steer/queue API。

## 9. 审计字段

每次工具调用和 Agent 决策至少记录：

- `task_id`
- `agent_run_id`
- `agent_type`
- `tool_name`
- `risk_level`
- `arguments_hash`
- `arguments_summary`
- `approval_id`
- `status`
- `duration_ms`
- `result_summary`
- `error_code`
- `created_at`
## M5-M6 实现同步：工具声明与风险等级

当前默认工具声明如下：

|工具名|风险|审批|说明|
|---|---|---|---|
|`requirement.normalize`|L0|否|整理原始需求为结构化片段。|
|`design.render_markdown`|L0|否|渲染设计 Markdown 草案。|
|`repo.read_file` / `repo.search_text` / `repo.list_files`|L0|否|只读访问受控 worktree。|
|`repo.write_file`|L1|否|写入受控 worktree 内 UTF-8 文件。|
|`sandbox.run_command`|L1|否|在本地受控目录执行非交互命令，支持超时和输出摘要。|
|`sandbox.collect_artifact`|L0|否|收集本地 sandbox 产物元数据。|
|`scaffold.prepare_workspace`|L1|否|准备 Task 独立 Git workspace 和 baseline。|
|`test.run_pytest`|L1|否|执行 pytest 并生成/解析 JUnit。|
|`security.run_bandit` / `security.run_pip_audit`|L1|否|执行受控代码与依赖安全扫描。|
|`git.status` / `git.diff` / `git.format_patch`|L0|否|读取本地 Git 状态、diff 或 commit patch。|
|`git.create_branch` / `git.commit`|L2|否|创建本地分支和显式文件列表提交，不 push。|
|`approval.request_remote_action`|L3|是|只创建审批请求，不执行远端动作。|

ToolCallRequest 必须包含 `task_id`、`tool_name`、`risk_level`、
`idempotency_key`、`arguments`、`reason`；Agent 调用还必须带成对的
`agent_run_id/agent_type` 与 `provider_call_id/provider_item_type`。
ToolCallResult 包含 `status`、`summary`、`result_json`、`stdout_summary`、
`stderr_summary`、`duration_ms`、`started_at`、`finished_at`、`error_code`、
`requires_approval`、`approval_reason`、`arguments_summary` 和 `audit_json`。
