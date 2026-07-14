"""Local Scaffold/Coder 的 workspace、分支、写入与 diff 交换。"""

from cloudhelm_agent_runtime.providers.local_tool_evidence import (
    command_execution,
    result_details,
    tool_call_evidence,
)
from cloudhelm_agent_runtime.providers.local_tool_plans import (
    PlannedLocalCall,
    call_id,
    calls_result,
    changed_files,
    command_calls,
    exit_code,
    failure_summaries,
    final_result,
    missing_tool_names,
    write_calls,
)
from cloudhelm_agent_runtime.schemas.implementation import CoderAgentOutput
from cloudhelm_agent_runtime.schemas.scaffold import ScaffoldAgentOutput


def scaffold_exchange(data, output_model, conversation, evidence, tool_names):
    """通过 scaffold.prepare_workspace 准备真实独立 Git workspace。"""

    prepare = PlannedLocalCall(
        call_id=call_id(conversation, "scaffold", 1),
        name="scaffold.prepare_workspace",
        arguments={
            "template_id": data.template_id,
            "baseline_branch": data.baseline_branch,
        },
    )
    missing = missing_tool_names([prepare], tool_names)
    if missing:
        return final_result(
            output_model,
            ScaffoldAgentOutput(
                task_id=data.task_id,
                development_plan_id=data.development_plan_id,
                step_id=data.step_id,
                summary="Scaffold workspace 工具未进入稳定工具清单。",
                status="blocked",
                blockers=[f"缺少工具：{name}" for name in missing],
                risk_level=data.risk_level,
            ),
        )
    if prepare.call_id not in evidence:
        return calls_result([prepare])
    item = evidence[prepare.call_id]
    if item.status != "succeeded":
        return final_result(
            output_model,
            ScaffoldAgentOutput(
                task_id=data.task_id,
                development_plan_id=data.development_plan_id,
                step_id=data.step_id,
                summary="Scaffold workspace 准备失败。",
                status="blocked",
                tool_calls=[tool_call_evidence(item)],
                blockers=failure_summaries([item]),
                risk_level=data.risk_level,
            ),
        )
    details = result_details(item)
    return final_result(
        output_model,
        ScaffoldAgentOutput(
            task_id=data.task_id,
            development_plan_id=data.development_plan_id,
            step_id=data.step_id,
            summary="Scaffold 已创建或复用受控 sample Git workspace。",
            status="completed",
            workspace_key=_string(details.get("workspace_key")),
            baseline_branch=_string(details.get("baseline_branch")),
            baseline_commit=_string(details.get("baseline_commit")),
            baseline_files=[
                str(path)
                for path in details.get("files", [])
                if isinstance(path, str)
            ],
            tool_calls=[tool_call_evidence(item)],
            risk_level=data.risk_level,
        ),
    )


