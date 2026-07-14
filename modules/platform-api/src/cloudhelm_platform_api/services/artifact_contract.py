"""Artifact 生产者引用与幂等身份校验。"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from cloudhelm_platform_api.models.artifact import Artifact
from cloudhelm_platform_api.repositories.agent_run_repository import (
    AgentRunRepository,
)
from cloudhelm_platform_api.repositories.task_repository import TaskRepository
from cloudhelm_platform_api.repositories.tool_call_repository import (
    ToolCallRepository,
)
from cloudhelm_platform_api.schemas.artifact import (
    ArtifactProducerType,
    ArtifactStatus,
)
from cloudhelm_platform_api.services.exceptions import ServiceError


def validate_artifact_references(
    *,
    task_id: UUID,
    producer_type: ArtifactProducerType,
    agent_run_id: UUID | None,
    tool_call_id: UUID | None,
    tasks: TaskRepository,
    agent_runs: AgentRunRepository,
    tool_calls: ToolCallRepository,
) -> None:
    """校验生产者记录存在、类型互斥且属于同一 Task。"""

    if tasks.get(task_id) is None:
        raise ServiceError("task_not_found", "任务不存在。", 404)
    if producer_type == ArtifactProducerType.SYSTEM:
        if agent_run_id is not None or tool_call_id is not None:
            raise ServiceError(
                "system_artifact_reference_invalid",
                "System Artifact 不能关联 AgentRun 或 ToolCall。",
                409,
            )
        return
    if producer_type == ArtifactProducerType.AGENT:
        if tool_call_id is not None:
            raise ServiceError(
                "agent_artifact_reference_invalid",
                "Agent Artifact 只能关联 AgentRun。",
                409,
            )
        agent_run = (
            agent_runs.get(agent_run_id)
            if agent_run_id is not None
            else None
        )
        if agent_run is None:
            raise ServiceError(
                "agent_run_not_found",
                "Agent Artifact 必须关联真实 AgentRun。",
                404,
            )
        if agent_run.task_id != task_id:
            raise ServiceError(
                "agent_run_task_mismatch",
                "AgentRun 不属于当前 Task。",
                409,
            )
        return
    if producer_type == ArtifactProducerType.TOOL:
        if agent_run_id is not None:
            raise ServiceError(
                "tool_artifact_reference_invalid",
                "Tool Artifact 只能关联 ToolCall。",
                409,
            )
        tool_call = (
            tool_calls.get(tool_call_id)
            if tool_call_id is not None
            else None
        )
        if tool_call is None:
            raise ServiceError(
                "tool_call_not_found",
                "Tool Artifact 必须关联真实 ToolCall。",
                404,
            )
        if tool_call.task_id != task_id:
            raise ServiceError(
                "tool_call_task_mismatch",
                "ToolCall 不属于当前 Task。",
                409,
            )


def ensure_artifact_identity(
    existing: Artifact,
    *,
    digest: str,
    producer_type: ArtifactProducerType,
    artifact_type: str,
    display_name: str,
    media_type: str,
    summary: str,
    metadata_json: dict[str, Any],
    agent_run_id: UUID | None,
    tool_call_id: UUID | None,
) -> None:
    """相同幂等键只能复用完全相同的不可变 Artifact 契约。"""

    expected = {
        "sha256": digest,
        "producer_type": producer_type.value,
        "artifact_type": artifact_type,
        "status": ArtifactStatus.AVAILABLE.value,
        "display_name": display_name,
        "media_type": media_type,
        "summary": summary,
        "metadata_json": metadata_json,
        "agent_run_id": agent_run_id,
        "tool_call_id": tool_call_id,
    }
    actual = {
        field: getattr(existing, field)
        for field in expected
    }
    if actual != expected:
        raise ServiceError(
            "artifact_idempotency_conflict",
            "相同 Artifact 幂等键对应不同内容或不可变契约。",
            409,
        )
