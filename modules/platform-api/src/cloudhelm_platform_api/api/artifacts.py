"""M6 Artifact 查询 API。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from cloudhelm_platform_api.api.deps import DbSession, pagination_params
from cloudhelm_platform_api.schemas.artifact import (
    ArtifactDetailRead,
    ArtifactRead,
    ArtifactStatus,
)
from cloudhelm_platform_api.schemas.common import PageResponse
from cloudhelm_platform_api.services.artifact_service import ArtifactService

router = APIRouter(tags=["artifacts"])


@router.get(
    "/api/tasks/{task_id}/artifacts",
    response_model=PageResponse[ArtifactRead],
    summary="分页读取任务 Artifact",
)
def list_artifacts(
    task_id: UUID,
    db: DbSession,
    page: Annotated[tuple[int, str | None], Depends(pagination_params)],
    artifact_type: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=80,
            description="按 Artifact 类型过滤。",
        ),
    ] = None,
    artifact_status: Annotated[
        ArtifactStatus | None,
        Query(
            alias="status",
            description="按 Artifact 可用状态过滤。",
        ),
    ] = None,
) -> PageResponse[ArtifactRead]:
    """读取指定 Task 的安全 Artifact 元数据。"""

    limit, cursor = page
    return ArtifactService(db).list_by_task(
        task_id,
        limit,
        cursor,
        artifact_type=artifact_type,
        status=(
            artifact_status.value
            if artifact_status is not None
            else None
        ),
    )


@router.get(
    "/api/artifacts/{artifact_id}",
    response_model=ArtifactDetailRead,
    summary="读取 Artifact 安全详情",
)
def get_artifact(
    artifact_id: UUID,
    db: DbSession,
) -> ArtifactDetailRead:
    """读取单个 Artifact，并返回经 hash 校验和大小限制的安全预览。"""

    return ArtifactService(db).get_detail(artifact_id)
