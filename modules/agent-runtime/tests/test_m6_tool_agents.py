"""M6 工具型 Agent、稳定工具前缀与同一逻辑 turn 测试。"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from cloudhelm_agent_runtime.agents import (
    CoderAgent,
    ReviewerAgent,
    SecurityAgent,
)
from cloudhelm_agent_runtime.providers import (
    LocalStructuredProvider,
    OpenAICompatibleProvider,
    PendingProviderTurn,
    ProviderConversation,
    ProviderToolCall,
    ProviderToolDefinition,
    ProviderToolExecutionResult,
)
from cloudhelm_agent_runtime.providers.request_payloads import build_responses_body
from cloudhelm_agent_runtime.providers.contracts import user_message_item
from cloudhelm_agent_runtime.providers.local_tool_evidence import (
    LocalToolEvidence,
    command_execution,
)
from cloudhelm_agent_runtime.schemas.agent_io import (
    ChangedFile,
    CommandExecution,
    PlannedCommand,
    PlannedFileWrite,
    PlannedToolCommand,
    RiskLevel,
)
from cloudhelm_agent_runtime.schemas.implementation import (
    CoderAgentInput,
    CoderAgentOutput,
)
from cloudhelm_agent_runtime.schemas.requirement import (
    AcceptanceCriterion,
    RequirementAgentInput,
    RequirementAgentOutput,
)
from cloudhelm_agent_runtime.schemas.review_report import (
    AcceptanceReview,
    ReviewerAgentInput,
    ReviewerAgentOutput,
)
from cloudhelm_agent_runtime.schemas.scaffold import ScaffoldAgentOutput
from cloudhelm_agent_runtime.schemas.security_report import (
    SecurityAgentInput,
    SecurityAgentOutput,
)
from cloudhelm_agent_runtime.schemas.test_report import (
    AcceptanceTestResult,
    TesterAgentOutput as TestReportOutput,
)


def _tool(name: str, properties: dict | None = None) -> ProviderToolDefinition:
    """构造测试用稳定 function tool。"""

    properties = properties or {}
    return ProviderToolDefinition(
        name=name,
        description=f"{name} test tool",
        parameters={
            "type": "object",
            "properties": properties,
            "additionalProperties": False,
        },
    )


def _acceptance() -> list[AcceptanceCriterion]:
    return [
        AcceptanceCriterion(
            id="AC-001",
            description="真实工具执行后形成可验证结果。",
            verification="pytest",
        )
    ]


RECIPE_SHA256 = f"sha256:{'1' * 64}"


def test_command_execution_truncates_long_output_summaries() -> None:
    """stdout/stderr 必须在构造 CommandExecution 前收紧到契约上限。"""

    execution = command_execution(
        LocalToolEvidence(
            call=ProviderToolCall(
                call_id="call-long-output",
                name="sandbox.run_command",
                arguments={},
            ),
            status="failed",
            result={
                "stdout_summary": "o" * 4500,
                "stderr_summary": "e" * 5000,
                "result_json": {"exit_code": 1},
            },
            error_code="command_failed",
        ),
        PlannedCommand(
            command=["python", "-m", "pytest"],
            purpose="验证长输出摘要。",
        ),
    )

    assert execution.stdout_summary is not None
    assert execution.stderr_summary is not None
    assert len(execution.stdout_summary) == 4000
    assert len(execution.stderr_summary) == 4000
    assert execution.stdout_summary.endswith("...<truncated:4500>")
    assert execution.stderr_summary.endswith("...<truncated:5000>")


def test_local_coder_executes_real_tool_results_in_one_logical_turn() -> None:
    """Local Provider 应请求真实工具，并在最终只提交一个 conversation turn。"""

    conversation = ProviderConversation(conversation_id=str(uuid4()))
    payload = CoderAgentInput(
        task_id=uuid4(),
        project_id=uuid4(),
        development_plan_id=uuid4(),
        step_ids=["STEP-001"],
        title="新增指标接口",
        implementation_goal="按批准计划写入实现并执行 pytest。",
        branch_name="codex/test-metrics",
        execution_recipe_sha256=RECIPE_SHA256,
        acceptance_criteria=_acceptance(),
        planned_changes=[
            PlannedFileWrite(
                path="src/sample_service/metrics.py",
                operation="create",
                purpose="新增指标实现。",
                content="def metrics():\n    return {'requests': 0}\n",
                create_parent=True,
            )
        ],
        verification_commands=[
            PlannedCommand(
                command=["uv", "run", "pytest", "-q"],
                purpose="运行真实 pytest。",
            )
        ],
        risk_level=RiskLevel.L1,
    )
    calls = []

    def execute(call):  # noqa: ANN001
        calls.append(call)
        if call.name == "git.create_branch":
            return ProviderToolExecutionResult(
                status="succeeded",
                result={
                    "tool_call_id": "tool-branch-1",
                    "summary": "分支已创建。",
                    "result_json": {
                        "branch_name": "codex/test-metrics",
                        "base_commit": "a" * 40,
                    },
                },
            )
        if call.name == "repo.write_file":
            assert call.arguments["path"] == "src/sample_service/metrics.py"
            assert "workspace_root" not in call.arguments
            return ProviderToolExecutionResult(
                status="succeeded",
                result={
                    "tool_call_id": "tool-write-1",
                    "summary": "文件已真实写入。",
                    "result_json": {
                        "path": call.arguments["path"],
                        "sha256": f"sha256:{'a' * 64}",
                    },
                },
            )
        if call.name == "sandbox.run_command":
            return ProviderToolExecutionResult(
                status="succeeded",
                result={
                    "tool_call_id": "tool-test-1",
                    "summary": "pytest 已真实执行。",
                    "result_json": {
                        "exit_code": 0,
                        "passed_count": 4,
                        "failed_count": 0,
                        "skipped_count": 0,
                        "duration_ms": 25,
                        "report_ref": "artifact://pytest.xml",
                    },
                },
            )
        assert call.name == "git.diff"
        return ProviderToolExecutionResult(
            status="succeeded",
            result={
                "tool_call_id": "tool-diff-1",
                "summary": "diff 已读取。",
                "result_json": {
                    "changed_files": ["src/sample_service/metrics.py"],
                    "patch": "+def metrics(): ...",
                },
            },
        )

    output = CoderAgent(LocalStructuredProvider()).run(
        payload,
        conversation=conversation,
        tools=(
            _tool("git.create_branch"),
            _tool("git.diff"),
            _tool("sandbox.run_command"),
            _tool("repo.write_file"),
        ),
        tool_executor=execute,
    )

    assert output.status == "completed"
    assert output.changed_files[0].sha256 == f"sha256:{'a' * 64}"
    assert output.verification[0].passed_count == 4
    assert [call.name for call in calls] == [
        "git.create_branch",
        "repo.write_file",
        "sandbox.run_command",
        "git.diff",
    ]
    assert conversation.turn_count == 1
    call_ids = [
        item["call_id"]
        for item in conversation.items
        if item["type"] == "function_call"
    ]
    output_ids = [
        item["call_id"]
        for item in conversation.items
        if item["type"] == "function_call_output"
    ]
    assert call_ids == output_ids


def test_local_reviewer_and_security_use_real_evidence() -> None:
    """Reviewer/Security 的结论必须由 diff、测试和扫描结果决定。"""

    changed = [
        ChangedFile(
            path="src/sample_service/main.py",
            operation="updated",
            intent="新增 API。",
            tool_call_id="tool-write",
        )
    ]
    test_report = TestReportOutput(
        task_id=uuid4(),
        development_plan_id=uuid4(),
        summary="pytest 通过。",
        status="passed",
        commands=[
            CommandExecution(
                call_id="call-test",
                command=["uv", "run", "pytest"],
                purpose="pytest",
                status="succeeded",
                exit_code=0,
                passed_count=2,
                failed_count=0,
            )
        ],
        passed_count=2,
        failed_count=0,
        acceptance_results=[
            AcceptanceTestResult(
                criterion_id="AC-001",
                status="passed",
                evidence_refs=["artifact://pytest.xml"],
                notes="pytest 通过。",
            )
        ],
        risk_level=RiskLevel.L1,
    )
    reviewer_payload = ReviewerAgentInput(
        task_id=test_report.task_id,
        project_id=uuid4(),
        development_plan_id=test_report.development_plan_id,
        title="评审真实 diff",
        acceptance_criteria=_acceptance(),
        acceptance_evidence=[
            AcceptanceReview(
                criterion_id="AC-001",
                status="satisfied",
                evidence_refs=["artifact://pytest.xml"],
                notes="pytest 和 diff 均覆盖本 AC。",
            )
        ],
        changed_files=changed,
        diff_paths=["src/sample_service/main.py"],
        test_report=test_report,
        execution_recipe_sha256=RECIPE_SHA256,
        risk_level=RiskLevel.L1,
    )

    def read_reviewer_diff(call):  # noqa: ANN001
        assert call.arguments["max_output_chars"] == 200000
        return ProviderToolExecutionResult(
            status="succeeded",
            result={
                "tool_call_id": "tool-diff",
                "summary": "已读取真实 diff。",
                "result_json": {
                    "paths": call.arguments["paths"],
                    "changed_files": [
                        "src/sample_service/main.py"
                    ],
                    "patch_truncated": False,
                    "patch": (
                        "diff --git "
                        "a/src/sample_service/main.py "
                        "b/src/sample_service/main.py\n"
                        "--- a/src/sample_service/main.py\n"
                        "+++ b/src/sample_service/main.py\n"
                        "@@ -1 +1 @@\n-old\n+new\n"
                    ),
                },
            },
        )

    reviewer = ReviewerAgent(LocalStructuredProvider()).run(
        reviewer_payload,
        conversation=ProviderConversation(conversation_id=str(uuid4())),
        tools=(_tool("git.diff"),),
        tool_executor=read_reviewer_diff,
    )
    assert reviewer.verdict == "approved"
    assert reviewer.proceed_to_security is True

    security_payload = SecurityAgentInput(
        task_id=reviewer.task_id,
        project_id=uuid4(),
        development_plan_id=reviewer.development_plan_id,
        title="扫描真实变更",
        changed_files=changed,
        scan_commands=[
            PlannedToolCommand(
                tool_name="security.run_bandit",
                arguments={"path": "src"},
                command=["uv", "run", "bandit", "-r", "src"],
                purpose="运行 Bandit。",
            )
        ],
        execution_recipe_sha256=RECIPE_SHA256,
        risk_level=RiskLevel.L1,
    )
    security = SecurityAgent(LocalStructuredProvider()).run(
        security_payload,
        conversation=ProviderConversation(conversation_id=str(uuid4())),
        tools=(_tool("security.run_bandit"),),
        tool_executor=lambda call: ProviderToolExecutionResult(
            status="succeeded",
            result={
                "tool_call_id": "tool-security",
                "summary": "Bandit 已完成。",
                "result_json": {
                    "exit_code": 1,
                    "findings": [
                        {
                            "scanner": "bandit",
                            "rule_id": "B301",
                            "severity": "high",
                            "path": "src/sample_service/main.py",
                            "line": 12,
                            "message": "检测到高风险调用。",
                        }
                    ],
                },
            },
        ),
    )
    assert security.verdict == "failed"
    assert security.blocking is True
    assert security.findings[0].id == "FINDING-001"
    assert security.risk_level == RiskLevel.L2


@pytest.mark.parametrize(
    "output",
    [
        ScaffoldAgentOutput(
            task_id=uuid4(),
            development_plan_id=uuid4(),
            step_id="STEP-001",
            summary="blocked",
            status="blocked",
            blockers=["missing tool"],
            risk_level=RiskLevel.L1,
        ),
        CoderAgentOutput(
            task_id=uuid4(),
            development_plan_id=uuid4(),
            step_ids=["STEP-001"],
            summary="blocked",
            status="blocked",
            blockers=["missing tool"],
            risk_level=RiskLevel.L1,
        ),
        TestReportOutput(
            task_id=uuid4(),
            development_plan_id=uuid4(),
            summary="blocked",
            status="blocked",
            acceptance_results=[
                AcceptanceTestResult(
                    criterion_id="AC-001",
                    status="not_covered",
                    notes="missing tool",
                )
            ],
            failure_reasons=["missing tool"],
            risk_level=RiskLevel.L1,
        ),
        ReviewerAgentOutput(
            task_id=uuid4(),
            development_plan_id=uuid4(),
            summary="blocked",
            verdict="blocked",
            acceptance_results=[
                AcceptanceReview(
                    criterion_id="AC-001",
                    status="missing",
                    notes="no evidence",
                )
            ],
            changed_files=[
                ChangedFile(
                    path="README.md",
                    operation="updated",
                    intent="test",
                )
            ],
            proceed_to_security=False,
            risk_level=RiskLevel.L1,
        ),
        SecurityAgentOutput(
            task_id=uuid4(),
            development_plan_id=uuid4(),
            summary="blocked",
            verdict="blocked",
            remaining_risks=["missing scanner"],
            blocking=True,
            risk_level=RiskLevel.L1,
        ),
    ],
)
def test_m6_outputs_forbid_extra_fields(output) -> None:  # noqa: ANN001
    """全部新增输出 schema 都必须拒绝额外字段。"""

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        output.__class__.model_validate(
            {
                **output.model_dump(mode="json"),
                "unexpected": True,
            }
        )


def test_responses_body_keeps_tools_and_text_format_stable_across_roles() -> None:
    """工具顺序、parallel flag 和 text.format 不得随普通角色变化。"""

    conversation = ProviderConversation(
        conversation_id=str(uuid4()),
        prompt_cache_key="cloudhelm:stable-tools",
    )
    payload = RequirementAgentInput(
        task_id=uuid4(),
        project_id=uuid4(),
        title="稳定工具",
        description="验证跨角色请求前缀。",
        source_type="manual",
        risk_level=RiskLevel.L1,
    )
    tools = (
        _tool("sandbox.run_command"),
        _tool("repo.read_file"),
    )
    bodies = [
        build_responses_body(
            agent_type=agent_type,
            payload=payload,
            output_model=output_model,
            model_name="gpt-test",
            current_input_items=[user_message_item('{"test":"stable"}')],
            conversation=conversation,
            reasoning_effort="xhigh",
            reasoning_summary="auto",
            reasoning_context="all_turns",
            max_output_tokens=2048,
            explicit_cache_breakpoint=False,
            tools=tools,
        )[0]
        for agent_type, output_model in (
            ("requirement", RequirementAgentOutput),
            ("coder", CoderAgentOutput),
            ("security", SecurityAgentOutput),
        )
    ]
    assert bodies[0]["tools"] == bodies[1]["tools"] == bodies[2]["tools"]
    assert [item["name"] for item in bodies[0]["tools"]] == [
        "repo.read_file",
        "sandbox.run_command",
    ]
    assert all(body["parallel_tool_calls"] is False for body in bodies)
    assert bodies[0]["text"] == bodies[1]["text"] == bodies[2]["text"]


class FakeSseResponse:
    """发送一个工具-only response.completed 事件。"""

    def __init__(self, response_payload: dict) -> None:
        self.response_payload = response_payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:  # noqa: ANN001
        return None

    def __iter__(self):
        event = {
            "type": "response.completed",
            "response": self.response_payload,
        }
        yield f"data: {json.dumps(event)}\n".encode()
        yield b"\n"


def test_openai_exchange_accepts_tool_only_response_without_mutation(monkeypatch) -> None:
    """OpenAI 单次 exchange 应返回 call，但把执行和 turn 提交留给调用方。"""

    captured = {}
    provider = OpenAICompatibleProvider(
        api_base="https://api.example.test",
        api_key="test-key",
        model_name="gpt-test",
        retry_backoff_seconds=0,
    )
    conversation = ProviderConversation(
        conversation_id=str(uuid4()),
        prompt_cache_key="cloudhelm:tool-only",
    )
    payload = CoderAgentInput(
        task_id=uuid4(),
        project_id=uuid4(),
        development_plan_id=uuid4(),
        step_ids=["STEP-001"],
        title="tool only",
        implementation_goal="写入真实文件。",
        branch_name="codex/tool-only",
        execution_recipe_sha256=RECIPE_SHA256,
        acceptance_criteria=_acceptance(),
        planned_changes=[
            PlannedFileWrite(
                path="README.md",
                operation="update",
                purpose="更新说明。",
                content="# updated\n",
            )
        ],
        risk_level=RiskLevel.L1,
    )
    pending = PendingProviderTurn.start("coder", payload)

    def fake_urlopen(http_request, timeout):  # noqa: ANN001
        captured["body"] = json.loads(http_request.data.decode())
        return FakeSseResponse(
            {
                "id": "resp_tool",
                "status": "completed",
                "usage": {
                    "input_tokens": 100,
                    "input_tokens_details": {"cached_tokens": 50},
                    "output_tokens": 20,
                },
                "output": [
                    {
                        "id": "fc_1",
                        "type": "function_call",
                        "name": "repo.write_file",
                        "arguments": '{"path":"README.md","content":"# updated\\n"}',
                        "call_id": "call_tool",
                        "status": "completed",
                    }
                ],
            }
        )

    monkeypatch.setattr(
        "cloudhelm_agent_runtime.providers.openai_compatible.request.urlopen",
        fake_urlopen,
    )
    exchange = provider.exchange(
        "coder",
        payload,
        CoderAgentOutput,
        conversation=conversation,
        pending_turn=pending,
        tools=(_tool("repo.write_file"),),
    )

    assert exchange.output_text is None
    assert exchange.tool_calls[0].call_id == "call_tool"
    assert exchange.metadata is not None
    assert exchange.metadata.cached_input_tokens == 50
    assert conversation.turn_count == 0
    assert pending.exchange_items == []
    assert captured["body"]["parallel_tool_calls"] is False
    assert captured["body"]["tools"][0]["name"] == "repo.write_file"
