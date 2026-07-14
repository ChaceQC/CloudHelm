"""Local Tester/Reviewer 真实证据门禁回归测试。"""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from cloudhelm_agent_runtime.agents import (
    ReviewerAgent,
    TesterAgent as RuntimeTesterAgent,
)
from cloudhelm_agent_runtime.providers import (
    LocalStructuredProvider,
    ProviderConversation,
    ProviderToolDefinition,
    ProviderToolExecutionResult,
)
from cloudhelm_agent_runtime.providers.local_quality_exchange import (
    reviewer_exchange,
)
from cloudhelm_agent_runtime.schemas.agent_io import (
    ChangedFile,
    CommandExecution,
    PlannedToolCommand,
    RiskLevel,
)
from cloudhelm_agent_runtime.schemas.requirement import AcceptanceCriterion
from cloudhelm_agent_runtime.schemas.review_report import (
    AcceptanceReview,
    ReviewerAgentInput,
    ReviewerAgentOutput,
)
from cloudhelm_agent_runtime.schemas.test_report import (
    AcceptanceTestEvidence,
    AcceptanceTestResult,
    TesterAgentInput as RuntimeTesterAgentInput,
    TesterAgentOutput as TestReportOutput,
)

RECIPE_SHA256 = f"sha256:{'1' * 64}"
GENERIC_PATH = "src/sample_service/main.py"
AUTH_PROFILE_AC_IDS = (
    "AC-AUTH-001",
    "AC-AUTH-002",
    "AC-AUTH-003",
    "AC-AUTH-004",
    "AC-AUTH-005",
    "AC-PROFILE-001",
    "AC-PROFILE-002",
    "AC-PROFILE-003",
    "AC-SEC-001",
    "AC-OBS-001",
    "AC-TEST-001",
)
AUTH_PROFILE_FILES = (
    ("src/sample_service/auth.py", "created"),
    ("src/sample_service/auth_security.py", "created"),
    ("src/sample_service/user_repository.py", "created"),
    ("src/sample_service/main.py", "updated"),
    ("tests/test_auth_profile.py", "created"),
    ("tests/test_auth_hardening.py", "created"),
)


def _tool(name: str) -> ProviderToolDefinition:
    """构造允许附加测试参数的稳定工具定义。"""

    return ProviderToolDefinition(
        name=name,
        description=f"{name} test tool",
        parameters={
            "type": "object",
            "properties": {},
            "additionalProperties": True,
        },
    )


def _criteria(ids: tuple[str, ...]) -> list[AcceptanceCriterion]:
    """按稳定 ID 构造验收标准。"""

    return [
        AcceptanceCriterion(
            id=criterion_id,
            description=f"验证 {criterion_id}。",
            verification="pytest",
        )
        for criterion_id in ids
    ]


def _passed_report(
    criteria: list[AcceptanceCriterion],
) -> TestReportOutput:
    """构造逐 AC 通过且带真实命令引用的测试报告。"""

    return TestReportOutput(
        task_id=uuid4(),
        development_plan_id=uuid4(),
        summary="pytest 与逐 AC 映射均通过。",
        status="passed",
        commands=[
            CommandExecution(
                call_id="call-test",
                command=["uv", "run", "pytest", "-q"],
                purpose="运行 pytest。",
                status="succeeded",
                exit_code=0,
                passed_count=len(criteria),
                failed_count=0,
            )
        ],
        passed_count=len(criteria),
        failed_count=0,
        acceptance_results=[
            AcceptanceTestResult(
                criterion_id=item.id,
                status="passed",
                evidence_refs=["artifact://junit.xml"],
                notes="映射 testcase 已通过。",
            )
            for item in criteria
        ],
        risk_level=RiskLevel.L1,
    )


def _reviewer_payload(
    *,
    criteria: list[AcceptanceCriterion] | None = None,
    changed_files: list[ChangedFile] | None = None,
    diff_paths: list[str] | None = None,
) -> ReviewerAgentInput:
    """构造 Reviewer 的同一 evidence set 输入。"""

    selected_criteria = criteria or _criteria(("AC-001",))
    selected_files = changed_files or [
        ChangedFile(
            path=GENERIC_PATH,
            operation="updated",
            intent="更新应用入口。",
        )
    ]
    report = _passed_report(selected_criteria)
    return ReviewerAgentInput(
        task_id=report.task_id,
        project_id=uuid4(),
        development_plan_id=report.development_plan_id,
        title="核验完整 Git patch",
        acceptance_criteria=selected_criteria,
        acceptance_evidence=[
            AcceptanceReview(
                criterion_id=item.id,
                status="satisfied",
                evidence_refs=["artifact://junit.xml"],
                notes="真实测试已覆盖。",
            )
            for item in selected_criteria
        ],
        changed_files=selected_files,
        diff_paths=(
            [item.path for item in selected_files]
            if diff_paths is None
            else diff_paths
        ),
        test_report=report,
        execution_recipe_sha256=RECIPE_SHA256,
        risk_level=RiskLevel.L1,
    )


