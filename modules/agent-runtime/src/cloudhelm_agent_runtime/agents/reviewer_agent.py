"""Reviewer Agent。"""

from cloudhelm_agent_runtime.agents.tool_agent import run_tool_agent
from cloudhelm_agent_runtime.instructions import allowed_tools_for
from cloudhelm_agent_runtime.providers.base import StructuredAgentProvider
from cloudhelm_agent_runtime.providers.contracts import ProviderConversation
from cloudhelm_agent_runtime.providers.exchange import ToolExecutor
from cloudhelm_agent_runtime.providers.tools import ProviderToolDefinition
from cloudhelm_agent_runtime.schemas.review_report import (
    ReviewerAgentInput,
    ReviewerAgentOutput,
)


class ReviewerAgent:
    """审查真实 diff、AC 和测试报告。"""

    agent_type = "reviewer"
    allowed_tools = allowed_tools_for(agent_type)

    def __init__(self, provider: StructuredAgentProvider) -> None:
        self.provider = provider

    def run(
        self,
        payload: ReviewerAgentInput,
        *,
        conversation: ProviderConversation,
        tools: tuple[ProviderToolDefinition, ...] | list[ProviderToolDefinition],
        tool_executor: ToolExecutor | None,
    ) -> ReviewerAgentOutput:
        """执行只读工具循环并校验评审结论。"""

        return ReviewerAgentOutput.model_validate(
            run_tool_agent(
                self.provider,
                self.agent_type,
                payload,
                ReviewerAgentOutput,
                conversation=conversation,
                tools=tools,
                tool_executor=tool_executor,
            )
        )
