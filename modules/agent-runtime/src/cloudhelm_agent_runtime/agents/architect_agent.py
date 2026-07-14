"""Architect Agent。

职责：基于已持久化 RequirementSpec 生成技术设计、OpenAPI 草案、DB schema
草案和风险点。
输入：`ArchitectAgentInput`。
输出：`ArchitectAgentOutput`。
允许工具：M4 阶段不执行工具；M5 注册表允许设计渲染和受控仓库只读工具。
"""

from cloudhelm_agent_runtime.providers.base import ProviderConversation, StructuredAgentProvider
from cloudhelm_agent_runtime.instructions import allowed_tools_for
from cloudhelm_agent_runtime.schemas.agent_io import RiskLevel, max_risk_level
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
        output = ArchitectAgentOutput.model_validate(raw)
        required_risk = max_risk_level(
            payload.task_risk_level,
            output.risk_level,
        )
        approval_required = required_risk in {
            RiskLevel.L2,
            RiskLevel.L3,
            RiskLevel.L4,
        }
        return output.model_copy(
            update={
                "risk_level": required_risk,
                "approval_recommended": (
                    output.approval_recommended or approval_required
                ),
            }
        )
