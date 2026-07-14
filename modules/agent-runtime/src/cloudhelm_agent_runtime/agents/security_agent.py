"""Security Agent。"""

from cloudhelm_agent_runtime.agents.tool_agent import run_tool_agent
from cloudhelm_agent_runtime.instructions import allowed_tools_for
from cloudhelm_agent_runtime.providers.base import StructuredAgentProvider
from cloudhelm_agent_runtime.providers.contracts import ProviderConversation
from cloudhelm_agent_runtime.providers.exchange import ToolExecutor
from cloudhelm_agent_runtime.providers.tools import ProviderToolDefinition
from cloudhelm_agent_runtime.schemas.security_report import (
    SecurityAgentInput,
    SecurityAgentOutput,
)


class SecurityAgent:
    """运行真实本地安全扫描并形成阻断结论。"""

    agent_type = "security"
    allowed_tools = allowed_tools_for(agent_type)

    def __init__(self, provider: StructuredAgentProvider) -> None:
        self.provider = provider

    def run(
        self,
        payload: SecurityAgentInput,
        *,
        conversation: ProviderConversation,
        tools: tuple[ProviderToolDefinition, ...] | list[ProviderToolDefinition],
        tool_executor: ToolExecutor | None,
    ) -> SecurityAgentOutput:
        """执行安全工具循环并校验报告。"""

        return SecurityAgentOutput.model_validate(
            run_tool_agent(
                self.provider,
                self.agent_type,
                payload,
                SecurityAgentOutput,
                conversation=conversation,
                tools=tools,
                tool_executor=tool_executor,
            )
        )
