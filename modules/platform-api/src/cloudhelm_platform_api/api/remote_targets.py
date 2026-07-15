"""M7 RemoteTarget API 路由。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from cloudhelm_platform_api.api.deps import DbSession, pagination_params
from cloudhelm_platform_api.schemas.common import ErrorResponse, PageResponse
from cloudhelm_platform_api.schemas.remote_target import (
    RemoteTargetCreate,
    RemoteTargetRead,
)
from cloudhelm_platform_api.services.remote_target_service import (
    RemoteTargetService,
)

router = APIRouter(tags=["remote-targets"])


@router.post(
    "/api/environments/{environment_id}/remote-targets",
    response_model=RemoteTargetRead,
    status_code=status.HTTP_201_CREATED,
    summary="注册受控 RemoteTarget",
    responses={
        503: {
            "model": ErrorResponse,
            "description": "服务端 profile 或 machine credential 配置不可用。",
        }
    },
)
def create_remote_target(
    environment_id: UUID,
    payload: RemoteTargetCreate,
    db: DbSession,
) -> RemoteTargetRead:
    """通过服务端 profile 注册目标，不接受任意 endpoint 或 credential。"""

    return RemoteTargetService(db).create_target(environment_id, payload)


@router.get(
    "/api/environments/{environment_id}/remote-targets",
    response_model=PageResponse[RemoteTargetRead],
    summary="分页读取 RemoteTarget",
)
def list_remote_targets(
    environment_id: UUID,
    db: DbSession,
    page: Annotated[tuple[int, str | None], Depends(pagination_params)],
) -> PageResponse[RemoteTargetRead]:
    """读取目标并收敛访问时发现的 heartbeat timeout。"""

    limit, cursor = page
    return RemoteTargetService(db).list_targets(
        environment_id,
        limit,
        cursor,
    )
