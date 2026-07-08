"""Architect Agent。

职责：基于已持久化 RequirementSpec 生成技术设计、OpenAPI 草案、DB schema
草案和风险点。
输入：`ArchitectAgentInput`。
输出：`ArchitectAgentOutput`。
允许工具：M4 阶段不执行工具；后续设计工具必须经 Tool Gateway。
"""

from cloudhelm_agent_runtime.providers.base import StructuredAgentProvider
from cloudhelm_agent_runtime.schemas.design import ArchitectAgentInput, ArchitectAgentOutput


class ArchitectAgent:
    """技术设计 Agent。"""

    agent_type = "architect"
    allowed_tools = ("design.generate", "spec.update")

    def __init__(self, provider: StructuredAgentProvider) -> None:
        self.provider = provider

    def run(self, payload: ArchitectAgentInput) -> ArchitectAgentOutput:
        """生成并校验技术设计输出。"""

        raw = self.provider.generate(self.agent_type, payload, ArchitectAgentOutput)
        return ArchitectAgentOutput.model_validate(raw)
