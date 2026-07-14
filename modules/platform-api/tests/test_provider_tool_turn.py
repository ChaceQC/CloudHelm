"""确定性多工具步骤的单 conversation turn 白盒测试。"""

from __future__ import annotations

import json

import pytest

from cloudhelm_agent_runtime.providers import (
    ProviderConversation,
    ProviderToolCall,
    ProviderToolExecutionResult,
)
from cloudhelm_platform_api.services.provider_tool_turn import (
    OrchestratedToolTurn,
)


def test_multiple_tool_calls_commit_as_one_ordered_turn() -> None:
    """同一 step 的多个 call/output 必须配对且只增加一个 turn。"""

    conversation = ProviderConversation(conversation_id="root-turn-test")
    turn = OrchestratedToolTurn(
        agent_type="coder",
        step_name="finalize_local_pull_request",
        step_purpose="完成 Git 状态、diff、commit 与 patch 门禁。",
    )
    turn.add(
        ProviderToolCall(
            call_id="call-status",
            name="git.status",
            arguments={},
        ),
        ProviderToolExecutionResult(
            status="succeeded",
            result={"summary": "工作区存在变更。"},
        ),
        purpose="读取工作区状态。",
    )
    turn.add(
        ProviderToolCall(
            call_id="call-diff",
            name="git.diff",
            arguments={"include_untracked": True},
        ),
        ProviderToolExecutionResult(
            status="succeeded",
            result={"summary": "已读取真实 diff。"},
        ),
        purpose="读取真实 diff。",
    )

    assert conversation.turn_count == 0
    assert conversation.items == []
    assert turn.call_count == 2
    assert turn.status == "succeeded"

    turn.commit(
        conversation,
        summary="Git 只读门禁通过。",
    )

    assert conversation.turn_count == 1
    assert [item["type"] for item in conversation.items] == [
        "message",
        "function_call",
        "function_call_output",
        "function_call",
        "function_call_output",
        "message",
    ]
    paired_call_ids = [
        item["call_id"]
        for item in conversation.items
        if item["type"] in {"function_call", "function_call_output"}
    ]
    assert paired_call_ids == [
        "call-status",
        "call-status",
        "call-diff",
        "call-diff",
    ]


def test_failed_tool_chain_commits_one_final_failure_summary() -> None:
    """工具失败仍可形成有序证据与一个最终失败摘要。"""

    conversation = ProviderConversation(conversation_id="root-failed-turn")
    turn = OrchestratedToolTurn(
        agent_type="tester",
        step_name="run_tester",
        step_purpose="运行真实 pytest 并保存报告。",
    )
    turn.add(
        ProviderToolCall(
            call_id="call-pytest",
            name="test.run_pytest",
            arguments={"profile": "sample"},
        ),
        ProviderToolExecutionResult(
            status="failed",
            result={"summary": "pytest 返回失败。"},
            error_code="test_failed",
        ),
        purpose="运行 pytest。",
    )

    assert turn.status == "failed"
    turn.commit(
        conversation,
        summary="测试未通过，工作流回到 Implementing。",
    )

    assert conversation.turn_count == 1
    final_item = conversation.items[-1]
    final_payload = json.loads(final_item["content"][0]["text"])
    assert final_payload["status"] == "failed"
    assert final_payload["summary"] == (
        "测试未通过，工作流回到 Implementing。"
    )
    assert final_payload["tools"] == [
        {
            "call_id": "call-pytest",
            "error_code": "test_failed",
            "purpose": "运行 pytest。",
            "status": "failed",
            "tool": "test.run_pytest",
        }
    ]

    with pytest.raises(ValueError, match="already committed"):
        turn.commit(conversation, summary="重复提交")
