"""M6 Local Development Workflow API DTO。"""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from cloudhelm_platform_api.schemas.agent_run import AgentRunRead
from cloudhelm_platform_api.schemas.artifact import ArtifactRead
from cloudhelm_platform_api.schemas.pull_request_record import (
    PullRequestRecordRead,
)
from cloudhelm_platform_api.schemas.task import TaskRead
from cloudhelm_platform_api.schemas.tool_call import ToolCallRead


class LocalDevelopmentActionRequest(BaseModel):
    """启动或推进本地开发闭环的请求体。"""

    actor_id: str = Field(
        default="control-console",
        min_length=1,
        max_length=160,
        description="操作人或调用组件标识。",
    )
    reason: str | None = Field(
        default=None,
        max_length=2000,
        description="推进原因。",
    )


class LocalDevelopmentStateRead(BaseModel):
    """任务当前 M6 本地开发状态摘要。"""

    task_id: UUID
    current_phase: str
    next_action: str
    development_plan_id: UUID
    active_agent_run_id: UUID | None = None
    latest_artifact_ids: dict[str, UUID] = Field(default_factory=dict)
    latest_pull_request_record_id: UUID | None = None


class LocalDevelopmentStepRead(BaseModel):
    """一次本地开发 run-next 的可审计结果。"""

    task: TaskRead
    action: str
    message: str
    agent_run: AgentRunRead | None = None
    tool_calls: list[ToolCallRead] = Field(default_factory=list)
    artifacts: list[ArtifactRead] = Field(default_factory=list)
    pull_request_record: PullRequestRecordRead | None = None
    gate_evidence: dict[str, Any] = Field(default_factory=dict)
