"""M6 工具型 Agent 的共享运行入口。"""

from __future__ import annotations

from pydantic import BaseModel

from cloudhelm_agent_runtime.providers.base import (
    AgentProviderError,
    StructuredAgentProvider,
    ToolCapableStructuredAgentProvider,
)
from cloudhelm_agent_runtime.providers.contracts import ProviderConversation
from cloudhelm_agent_runtime.providers.exchange import (
    ToolExecutor,
    run_tool_capable_turn,
)
from cloudhelm_agent_runtime.providers.tools import ProviderToolDefinition


def run_tool_agent(
    provider: StructuredAgentProvider,
    agent_type: str,
    payload: BaseModel,
    output_model: type[BaseModel],
    *,
    conversation: ProviderConversation,
    tools: tuple[ProviderToolDefinition, ...] | list[ProviderToolDefinition],
    tool_executor: ToolExecutor | None,
) -> BaseModel:
    """通过通用工具循环运行 Agent，并返回专属 Pydantic 输出。"""

    if not isinstance(provider, ToolCapableStructuredAgentProvider):
        raise AgentProviderError(
            f"provider {provider.name} does not support tool-capable agents"
        )
    raw = run_tool_capable_turn(
        provider,
        agent_type,
        payload,
        output_model,
        conversation=conversation,
        tools=tools,
        tool_executor=tool_executor,
    )
    return output_model.model_validate(raw)
