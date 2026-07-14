"""Scaffold Agent。"""

from cloudhelm_agent_runtime.agents.tool_agent import run_tool_agent
from cloudhelm_agent_runtime.instructions import allowed_tools_for
from cloudhelm_agent_runtime.providers.base import StructuredAgentProvider
from cloudhelm_agent_runtime.providers.contracts import ProviderConversation
from cloudhelm_agent_runtime.providers.exchange import ToolExecutor
from cloudhelm_agent_runtime.providers.tools import ProviderToolDefinition
from cloudhelm_agent_runtime.schemas.scaffold import (
    ScaffoldAgentInput,
    ScaffoldAgentOutput,
)


class ScaffoldAgent:
    """根据显式文件计划创建项目或模块骨架。"""

    agent_type = "scaffold"
    allowed_tools = allowed_tools_for(agent_type)

    def __init__(self, provider: StructuredAgentProvider) -> None:
        self.provider = provider

    def run(
        self,
        payload: ScaffoldAgentInput,
        *,
        conversation: ProviderConversation,
        tools: tuple[ProviderToolDefinition, ...] | list[ProviderToolDefinition],
        tool_executor: ToolExecutor | None,
    ) -> ScaffoldAgentOutput:
        """执行真实工具循环并校验 Scaffold 输出。"""

        return ScaffoldAgentOutput.model_validate(
            run_tool_agent(
                self.provider,
                self.agent_type,
                payload,
                ScaffoldAgentOutput,
                conversation=conversation,
                tools=tools,
                tool_executor=tool_executor,
            )
        )
