"""Tester Agent。"""

from cloudhelm_agent_runtime.agents.tool_agent import run_tool_agent
from cloudhelm_agent_runtime.instructions import allowed_tools_for
from cloudhelm_agent_runtime.providers.base import StructuredAgentProvider
from cloudhelm_agent_runtime.providers.contracts import ProviderConversation
from cloudhelm_agent_runtime.providers.exchange import ToolExecutor
from cloudhelm_agent_runtime.providers.tools import ProviderToolDefinition
from cloudhelm_agent_runtime.schemas.test_report import (
    TesterAgentInput,
    TesterAgentOutput,
)


class TesterAgent:
    """运行真实测试命令并形成测试报告。"""

    agent_type = "tester"
    allowed_tools = allowed_tools_for(agent_type)

    def __init__(self, provider: StructuredAgentProvider) -> None:
        self.provider = provider

    def run(
        self,
        payload: TesterAgentInput,
        *,
        conversation: ProviderConversation,
        tools: tuple[ProviderToolDefinition, ...] | list[ProviderToolDefinition],
        tool_executor: ToolExecutor | None,
    ) -> TesterAgentOutput:
        """执行测试工具循环并校验报告。"""

        return TesterAgentOutput.model_validate(
            run_tool_agent(
                self.provider,
                self.agent_type,
                payload,
                TesterAgentOutput,
                conversation=conversation,
                tools=tools,
                tool_executor=tool_executor,
            )
        )
