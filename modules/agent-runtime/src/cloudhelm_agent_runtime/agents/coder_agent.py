"""Coder Agent。"""

from cloudhelm_agent_runtime.agents.tool_agent import run_tool_agent
from cloudhelm_agent_runtime.instructions import allowed_tools_for
from cloudhelm_agent_runtime.providers.base import StructuredAgentProvider
from cloudhelm_agent_runtime.providers.contracts import ProviderConversation
from cloudhelm_agent_runtime.providers.exchange import ToolExecutor
from cloudhelm_agent_runtime.providers.tools import ProviderToolDefinition
from cloudhelm_agent_runtime.schemas.implementation import (
    CoderAgentInput,
    CoderAgentOutput,
)


class CoderAgent:
    """根据已批准计划产生真实代码变更。"""

    agent_type = "coder"
    allowed_tools = allowed_tools_for(agent_type)

    def __init__(self, provider: StructuredAgentProvider) -> None:
        self.provider = provider

    def run(
        self,
        payload: CoderAgentInput,
        *,
        conversation: ProviderConversation,
        tools: tuple[ProviderToolDefinition, ...] | list[ProviderToolDefinition],
        tool_executor: ToolExecutor | None,
    ) -> CoderAgentOutput:
        """执行真实工具循环并校验实现结果。"""

        return CoderAgentOutput.model_validate(
            run_tool_agent(
                self.provider,
                self.agent_type,
                payload,
                CoderAgentOutput,
                conversation=conversation,
                tools=tools,
                tool_executor=tool_executor,
            )
        )
