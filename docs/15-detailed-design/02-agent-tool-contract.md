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
|IncidentAnalysis|SRE Agent|Console、Runbook|

## 8. Prompt 与输出稳定性要求

- system prompt 固定角色边界。
- developer prompt 注入当前任务目标、约束、工具权限。
- user/task context 只传必要上下文，避免过长。
- 输出必须先过 JSON Schema / Pydantic 校验。
- 校验失败时执行“修复格式”重试，不重复调用高风险工具。

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
