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
    "repo.search_code",
    "sandbox.run_tests"
  ]
}
```

## 2. AgentRun 标准输出

```json
{
  "agent_type": "coder",
  "status": "succeeded",
  "summary": "实现用户注册、登录和个人资料接口",
  "structured_output_type": "implementation_result",
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

## 3. ToolCallRequest 契约

```json
{
  "task_id": "uuid",
  "agent_run_id": "uuid",
  "tool_name": "repo.write_file",
  "risk_level": "L1",
  "idempotency_key": "task_001:write_file:001",
  "arguments": {
    "path": "backend/app/api/auth.py",
    "content_ref": "artifact://generated/auth_py"
  },
  "reason": "实现登录接口",
  "expected_result_schema": "RepoWriteFileResult"
}
```

## 4. ToolResult 契约

```json
{
  "tool_call_id": "uuid",
  "status": "success",
  "risk_level": "L1",
  "result": {
    "summary": "写入 backend/app/api/auth.py",
    "artifact_refs": []
  },
  "stderr_summary": "",
  "duration_ms": 120,
  "started_at": "2026-07-07T10:00:00Z",
  "finished_at": "2026-07-07T10:00:01Z"
}
```

失败时：

```json
{
  "tool_call_id": "uuid",
  "status": "failed",
  "error": {
    "code": "TOOL_TIMEOUT",
    "message": "sandbox command timed out",
    "retryable": true,
    "detail": {
      "timeout_seconds": 60
    }
  }
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
|Tester|sandbox、CI logs|test report、artifact|无|
|Reviewer|diff、spec、安全报告|review report|无|
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

M4 已实现前三类：RequirementSpec、TechnicalDesign、DevelopmentPlan。ImplementationResult 及之后的执行类 schema 留到 M5-M8。
|IncidentAnalysis|SRE Agent|Console、Runbook|

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
  三个角色全部字段；当前角色输出仍由专属 Pydantic model 严格校验。禁止按角色
  切换 schema，因为 Structured Output schema 位于消息前缀之前，会破坏缓存。
- 校验失败时只在当前重试追加 `<validation_repair>`，不修改 Base Instructions，
  不提交失败尝试的 ResponseItem，也不重复调用高风险工具。
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
  running、同 Task、最大深度、active 数量、非空 objective 和 expected result。
- fresh child 不复制父历史；full-history child 只复制
  system/developer/user message 与 assistant final answer。
- reasoning、tool call、tool output 和内部 metadata 不跨 child fork。
- child 完成、失败或取消时，只向父 conversation 追加
  `<subagent_notification>`；隐藏 reasoning 不合并。
- 每个普通 Agent 成功步骤通过数据库 savepoint 原子保存业务产物、
  AgentRun、conversation turn 和完成事件；晚期失败回滚全部成功侧写入后再
  单独记录失败 AgentRun。

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
## M5 实现同步：工具声明与风险等级

M5 默认工具声明如下：

|工具名|风险|审批|说明|
|---|---|---|---|
|`requirement.normalize`|L0|否|整理原始需求为结构化片段。|
|`design.render_markdown`|L0|否|渲染设计 Markdown 草案。|
|`repo.read_file` / `repo.search_text` / `repo.list_files`|L0|否|只读访问受控 worktree。|
|`repo.write_file`|L1|否|写入受控 worktree 内 UTF-8 文件。|
|`sandbox.run_command`|L1|否|在本地受控目录执行非交互命令，支持超时和输出摘要。|
|`sandbox.collect_artifact`|L0|否|收集本地 sandbox 产物元数据。|
|`git.status` / `git.diff`|L0|否|读取本地 Git 状态和 diff。|
|`git.create_branch` / `git.commit`|L2|否|创建本地分支和显式文件列表提交，不 push。|
|`approval.request_remote_action`|L3|是|只创建审批请求，不执行远端动作。|

ToolCallRequest 必须包含 `task_id`、`agent_run_id`、`tool_name`、`risk_level`、`idempotency_key`、`arguments`、`reason`。ToolCallResult 必须包含 `status`、`summary`、`result_json`、`stdout_summary`、`stderr_summary`、`duration_ms`、`started_at`、`finished_at`、`error_code`、`arguments_summary` 和审计摘要。
