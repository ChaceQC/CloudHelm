"""M4 本地规则化结构化 Provider。

该实现从真实 Task、Requirement 和 Design 字段生成可审查草案，不使用测试
固定返回。它与外部 Provider 共用同一 Conversation 契约，因此普通 Agent
角色切换仍会追加到同一个 Task root conversation。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from cloudhelm_agent_runtime.instructions import build_turn_input_items
from cloudhelm_agent_runtime.providers.base import (
    AgentProviderError,
    ToolCapableStructuredAgentProvider,
)
from cloudhelm_agent_runtime.providers.contracts import (
    ProviderConversation,
    assistant_message_item,
)
from cloudhelm_agent_runtime.providers.exchange import (
    PendingProviderTurn,
    ProviderExchangeResult,
)
from cloudhelm_agent_runtime.providers.local_tool_exchange import (
    local_tool_exchange,
)
from cloudhelm_agent_runtime.providers.tools import ProviderToolDefinition
from cloudhelm_agent_runtime.providers.local_m4_generation import (
    generate_architect,
    generate_planner,
    generate_requirement,
)


class LocalStructuredProvider(ToolCapableStructuredAgentProvider):
    """M4 MVP 本地规则化 provider。"""

    name = "local_structured"
    model_name = "local-rules-m4-v1"

    def generate(
        self,
        agent_type: str,
        payload: BaseModel,
        output_model: type[BaseModel],
        *,
        conversation: ProviderConversation | None = None,
    ) -> dict[str, Any]:
        """按 Agent 类型生成结构化 JSON，并提前执行一次 Pydantic 校验。"""

        self.last_call_metadata = None
        if agent_type == "requirement":
            output = generate_requirement(payload)
        elif agent_type == "architect":
            output = generate_architect(payload)
        elif agent_type == "planner":
            output = generate_planner(payload)
        else:
            raise AgentProviderError(f"unsupported agent type: {agent_type}")
        result = output_model.model_validate(output).model_dump(mode="json")
        if conversation is not None:
            conversation.append_turn(
                build_turn_input_items(agent_type, payload),
                [assistant_message_item(output_model.model_validate(result).model_dump_json())],
            )
        return result

    def exchange(
        self,
        agent_type: str,
        payload: BaseModel,
        output_model: type[BaseModel],
        *,
        conversation: ProviderConversation,
        pending_turn: PendingProviderTurn,
        tools: tuple[ProviderToolDefinition, ...] = (),
    ) -> ProviderExchangeResult:
        """根据真实 payload 发出工具请求，并只汇总真实回填结果。"""

        self.last_call_metadata = None
        return local_tool_exchange(
            agent_type,
            payload,
            output_model,
            conversation=conversation,
            pending_turn=pending_turn,
            tools=tools,
        )
