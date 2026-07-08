"""Requirement Agent。

职责：读取真实 Task 输入，生成需求规格、约束和验收标准。
输入：`RequirementAgentInput`。
输出：`RequirementAgentOutput`。
允许工具：M4 阶段无真实外部工具；后续只允许 `requirement.parse` 和
`spec.update` 通过 Tool Gateway 接入。
"""

from cloudhelm_agent_runtime.providers.base import StructuredAgentProvider
from cloudhelm_agent_runtime.schemas.requirement import RequirementAgentInput, RequirementAgentOutput


class RequirementAgent:
    """需求规格化 Agent。"""

    agent_type = "requirement"
    allowed_tools = ("requirement.parse", "spec.update")

    def __init__(self, provider: StructuredAgentProvider) -> None:
        self.provider = provider

    def run(self, payload: RequirementAgentInput) -> RequirementAgentOutput:
        """生成并校验需求规格输出。"""

        raw = self.provider.generate(self.agent_type, payload, RequirementAgentOutput)
        return RequirementAgentOutput.model_validate(raw)
