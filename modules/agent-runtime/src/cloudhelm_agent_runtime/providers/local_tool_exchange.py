"""M6 LocalStructuredProvider 的工具请求与真实结果分派。"""

from pydantic import BaseModel

from cloudhelm_agent_runtime.providers.contracts import ProviderConversation
from cloudhelm_agent_runtime.providers.exchange import (
    PendingProviderTurn,
    ProviderExchangeResult,
)
from cloudhelm_agent_runtime.providers.local_quality_exchange import (
    reviewer_exchange,
    security_exchange,
)
from cloudhelm_agent_runtime.providers.local_test_exchange import tester_exchange
from cloudhelm_agent_runtime.providers.local_tool_evidence import (
    paired_tool_evidence,
)
from cloudhelm_agent_runtime.providers.local_write_exchange import (
    coder_exchange,
    scaffold_exchange,
)
from cloudhelm_agent_runtime.providers.tools import ProviderToolDefinition
from cloudhelm_agent_runtime.schemas.implementation import CoderAgentInput
from cloudhelm_agent_runtime.schemas.review_report import ReviewerAgentInput
from cloudhelm_agent_runtime.schemas.scaffold import ScaffoldAgentInput
from cloudhelm_agent_runtime.schemas.security_report import SecurityAgentInput
from cloudhelm_agent_runtime.schemas.test_report import TesterAgentInput


def local_tool_exchange(
    agent_type: str,
    payload: BaseModel,
    output_model: type[BaseModel],
    *,
    conversation: ProviderConversation,
    pending_turn: PendingProviderTurn,
    tools: tuple[ProviderToolDefinition, ...],
) -> ProviderExchangeResult:
    """根据真实 payload 与已回填工具结果产生下一次调用或最终报告。"""

    tool_names = {tool.name for tool in tools}
    evidence = paired_tool_evidence(pending_turn)
    if agent_type == "scaffold":
        return scaffold_exchange(
            ScaffoldAgentInput.model_validate(payload),
            output_model,
            conversation,
            evidence,
            tool_names,
        )
    if agent_type == "coder":
        return coder_exchange(
            CoderAgentInput.model_validate(payload),
            output_model,
            conversation,
            evidence,
            tool_names,
        )
    if agent_type == "tester":
        return tester_exchange(
            TesterAgentInput.model_validate(payload),
            output_model,
            conversation,
            evidence,
            tool_names,
        )
    if agent_type == "reviewer":
        return reviewer_exchange(
            ReviewerAgentInput.model_validate(payload),
            output_model,
            conversation,
            evidence,
            tool_names,
        )
    if agent_type == "security":
        return security_exchange(
            SecurityAgentInput.model_validate(payload),
            output_model,
            conversation,
            evidence,
            tool_names,
        )
    raise ValueError(f"unsupported local tool-capable agent type: {agent_type}")