def _run_reviewer(
    payload: ReviewerAgentInput,
    details: dict,
) -> tuple[object, list[dict]]:
    """执行一次 Reviewer 并返回输出与真实工具参数。"""

    arguments: list[dict] = []

    def execute(call):  # noqa: ANN001
        arguments.append(call.arguments)
        return ProviderToolExecutionResult(
            status="succeeded",
            result={
                "tool_call_id": "tool-diff",
                "summary": "已读取真实 diff。",
                "result_json": details,
            },
        )

    output = ReviewerAgent(LocalStructuredProvider()).run(
        payload,
        conversation=ProviderConversation(conversation_id=str(uuid4())),
        tools=(_tool("git.diff"),),
        tool_executor=execute,
    )
    return output, arguments


def _patch_section(path: str, operation: str, body: str = "+new\n") -> str:
    """生成包含正确 created/updated header 的单文件 patch。"""

    old_header = "/dev/null" if operation == "created" else f"a/{path}"
    new_header = "/dev/null" if operation == "deleted" else f"b/{path}"
    return (
        f"diff --git a/{path} b/{path}\n"
        f"--- {old_header}\n"
        f"+++ {new_header}\n"
        "@@ -0,0 +1 @@\n"
        f"{body}"
    )


@pytest.mark.parametrize(
    ("junit_testcase", "truncated", "expected_note"),
    (
        (
            "test_unmapped_behavior",
            False,
            "缺少 testcase：test_required_behavior",
        ),
        (
            "test_required_behavior",
            True,
            "JUnit 证据不完整",
        ),
    ),
)
def test_tester_does_not_pass_ac_with_incomplete_junit_evidence(
    junit_testcase: str,
    truncated: bool,
    expected_note: str,
) -> None:
    """命令成功但 JUnit 缺 testcase 或被截断时均不得宣称 AC 通过。"""

    payload = RuntimeTesterAgentInput(
        task_id=uuid4(),
        project_id=uuid4(),
        development_plan_id=uuid4(),
        title="核验逐 AC JUnit 映射",
        acceptance_criteria=_criteria(("AC-001",)),
        acceptance_evidence=[
            AcceptanceTestEvidence(
                criterion_id="AC-001",
                testcase_names=["test_required_behavior"],
                notes="必须由稳定 testcase 证明。",
            )
        ],
        changed_files=[
            ChangedFile(
                path=GENERIC_PATH,
                operation="updated",
                intent="更新应用入口。",
            )
        ],
        commands=[
            PlannedToolCommand(
                tool_name="test.run_pytest",
                arguments={"junit_path": ".cloudhelm/artifacts/junit.xml"},
                command=["uv", "run", "pytest", "-q"],
                purpose="运行真实 pytest。",
            )
        ],
        execution_recipe_sha256=RECIPE_SHA256,
        risk_level=RiskLevel.L1,
    )
    calls = []

    def execute(call):  # noqa: ANN001
        calls.append(call.name)
        if call.name == "test.run_pytest":
            return ProviderToolExecutionResult(
                status="succeeded",
                result={
                    "tool_call_id": "tool-test",
                    "summary": "pytest 命令成功。",
                    "result_json": {
                        "exit_code": 0,
                        "passed_count": 1,
                        "failed_count": 0,
                        "skipped_count": 0,
                        "junit_path": ".cloudhelm/artifacts/junit.xml",
                    },
                },
            )
        assert call.name == "repo.read_file"
        content = (
            "<testsuites><testsuite tests=\"1\">"
            "<testcase classname=\"tests.test_demo\" "
            f"name=\"{junit_testcase}\"/>"
            "</testsuite></testsuites>"
        )
        return ProviderToolExecutionResult(
            status="succeeded",
            result={
                "tool_call_id": "tool-junit",
                "summary": "已读取 JUnit。",
                "result_json": {
                    "path": call.arguments["path"],
                    "content": content,
                    "size_bytes": len(content.encode("utf-8")),
                    "truncated": truncated,
                },
            },
        )

    output = RuntimeTesterAgent(LocalStructuredProvider()).run(
        payload,
        conversation=ProviderConversation(conversation_id=str(uuid4())),
        tools=(_tool("test.run_pytest"), _tool("repo.read_file")),
        tool_executor=execute,
    )

    assert calls == ["test.run_pytest", "repo.read_file"]
    assert output.status == "partial"
    assert output.acceptance_results[0].status == "not_covered"
    assert expected_note in output.acceptance_results[0].notes
    if truncated:
        assert any(
            "JUnit XML 已截断" in reason
            for reason in output.failure_reasons
        )


