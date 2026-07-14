"""Local Reviewer/Security 的真实证据交换。"""

from cloudhelm_agent_runtime.providers.local_tool_evidence import (
    command_execution,
    result_details,
    tool_call_evidence,
)
from cloudhelm_agent_runtime.providers.local_review_evidence import (
    inspect_reviewer_diff,
)
from cloudhelm_agent_runtime.providers.local_tool_plans import (
    PlannedLocalCall,
    call_id,
    calls_result,
    failure_summaries,
    final_result,
    missing_tool_names,
    security_findings,
    security_risk,
    tool_command_calls,
)
from cloudhelm_agent_runtime.schemas.review_report import (
    ReviewerAgentOutput,
    ReviewIssue,
)
from cloudhelm_agent_runtime.schemas.security_report import SecurityAgentOutput


def reviewer_exchange(data, output_model, conversation, evidence, tool_names):
    """读取真实 diff 并根据 AC/test evidence 形成评审结论。"""

    issues = list(data.known_issues)
    calls = []
    if not data.diff_paths:
        verdict = "blocked"
        tool_calls = []
        issues.append(
            ReviewIssue(
                id=f"ISSUE-{len(issues) + 1:03d}",
                severity="high",
                message="Reviewer 输入缺少 diff_paths。",
                recommendation="从同一 Coder evidence set 重新生成变更路径。",
            )
        )
    else:
        calls = [
            PlannedLocalCall(
                call_id=call_id(conversation, "reviewer", 1),
                name="git.diff",
                arguments={
                    "paths": data.diff_paths,
                    "max_output_chars": 200000,
                },
            )
        ]
        missing = missing_tool_names(calls, tool_names)
        if missing:
            verdict = "blocked"
            tool_calls = []
            issues.append(
                ReviewIssue(
                    id=f"ISSUE-{len(issues) + 1:03d}",
                    severity="high",
                    message="Reviewer 所需 git.diff 未进入稳定工具清单。",
                    recommendation="恢复受控 git.diff 工具后重新评审。",
                )
            )
        else:
            pending = [
                call for call in calls if call.call_id not in evidence
            ]
            if pending:
                return calls_result(pending)
            paired = [evidence[call.call_id] for call in calls]
            tool_calls = [tool_call_evidence(item) for item in paired]
            tool_blocked = any(
                item.status != "succeeded" for item in paired
            )
            evidence_blocked = False
            if not tool_blocked:
                evidence_blocked, evidence_issues = inspect_reviewer_diff(
                    data,
                    paired[0],
                    start_index=len(issues) + 1,
                )
                issues.extend(evidence_issues)
            verdict = (
                "blocked"
                if tool_blocked or evidence_blocked
                else "approved"
            )
    for result in data.acceptance_evidence:
        if result.status != "satisfied":
            issues.append(
                ReviewIssue(
                    id=f"ISSUE-{len(issues) + 1:03d}",
                    severity="high" if result.status == "missing" else "medium",
                    message=f"{result.criterion_id} 未满足。",
                    recommendation=result.notes,
                )
            )
    if data.test_report.status != "passed":
        issues.append(
            ReviewIssue(
                id=f"ISSUE-{len(issues) + 1:03d}",
                severity="high",
                message="真实测试报告未通过。",
                recommendation="修复失败测试并重新执行 Tester Agent。",
            )
        )
    if issues and verdict != "blocked":
        verdict = "changes_requested"
    return final_result(
        output_model,
        ReviewerAgentOutput(
            task_id=data.task_id,
            development_plan_id=data.development_plan_id,
            summary=(
                f"Reviewer 已核对 {len(data.acceptance_evidence)} 项 AC "
                "与真实测试结果。"
            ),
            verdict=verdict,
            acceptance_results=data.acceptance_evidence,
            issues=issues,
            changed_files=data.changed_files,
            tool_calls=tool_calls,
            proceed_to_security=verdict == "approved",
            risk_level=data.risk_level,
        ),
    )


def security_exchange(data, output_model, conversation, evidence, tool_names):
    """执行本地扫描并依据真实 findings 形成 PR 门禁。"""

    calls = tool_command_calls("security", data.scan_commands, conversation)
    missing = missing_tool_names(calls, tool_names)
    if missing:
        return final_result(
            output_model,
            SecurityAgentOutput(
                task_id=data.task_id,
                development_plan_id=data.development_plan_id,
                summary="Security 所需工具未进入稳定工具清单。",
                verdict="blocked",
                remaining_risks=[f"缺少工具：{name}" for name in missing],
                blocking=True,
                risk_level=data.risk_level,
            ),
        )
    pending = [call for call in calls if call.call_id not in evidence]
    if pending:
        return calls_result(pending)
    paired = [evidence[call.call_id] for call in calls]
    executions = [
        command_execution(item, plan)
        for item, plan in zip(paired, data.scan_commands, strict=True)
    ]
    findings = security_findings(paired)
    incomplete = [
        item
        for item in paired
        if item.status != "succeeded" or item.error_code is not None
    ]
    skipped_risks = _skipped_dependency_risks(paired)
    severe = any(item.severity in {"high", "critical"} for item in findings)
    if severe:
        verdict = "failed"
        blocking = True
    elif incomplete or skipped_risks:
        verdict = "partial"
        blocking = False
    else:
        verdict = "passed"
        blocking = False
    return final_result(
        output_model,
        SecurityAgentOutput(
            task_id=data.task_id,
            development_plan_id=data.development_plan_id,
            summary=(
                f"Security 已执行 {len(executions)} 条真实扫描命令并解析 "
                f"{len(findings)} 项发现。"
            ),
            verdict=verdict,
            scanners=executions,
            findings=findings,
            tool_calls=[tool_call_evidence(item) for item in paired],
            remaining_risks=[
                *failure_summaries(incomplete),
                *skipped_risks,
            ],
            blocking=blocking,
            risk_level=security_risk(data.risk_level, findings),
        ),
    )


def _skipped_dependency_risks(items) -> list[str]:
    """把 pip-audit 明确跳过的依赖保留为 non-blocking 剩余风险。"""

    risks = []
    for item in items:
        skipped = result_details(item).get("skipped_dependencies")
        if not isinstance(skipped, list):
            continue
        for dependency in skipped:
            if not isinstance(dependency, dict):
                continue
            name = str(dependency.get("name") or "unknown")
            reason = str(
                dependency.get("reason")
                or "pip-audit 未提供跳过原因"
            )
            risks.append(f"pip-audit 跳过依赖 {name}：{reason}")
    return risks
