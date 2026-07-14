"""Local Tester 的真实 pytest/JUnit 证据交换。"""

from cloudhelm_agent_runtime.providers.local_junit_evidence import (
    map_acceptance_results,
    not_covered_results,
)
from cloudhelm_agent_runtime.providers.local_tool_evidence import (
    command_execution,
    result_details,
    tool_call_evidence,
)
from cloudhelm_agent_runtime.providers.local_tool_plans import (
    PlannedLocalCall,
    call_id,
    calls_result,
    exit_code,
    failure_summaries,
    final_result,
    missing_tool_names,
    sum_optional,
    tool_command_calls,
)
from cloudhelm_agent_runtime.schemas.agent_io import ArtifactEvidence
from cloudhelm_agent_runtime.schemas.test_report import (
    TesterAgentOutput,
)


def tester_exchange(data, output_model, conversation, evidence, tool_names):
    """执行测试命令并生成真实、逐 AC 的测试报告。"""

    calls = tool_command_calls("tester", data.commands, conversation)
    missing = missing_tool_names(calls, tool_names)
    if missing:
        return final_result(
            output_model,
            TesterAgentOutput(
                task_id=data.task_id,
                development_plan_id=data.development_plan_id,
                summary="Tester 所需工具未进入稳定工具清单。",
                status="blocked",
                acceptance_results=_acceptance_results(
                    data,
                    "not_covered",
                    [],
                    "所需测试工具未进入稳定工具清单。",
                ),
                failure_reasons=[
                    f"缺少工具：{name}" for name in missing
                ],
                risk_level=data.risk_level,
            ),
        )
    pending = [call for call in calls if call.call_id not in evidence]
    if pending:
        return calls_result(pending)
    paired = [evidence[call.call_id] for call in calls]
    junit_calls = _junit_calls(calls, paired, conversation)
    missing = missing_tool_names(junit_calls, tool_names)
    if missing:
        return final_result(
            output_model,
            TesterAgentOutput(
                task_id=data.task_id,
                development_plan_id=data.development_plan_id,
                summary="Tester 无法收集 JUnit Artifact。",
                status="blocked",
                acceptance_results=_acceptance_results(
                    data,
                    "not_covered",
                    [],
                    "JUnit Artifact 未能完整收集。",
                ),
                tool_calls=[
                    tool_call_evidence(item) for item in paired
                ],
                failure_reasons=[
                    f"缺少工具：{name}" for name in missing
                ],
                risk_level=data.risk_level,
            ),
        )
    pending = [
        call for call in junit_calls if call.call_id not in evidence
    ]
    if pending:
        return calls_result(pending)
    junit_evidence = [evidence[call.call_id] for call in junit_calls]
    executions = [
        command_execution(item, plan)
        for item, plan in zip(paired, data.commands, strict=True)
    ]
    status = _test_status(paired, junit_evidence)
    failures = failure_summaries(
        [
            item
            for item in [*paired, *junit_evidence]
            if item.status != "succeeded"
            or exit_code(item) not in {0, None}
        ]
    )
    artifacts = _junit_artifacts(junit_evidence)
    evidence_refs = [item.ref for item in artifacts]
    if status == "blocked":
        acceptance_results = not_covered_results(
            data,
            "测试工具或 JUnit 读取被阻断。",
        )
        coverage_failures: list[str] = []
    else:
        acceptance_results, coverage_failures = map_acceptance_results(
            data,
            junit_evidence,
            evidence_refs,
        )
        if any(item.status == "failed" for item in acceptance_results):
            status = "failed"
        elif (
            status == "failed"
            or any(
                item.status == "not_covered"
                for item in acceptance_results
            )
        ):
            status = "partial"
        else:
            status = "passed"
    failures.extend(coverage_failures)
    if status == "blocked" and not failures:
        failures.append("测试工具或 JUnit 证据不可用。")
    if status == "failed" and not failures:
        failures.append("至少一个映射 testcase 失败。")
    return final_result(
        output_model,
        TesterAgentOutput(
            task_id=data.task_id,
            development_plan_id=data.development_plan_id,
            summary=f"Tester 已执行 {len(executions)} 条真实测试命令。",
            status=status,
            commands=executions,
            passed_count=sum_optional(executions, "passed_count"),
            failed_count=sum_optional(executions, "failed_count"),
            skipped_count=sum_optional(executions, "skipped_count"),
            acceptance_results=acceptance_results,
            tool_calls=[
                tool_call_evidence(item)
                for item in [*paired, *junit_evidence]
            ],
            artifacts=artifacts,
            failure_reasons=failures,
            risk_level=data.risk_level,
        ),
    )


def _junit_calls(calls, paired, conversation):
    """根据 pytest 工具结果构造 JUnit 读取请求。"""

    result = []
    for index, item in enumerate(paired, start=len(calls) + 1):
        junit_path = result_details(item).get("junit_path")
        if isinstance(junit_path, str) and junit_path:
            result.append(
                PlannedLocalCall(
                    call_id=call_id(conversation, "tester", index),
                    name="repo.read_file",
                    arguments={
                        "path": junit_path,
                        "max_bytes": 262144,
                    },
                )
            )
    return result


def _test_status(paired, junit_evidence) -> str:
    """区分基础设施阻断、测试失败和真实通过。"""

    blocked = any(
        item.status == "waiting_approval"
        or item.error_code in {"command_not_found", "tool_executor_error"}
        or (item in junit_evidence and item.status != "succeeded")
        for item in [*paired, *junit_evidence]
    )
    failed = any(
        item.status == "failed" or exit_code(item) not in {0, None}
        for item in paired
    )
    return "blocked" if blocked else "failed" if failed else "passed"


def _junit_artifacts(junit_evidence) -> list[ArtifactEvidence]:
    """把真实 repo.read_file 结果投影为 JUnit Artifact 引用。"""

    return [
        ArtifactEvidence(
            type="junit_xml",
            ref=str(result_details(item).get("path")),
            sha256=(
                str(result_details(item).get("sha256"))
                if result_details(item).get("sha256")
                else None
            ),
            size_bytes=(
                int(result_details(item).get("size_bytes"))
                if isinstance(
                    result_details(item).get("size_bytes"),
                    int,
                )
                else None
            ),
        )
        for item in junit_evidence
        if item.status == "succeeded"
    ]
