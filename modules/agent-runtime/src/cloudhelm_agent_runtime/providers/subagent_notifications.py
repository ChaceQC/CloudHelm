"""Subagent 最终摘要通知的有界 ResponseItem 契约。"""

import json
from typing import Any

from cloudhelm_agent_runtime.providers.contracts import developer_message_item

MAX_SUBAGENT_SUMMARY_CHARS = 4000


def subagent_notification_item(
    *,
    conversation_id: str,
    agent_role: str,
    status: str,
    summary: str,
) -> dict[str, Any]:
    """把子 Agent 最终结果作为结构化通知返回父会话。

    子会话的 encrypted reasoning、tool call 和 tool output 不会复制到父线程。
    """

    normalized_summary = summary.strip()
    if not normalized_summary:
        raise ValueError("subagent notification requires a non-empty summary")
    if len(normalized_summary) > MAX_SUBAGENT_SUMMARY_CHARS:
        raise ValueError(
            "subagent notification summary exceeds 4000 characters"
        )
    payload = {
        "conversation_id": conversation_id,
        "agent_role": agent_role,
        "status": status,
        "summary": normalized_summary,
    }
    text = (
        "<subagent_notification>\n"
        f"{json.dumps(payload, ensure_ascii=False, sort_keys=True)}\n"
        "</subagent_notification>"
    )
    return developer_message_item(text)
