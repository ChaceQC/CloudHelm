"""Requirement Agent。

职责：读取真实 Task 输入，生成需求规格、约束和验收标准。
输入：`RequirementAgentInput`。
输出：`RequirementAgentOutput`。
允许工具：M4 阶段不执行工具；M5 注册表只允许需求整理和受控仓库只读
工具，且真实调用必须通过 Tool Gateway。
"""

from cloudhelm_agent_runtime.providers.base import ProviderConversation, StructuredAgentProvider
from cloudhelm_agent_runtime.instructions import allowed_tools_for
from cloudhelm_agent_runtime.schemas.agent_io import max_risk_level
from cloudhelm_agent_runtime.schemas.requirement import RequirementAgentInput, RequirementAgentOutput


class RequirementAgent:
    """需求规格化 Agent。"""

    agent_type = "requirement"
    allowed_tools = allowed_tools_for(agent_type)

    def __init__(self, provider: StructuredAgentProvider) -> None:
        self.provider = provider

    def run(
        self,
        payload: RequirementAgentInput,
        conversation: ProviderConversation | None = None,
    ) -> RequirementAgentOutput:
        """生成并校验需求规格输出。"""

        raw = self.provider.generate(
            self.agent_type,
            payload,
            RequirementAgentOutput,
            conversation=conversation,
        )
        output = RequirementAgentOutput.model_validate(raw)
        required_risk = max_risk_level(payload.risk_level, output.risk_level)
        return output.model_copy(update={"risk_level": required_risk})
