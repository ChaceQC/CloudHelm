"""Planner Agent。

职责：基于已生成的 TechnicalDesign 输出开发任务图和风险说明。
输入：`PlannerAgentInput`。
输出：`PlannerAgentOutput`。
允许工具：M4 阶段无真实工具调用；M5 注册表只开放需求/设计整理和受控
仓库只读工具。
"""

from cloudhelm_agent_runtime.providers.base import ProviderConversation, StructuredAgentProvider
from cloudhelm_agent_runtime.instructions import allowed_tools_for
from cloudhelm_agent_runtime.schemas.development_plan import PlannerAgentInput, PlannerAgentOutput


class PlannerAgent:
    """开发计划 Agent。"""

    agent_type = "planner"
    allowed_tools = allowed_tools_for(agent_type)

    def __init__(self, provider: StructuredAgentProvider) -> None:
        self.provider = provider

    def run(
        self,
        payload: PlannerAgentInput,
        conversation: ProviderConversation | None = None,
    ) -> PlannerAgentOutput:
        """生成并校验开发计划输出。"""

        raw = self.provider.generate(
            self.agent_type,
            payload,
            PlannerAgentOutput,
            conversation=conversation,
        )
        return PlannerAgentOutput.model_validate(raw)