def coder_exchange(data, output_model, conversation, evidence, tool_names):
    """按 branch -> writes -> verification -> diff 推进 Coder。"""

    branch = PlannedLocalCall(
        call_id=call_id(conversation, "coder", 1),
        name="git.create_branch",
        arguments={"branch_name": data.branch_name},
    )
    missing = missing_tool_names([branch], tool_names)
    if missing:
        return _coder_blocked(data, output_model, missing)
    if branch.call_id not in evidence:
        return calls_result([branch])
    branch_evidence = evidence[branch.call_id]
    if branch_evidence.status != "succeeded":
        return _coder_failure(
            data,
            output_model,
            [branch_evidence],
            "Coder 创建本地开发分支失败。",
        )

    writes = write_calls(
        "coder",
        data.planned_changes,
        conversation,
        start=2,
    )
    missing = missing_tool_names(writes, tool_names)
    if missing:
        return _coder_blocked(data, output_model, missing)
    pending = [call for call in writes if call.call_id not in evidence]
    if pending:
        return calls_result(pending)
    write_evidence = [evidence[call.call_id] for call in writes]
    if any(item.status != "succeeded" for item in write_evidence):
        return _coder_failure(
            data,
            output_model,
            [branch_evidence, *write_evidence],
            "Coder 文件写入未全部成功。",
            changes=changed_files(data.planned_changes, writes, evidence),
        )

    commands = command_calls(
        "coder",
        data.verification_commands,
        conversation,
        start=len(writes) + 2,
    )
    missing = missing_tool_names(commands, tool_names)
    if missing:
        return _coder_blocked(data, output_model, missing)
    pending = [call for call in commands if call.call_id not in evidence]
    if pending:
        return calls_result(pending)
    command_evidence = [evidence[call.call_id] for call in commands]
    command_failures = [
        item
        for item in command_evidence
        if item.status != "succeeded" or exit_code(item) not in {0, None}
    ]
    changes = changed_files(data.planned_changes, writes, evidence)
    if command_failures:
        return _coder_failure(
            data,
            output_model,
            [branch_evidence, *write_evidence, *command_evidence],
            "Coder 验证命令未全部通过。",
            changes=changes,
            verification=[
                command_execution(item, plan)
                for item, plan in zip(
                    command_evidence,
                    data.verification_commands,
                    strict=True,
                )
            ],
        )

    diff = PlannedLocalCall(
        call_id=call_id(
            conversation,
            "coder",
            len(writes) + len(commands) + 2,
        ),
        name="git.diff",
        arguments={
            "paths": [item.path for item in changes],
            "include_untracked": True,
        },
    )
    missing = missing_tool_names([diff], tool_names)
    if missing:
        return _coder_blocked(data, output_model, missing)
    if diff.call_id not in evidence:
        return calls_result([diff])
    diff_evidence = evidence[diff.call_id]
    diff_details = result_details(diff_evidence)
    diff_paths = [
        str(path)
        for path in diff_details.get("changed_files", [])
        if isinstance(path, str)
    ]
    all_evidence = [
        branch_evidence,
        *write_evidence,
        *command_evidence,
        diff_evidence,
    ]
    if diff_evidence.status != "succeeded" or not diff_paths:
        return _coder_failure(
            data,
            output_model,
            all_evidence,
            "Coder 未能生成非空真实 diff。",
            changes=changes,
        )
    return final_result(
        output_model,
        CoderAgentOutput(
            task_id=data.task_id,
            development_plan_id=data.development_plan_id,
            step_ids=data.step_ids,
            summary=f"Coder 已在 {data.branch_name} 产生 {len(diff_paths)} 个真实 diff 文件。",
            status="completed",
            branch_name=data.branch_name,
            diff_paths=diff_paths,
            changed_files=changes,
            verification=[
                command_execution(item, plan)
                for item, plan in zip(
                    command_evidence,
                    data.verification_commands,
                    strict=True,
                )
            ],
            tests_added=[
                item.path for item in changes if "test" in item.path.lower()
            ],
            tool_calls=[
                tool_call_evidence(item) for item in all_evidence
            ],
            risk_level=data.risk_level,
        ),
    )


def _coder_blocked(data, output_model, missing):
    """构造缺少稳定工具时的 Coder 阻断输出。"""

    return final_result(
        output_model,
        CoderAgentOutput(
            task_id=data.task_id,
            development_plan_id=data.development_plan_id,
            step_ids=data.step_ids,
            summary="Coder 所需工具未进入稳定工具清单。",
            status="blocked",
            blockers=[f"缺少工具：{name}" for name in missing],
            risk_level=data.risk_level,
        ),
    )


def _coder_failure(
    data,
    output_model,
    items,
    summary,
    *,
    changes=None,
    verification=None,
):
    """构造具有真实 ToolCall 证据的可恢复 Coder partial 输出。"""

    return final_result(
        output_model,
        CoderAgentOutput(
            task_id=data.task_id,
            development_plan_id=data.development_plan_id,
            step_ids=data.step_ids,
            summary=summary,
            status="partial",
            branch_name=data.branch_name,
            changed_files=changes or [],
            verification=verification or [],
            tool_calls=[tool_call_evidence(item) for item in items],
            blockers=failure_summaries(
                [
                    item
                    for item in items
                    if item.status != "succeeded"
                    or exit_code(item) not in {0, None}
                ]
            )
            or [summary],
            risks=["验证或工具调用未全部成功。"],
            risk_level=data.risk_level,
        ),
    )


def _string(value):
    """把结构化工具字段安全投影为可选字符串。"""

    return str(value) if value is not None else None
