"""M6 单步执行器与 API service 的内部结果对象。"""

from dataclasses import dataclass, field
from typing import Any

from cloudhelm_platform_api.models.agent_run import AgentRun
from cloudhelm_platform_api.models.artifact import Artifact
from cloudhelm_platform_api.models.pull_request_record import PullRequestRecord
from cloudhelm_platform_api.schemas.tool_call import ToolCallRead


@dataclass(slots=True)
class LocalDevelopmentResult:
    """一个 M6 最小动作产生的记录、证据和目标阶段。"""

    action: str
    message: str
    target_phase: str | None
    agent_run: AgentRun | None = None
    tool_calls: list[ToolCallRead] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)
    pull_request_record: PullRequestRecord | None = None
    gate_evidence: dict[str, Any] = field(default_factory=dict)
