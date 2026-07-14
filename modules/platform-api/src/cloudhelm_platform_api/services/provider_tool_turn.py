"""把一个确定性工具步骤聚合为单个 Task root conversation turn。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from cloudhelm_agent_runtime.providers import (
    ProviderConversation,
    ProviderToolCall,
    ProviderToolExecutionResult,
    execution_result_item,
)
from cloudhelm_agent_runtime.providers.contracts import (
    assistant_message_item,
    developer_message_item,
)


@dataclass(slots=True)
class OrchestratedToolTurn:
    """聚合一个 Agent step 内按顺序执行的全部 call/output。

    调用方先通过 :meth:`add` 追加真实 Tool Gateway 结果，最后无论成功或
    失败都只调用一次 :meth:`commit`。这样一个工作流步骤只增加一个逻辑
    conversation turn，同时保留每个 call_id 的顺序和配对关系。
    """

    agent_type: str
    step_name: str
    step_purpose: str
    _exchange_items: list[dict] = field(default_factory=list)
    _tool_summaries: list[dict] = field(default_factory=list)
    _call_ids: set[str] = field(default_factory=set)
    _committed: bool = False

    def __post_init__(self) -> None:
        """拒绝无法形成审计上下文的空步骤标识。"""

        if not self.agent_type.strip():
            raise ValueError("orchestrated tool turn requires agent_type")
        if not self.step_name.strip():
            raise ValueError("orchestrated tool turn requires step_name")
        if not self.step_purpose.strip():
            raise ValueError("orchestrated tool turn requires step_purpose")

    def add(
        self,
        call: ProviderToolCall,
        result: ProviderToolExecutionResult,
        *,
        purpose: str,
    ) -> None:
        """按实际执行顺序追加一个 call/output 配对。"""

        if self._committed:
            raise ValueError("orchestrated tool turn is already committed")
        if not purpose.strip():
            raise ValueError("orchestrated tool call requires purpose")
        if call.call_id in self._call_ids:
            raise ValueError(
                f"duplicate orchestrated tool call_id: {call.call_id}"
            )
        self._call_ids.add(call.call_id)
        self._exchange_items.extend(
            [
                _call_item(call),
                execution_result_item(call, result),
            ]
        )
        self._tool_summaries.append(
            {
                "call_id": call.call_id,
                "tool": call.name,
                "purpose": purpose,
                "status": result.status,
                "error_code": result.error_code,
            }
        )

    def commit(
        self,
        conversation: ProviderConversation,
        *,
        summary: str,
        response_id: str | None = None,
    ) -> None:
        """追加最终摘要，并把聚合内容一次性提交为一个逻辑 turn。"""

        if self._committed:
            raise ValueError("orchestrated tool turn is already committed")
        if not self._exchange_items:
            raise ValueError("orchestrated tool turn requires at least one call")
        if not summary.strip():
            raise ValueError("orchestrated tool turn requires final summary")

        final_payload = {
            "schema_version": "orchestrated-tool-turn-v1",
            "agent_type": self.agent_type,
            "step_name": self.step_name,
            "status": self.status,
            "summary": summary,
            "tools": self._tool_summaries,
        }
        input_payload = {
            "schema_version": "orchestrated-tool-step-v1",
            "agent_type": self.agent_type,
            "step_name": self.step_name,
            "purpose": self.step_purpose,
        }
        conversation.append_turn(
            developer_message_item(
                "<orchestrated_tool_step>\n"
                f"{json.dumps(input_payload, ensure_ascii=False, sort_keys=True)}"
                "\n</orchestrated_tool_step>"
            ),
            [
                *self._exchange_items,
                assistant_message_item(
                    json.dumps(
                        final_payload,
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                ),
            ],
            response_id=response_id,
        )
        self._committed = True

    @property
    def status(self) -> str:
        """汇总工具结果状态，失败优先于等待审批和成功。"""

        statuses = {
            str(item["status"]) for item in self._tool_summaries
        }
        if "failed" in statuses:
            return "failed"
        if "waiting_approval" in statuses:
            return "waiting_approval"
        return "succeeded"

    @property
    def call_count(self) -> int:
        """返回已聚合的工具调用数量。"""

        return len(self._tool_summaries)


def append_orchestrated_tool_turn(
    conversation: ProviderConversation,
    *,
    agent_type: str,
    call: ProviderToolCall,
    result: ProviderToolExecutionResult,
    purpose: str,
) -> None:
    """兼容单工具步骤；多工具步骤应复用一个聚合器后统一 commit。"""

    turn = OrchestratedToolTurn(
        agent_type=agent_type,
        step_name=call.name,
        step_purpose=purpose,
    )
    turn.add(call, result, purpose=purpose)
    turn.commit(
        conversation,
        summary=str(
            result.result.get("summary")
            or f"{call.name} 执行状态：{result.status}"
        ),
    )


def _call_item(call: ProviderToolCall) -> dict:
    """把 ProviderToolCall 转为可回放的 Responses call item。"""

    item = {
        "type": call.item_type,
        "name": call.name,
        "call_id": call.call_id,
        "status": "completed",
    }
    encoded_arguments = json.dumps(
        call.arguments,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    if call.item_type == "custom_tool_call":
        item["input"] = encoded_arguments
    else:
        item["arguments"] = encoded_arguments
    return item
