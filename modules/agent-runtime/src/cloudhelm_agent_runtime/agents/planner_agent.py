"""Planner Agent。

职责：基于已生成的 TechnicalDesign 输出开发任务图和风险说明。
输入：`PlannerAgentInput`。
输出：`PlannerAgentOutput`。
允许工具：M4 阶段无真实工具调用，后续只读 repo/spec/logs 等能力必须经
Tool Gateway。
"""

from cloudhelm_agent_runtime.providers.base import StructuredAgentProvider
from cloudhelm_agent_runtime.schemas.development_plan import PlannerAgentInput, PlannerAgentOutput


class PlannerAgent:
    """开发计划 Agent。"""

    agent_type = "planner"
    allowed_tools = ("spec.read", "design.read")

    def __init__(self, provider: StructuredAgentProvider) -> None:
        self.provider = provider

    def run(self, payload: PlannerAgentInput) -> PlannerAgentOutput:
        """生成并校验开发计划输出。"""

        raw = self.provider.generate(self.agent_type, payload, PlannerAgentOutput)
        return PlannerAgentOutput.model_validate(raw)
