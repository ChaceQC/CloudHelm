"""M6 本地开发 API 响应组装。"""

from cloudhelm_platform_api.models.task import Task
from cloudhelm_platform_api.schemas.agent_run import AgentRunRead
from cloudhelm_platform_api.schemas.artifact import artifact_to_read
from cloudhelm_platform_api.schemas.local_development import (
    LocalDevelopmentStepRead,
)
from cloudhelm_platform_api.schemas.pull_request_record import (
    pull_request_record_to_read,
)
from cloudhelm_platform_api.schemas.task import TaskRead
from cloudhelm_platform_api.services.local_development_result import (
    LocalDevelopmentResult,
)


def build_local_development_step(
    task: Task,
    result: LocalDevelopmentResult,
) -> LocalDevelopmentStepRead:
    """把单步 ORM/DTO 结果转换为稳定公开响应。"""

    return LocalDevelopmentStepRead(
        task=TaskRead.model_validate(task),
        action=result.action,
        message=result.message,
        agent_run=(
            AgentRunRead.model_validate(result.agent_run)
            if result.agent_run is not None
            else None
        ),
        tool_calls=result.tool_calls,
        artifacts=[
            artifact_to_read(artifact) for artifact in result.artifacts
        ],
        pull_request_record=(
            pull_request_record_to_read(result.pull_request_record)
            if result.pull_request_record is not None
            else None
        ),
        gate_evidence=result.gate_evidence,
    )
