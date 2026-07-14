"""LocalStructuredProvider 工具计划与输出组装辅助。"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from cloudhelm_agent_runtime.providers.contracts import (
    ProviderConversation,
    assistant_message_item,
)
from cloudhelm_agent_runtime.providers.exchange import ProviderExchangeResult
from cloudhelm_agent_runtime.providers.local_tool_evidence import (
    LocalToolEvidence,
    result_details,
)
from cloudhelm_agent_runtime.schemas.agent_io import ChangedFile, RiskLevel
from cloudhelm_agent_runtime.schemas.security_report import SecurityFinding


@dataclass(frozen=True, slots=True)
class PlannedLocalCall:
    """Local Provider 根据真实输入形成的一次确定性工具请求。"""

    call_id: str
    name: str
    arguments: dict[str, Any]

    def response_item(self) -> dict[str, Any]:
        """转换为可重放 Responses function_call。"""

        return {
            "type": "function_call",
            "name": self.name,
            "arguments": json.dumps(
                self.arguments,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            "call_id": self.call_id,
            "status": "completed",
        }


def write_calls(agent_type, plans, conversation, *, start=1):
    """把显式文件计划转换为 repo.write_file 调用。"""

    return [
        PlannedLocalCall(
            call_id=call_id(conversation, agent_type, index),
            name="repo.write_file",
            arguments={
                "path": plan.path,
                "content": plan.content,
                "mode": "replace",
                "create_parent": plan.create_parent,
            },
        )
        for index, plan in enumerate(plans, start=start)
    ]


def command_calls(agent_type, plans, conversation, *, start=1):
    """把显式命令计划转换为 sandbox.run_command 调用。"""

    return [
        PlannedLocalCall(
            call_id=call_id(conversation, agent_type, index),
            name="sandbox.run_command",
            arguments={
                "cwd": plan.cwd,
                "command": plan.command,
                "timeout_seconds": plan.timeout_seconds,
            },
        )
        for index, plan in enumerate(plans, start=start)
    ]


def tool_command_calls(agent_type, plans, conversation, *, start=1):
    """把领域工具计划转换为对应 function call。"""

    return [
        PlannedLocalCall(
            call_id=call_id(conversation, agent_type, index),
            name=plan.tool_name,
            arguments=plan.arguments,
        )
        for index, plan in enumerate(plans, start=start)
    ]


def changed_files(plans, calls, evidence):
    """只把真实成功写入映射为 ChangedFile。"""

    changed = []
    for plan, call in zip(plans, calls, strict=True):
        item = evidence.get(call.call_id)
        if item is None or item.status != "succeeded":
            continue
        details = result_details(item)
        sha256 = details.get("sha256")
        if not isinstance(sha256, str) or not re.fullmatch(
            r"sha256:[0-9a-f]{64}",
            sha256,
        ):
            sha256 = None
        changed.append(
            ChangedFile(
                path=plan.path,
                operation="created" if plan.operation == "create" else "updated",
                intent=plan.purpose,
                tool_call_id=(
                    str(item.result.get("tool_call_id"))
                    if item.result.get("tool_call_id") is not None
                    else None
                ),
                sha256=sha256,
            )
        )
    return changed


def security_findings(items: list[LocalToolEvidence]) -> list[SecurityFinding]:
    """从结构化扫描结果提取并重新编号发现项。"""

    findings = []
    valid_severities = {"info", "low", "medium", "high", "critical"}
    for item in items:
        raw = result_details(item).get("findings")
        if not isinstance(raw, list):
            continue
        for candidate in raw:
            if not isinstance(candidate, dict):
                continue
            severity = str(
                candidate.get("severity")
                or (
                    "high"
                    if item.call.name == "security.run_pip_audit"
                    else "info"
                )
            ).lower()
            if severity not in valid_severities:
                severity = "info"
            findings.append(
                SecurityFinding(
                    id=f"FINDING-{len(findings) + 1:03d}",
                    scanner=str(candidate.get("scanner") or item.call.name),
                    rule_id=str(
                        candidate.get("rule_id")
                        or candidate.get("id")
                        or "unknown"
                    ),
                    severity=severity,
                    path=(
                        str(candidate["path"])
                        if candidate.get("path") is not None
                        else None
                    ),
                    line=(
                        int(candidate["line"])
                        if isinstance(candidate.get("line"), int)
                        else None
                    ),
                    message=str(
                        candidate.get("message")
                        or candidate.get("description")
                        or "扫描器未提供详情。"
                    ),
                )
            )
    return findings


def security_risk(
    current: RiskLevel,
    findings: list[SecurityFinding],
) -> RiskLevel:
    """按真实发现严重级别提高风险等级。"""

    order = list(RiskLevel)
    required = current
    if any(item.severity == "critical" for item in findings):
        required = RiskLevel.L3
    elif any(item.severity == "high" for item in findings):
        required = RiskLevel.L2
    return required if order.index(required) >= order.index(current) else current


def failure_summaries(items: list[LocalToolEvidence]) -> list[str]:
    """形成真实工具失败摘要。"""

    return [
        str(
            item.result.get("summary")
            or item.error_code
            or f"{item.call.name} 返回 {item.status}"
        )
        for item in items
    ]


def exit_code(item: LocalToolEvidence) -> int | None:
    """读取真实命令退出码。"""

    value = result_details(item).get("exit_code")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def sum_optional(executions, field_name):
    """只对真实存在的测试计数求和。"""

    values = [
        getattr(item, field_name)
        for item in executions
        if getattr(item, field_name) is not None
    ]
    return sum(values) if values else None


def missing_tool_names(calls, tool_names):
    """返回调用计划中未声明的稳定工具名。"""

    return sorted({call.name for call in calls if call.name not in tool_names})


def call_id(
    conversation: ProviderConversation,
    agent_type: str,
    index: int,
) -> str:
    """按 conversation、逻辑 turn、角色和序号生成稳定 call ID。"""

    identity = hashlib.sha256(
        (
            f"{conversation.conversation_id}:"
            f"{conversation.turn_count + 1}:{agent_type}"
        ).encode()
    ).hexdigest()[:12]
    return f"call_{identity}_{index:03d}"


def calls_result(calls) -> ProviderExchangeResult:
    """返回工具-only exchange。"""

    return ProviderExchangeResult.from_response(
        [call.response_item() for call in calls],
        output_text=None,
    )


def final_result(output_model, output) -> ProviderExchangeResult:
    """校验角色输出并构造最终 assistant message。"""

    validated = output_model.model_validate(output)
    text = validated.model_dump_json()
    return ProviderExchangeResult.from_response(
        [assistant_message_item(text)],
        output_text=text,
    )
