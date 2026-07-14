"""LocalStructuredProvider 的真实工具结果解析辅助。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from cloudhelm_agent_runtime.providers.exchange import PendingProviderTurn
from cloudhelm_agent_runtime.providers.tools import ProviderToolCall, collect_tool_calls
from cloudhelm_agent_runtime.schemas.agent_io import (
    CommandExecution,
    PlannedCommand,
    ToolCallEvidence,
)


@dataclass(frozen=True, slots=True)
class LocalToolEvidence:
    """一组已配对 function call/output。"""

    call: ProviderToolCall
    status: str
    result: dict[str, Any]
    error_code: str | None


def paired_tool_evidence(pending_turn: PendingProviderTurn) -> dict[str, LocalToolEvidence]:
    """从 pending turn 读取同 `call_id` 的真实工具结果。"""

    calls = {
        call.call_id: call
        for call in collect_tool_calls(pending_turn.exchange_items)
    }
    evidence: dict[str, LocalToolEvidence] = {}
    for item in pending_turn.exchange_items:
        if item.get("type") not in {
            "function_call_output",
            "custom_tool_call_output",
        }:
            continue
        call_id = item.get("call_id")
        if not isinstance(call_id, str) or call_id not in calls:
            continue
        raw_output = item.get("output")
        if not isinstance(raw_output, str):
            continue
        try:
            payload = json.loads(raw_output)
        except json.JSONDecodeError:
            payload = {
                "status": "failed",
                "result": {"summary": "工具结果不是有效 JSON。"},
                "error_code": "invalid_tool_output",
            }
        result = payload.get("result")
        evidence[call_id] = LocalToolEvidence(
            call=calls[call_id],
            status=str(payload.get("status") or "failed"),
            result=result if isinstance(result, dict) else {},
            error_code=(
                str(payload["error_code"])
                if payload.get("error_code") is not None
                else None
            ),
        )
    return evidence


def tool_call_evidence(item: LocalToolEvidence) -> ToolCallEvidence:
    """把真实工具结果投影为 Agent 输出引用。"""

    details = _details(item.result)
    summary = (
        item.result.get("summary")
        or details.get("summary")
        or f"{item.call.name} 返回 {item.status}。"
    )
    return ToolCallEvidence(
        call_id=item.call.call_id,
        tool_name=item.call.name,
        status=item.status,
        tool_call_id=_optional_string(
            item.result.get("tool_call_id") or details.get("tool_call_id")
        ),
        error_code=item.error_code,
        summary=str(summary)[:1000],
    )


def command_execution(
    item: LocalToolEvidence,
    plan: PlannedCommand,
) -> CommandExecution:
    """从 Gateway 结果提取命令、退出码、测试计数和报告引用。"""

    details = _details(item.result)
    return CommandExecution(
        call_id=item.call.call_id,
        tool_call_id=_optional_string(
            item.result.get("tool_call_id") or details.get("tool_call_id")
        ),
        command=plan.command,
        purpose=plan.purpose,
        status=item.status,
        exit_code=_optional_int(details.get("exit_code")),
        passed_count=_optional_int(details.get("passed_count")),
        failed_count=_optional_int(details.get("failed_count")),
        skipped_count=_optional_int(details.get("skipped_count")),
        duration_ms=_optional_int(details.get("duration_ms")),
        report_ref=_optional_string(
            details.get("report_ref")
            or details.get("junit_path")
            or details.get("path")
        ),
        stdout_summary=_optional_string(item.result.get("stdout_summary")),
        stderr_summary=_optional_string(item.result.get("stderr_summary")),
        error_code=item.error_code,
    )


def result_details(item: LocalToolEvidence) -> dict[str, Any]:
    """返回 Gateway result_json 或已是结构化结果的原对象。"""

    return _details(item.result)


def _details(result: dict[str, Any]) -> dict[str, Any]:
    nested = result.get("result_json")
    return nested if isinstance(nested, dict) else result


def _optional_string(value: Any) -> str | None:
    return str(value) if value is not None else None


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.lstrip("-").isdigit():
        return int(value)
    return None
