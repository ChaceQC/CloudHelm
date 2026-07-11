"""Architect Agent。

职责：基于已持久化 RequirementSpec 生成技术设计、OpenAPI 草案、DB schema
草案和风险点。
输入：`ArchitectAgentInput`。
输出：`ArchitectAgentOutput`。
允许工具：M4 阶段不执行工具；M5 注册表允许设计渲染和受控仓库只读工具。
"""

from cloudhelm_agent_runtime.providers.base import ProviderConversation, StructuredAgentProvider
from cloudhelm_agent_runtime.instructions import allowed_tools_for
from cloudhelm_agent_runtime.schemas.design import ArchitectAgentInput, ArchitectAgentOutput


class ArchitectAgent:
    """技术设计 Agent。"""

    agent_type = "architect"
    allowed_tools = allowed_tools_for(agent_type)

    def __init__(self, provider: StructuredAgentProvider) -> None:
        self.provider = provider

    def run(
        self,
        payload: ArchitectAgentInput,
        conversation: ProviderConversation | None = None,
    ) -> ArchitectAgentOutput:
        """生成并校验技术设计输出。"""

        raw = self.provider.generate(
            self.agent_type,
            payload,
            ArchitectAgentOutput,
            conversation=conversation,
        )
        return ArchitectAgentOutput.model_validate(raw)