def test_reviewer_blocks_empty_diff_paths_without_calling_tool() -> None:
    """Provider 防御层面对绕过 schema 的空 diff_paths 仍返回 blocked。"""

    payload = _reviewer_payload().model_copy(update={"diff_paths": []})
    exchange = reviewer_exchange(
        payload,
        ReviewerAgentOutput,
        ProviderConversation(conversation_id=str(uuid4())),
        {},
        {"git.diff"},
    )
    assert exchange.output_text is not None
    output = ReviewerAgentOutput.model_validate_json(exchange.output_text)

    assert output.verdict == "blocked"
    assert output.proceed_to_security is False
    assert exchange.tool_calls == ()
    assert any("diff_paths" in item.message for item in output.issues)


@pytest.mark.parametrize(
    ("diff_paths", "duplicate_changed_file"),
    (
        ([], False),
        ([GENERIC_PATH, GENERIC_PATH], False),
        (["src/sample_service/other.py"], False),
        ([GENERIC_PATH], True),
    ),
)
def test_reviewer_input_rejects_non_exact_diff_paths(
    diff_paths: list[str],
    duplicate_changed_file: bool,
) -> None:
    """Reviewer schema 在 Provider 前拒绝空、重复或不一致的路径集合。"""

    payload = _reviewer_payload().model_dump(mode="python")
    payload["diff_paths"] = diff_paths
    if duplicate_changed_file:
        payload["changed_files"].append(payload["changed_files"][0])

    with pytest.raises(
        ValidationError,
        match="(at least 1 item|reviewer .* paths)",
    ):
        ReviewerAgentInput.model_validate(payload)


@pytest.mark.parametrize(
    ("details", "message"),
    (
        (
            {
                "paths": [GENERIC_PATH],
                "changed_files": [GENERIC_PATH],
                "patch": "",
                "patch_truncated": False,
            },
            "非空 Git patch",
        ),
        (
            {
                "paths": [GENERIC_PATH],
                "changed_files": [GENERIC_PATH],
                "patch": (
                    _patch_section(GENERIC_PATH, "updated")
                    + "...<truncated:999>"
                ),
                "patch_truncated": True,
            },
            "已截断",
        ),
        (
            {
                "paths": [GENERIC_PATH],
                "changed_files": ["src/sample_service/other.py"],
                "patch": _patch_section(GENERIC_PATH, "updated"),
                "patch_truncated": False,
            },
            "不一致",
        ),
    ),
)
def test_reviewer_blocks_incomplete_or_mismatched_diff(
    details: dict,
    message: str,
) -> None:
    """空、截断或路径不一致的 diff 均不得进入 Security。"""

    output, arguments = _run_reviewer(_reviewer_payload(), details)

    assert arguments == [
        {"paths": [GENERIC_PATH], "max_output_chars": 200000}
    ]
    assert output.verdict == "blocked"
    assert output.proceed_to_security is False
    assert any(message in item.message for item in output.issues)


def test_auth_profile_reviewer_requests_changes_for_missing_markers() -> None:
    """受控 auth/profile patch 即使路径齐全，也必须包含领域实现和测试标记。"""

    criteria = _criteria(AUTH_PROFILE_AC_IDS)
    changed_files = [
        ChangedFile(path=path, operation=operation, intent="实现受控需求。")
        for path, operation in AUTH_PROFILE_FILES
    ]
    patch = "\n".join(
        _patch_section(path, operation)
        for path, operation in AUTH_PROFILE_FILES
    )
    output, _arguments = _run_reviewer(
        _reviewer_payload(
            criteria=criteria,
            changed_files=changed_files,
        ),
        {
            "paths": [item.path for item in changed_files],
            "changed_files": [item.path for item in changed_files],
            "patch": patch,
            "patch_truncated": False,
        },
    )

    assert output.verdict == "changes_requested"
    assert any("缺少必需实现或测试标记" in item.message for item in output.issues)
    assert not any("Git patch 缺少文件头" in item.message for item in output.issues)


def test_auth_profile_reviewer_requests_changes_for_missing_paths() -> None:
    """把全部 marker 塞进单文件也不能替代必需模块和测试文件。"""

    criteria = _criteria(AUTH_PROFILE_AC_IDS)
    changed_file = ChangedFile(
        path="src/sample_service/auth.py",
        operation="created",
        intent="实现受控需求。",
    )
    marker_body = "\n".join(
        (
            "+/auth/register",
            "+/auth/login",
            "+/profile",
            "+hashlib.scrypt",
            "+hmac.new",
            "+CREATE TABLE IF NOT EXISTS users",
            "+test_register_",
            "+test_profile_",
        )
    )
    output, _arguments = _run_reviewer(
        _reviewer_payload(
            criteria=criteria,
            changed_files=[changed_file],
        ),
        {
            "paths": [changed_file.path],
            "changed_files": [changed_file.path],
            "patch": _patch_section(
                changed_file.path,
                changed_file.operation,
                f"{marker_body}\n",
            ),
            "patch_truncated": False,
        },
    )

    assert output.verdict == "changes_requested"
    assert any("缺少必需文件" in item.message for item in output.issues)
    assert not any(
        "缺少必需实现或测试标记" in item.message
        for item in output.issues
    )
