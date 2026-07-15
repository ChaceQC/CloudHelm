"""M7 Environment API 路由。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from cloudhelm_platform_api.api.deps import DbSession, pagination_params
from cloudhelm_platform_api.schemas.common import PageResponse
from cloudhelm_platform_api.schemas.environment import (
    EnvironmentCreate,
    EnvironmentRead,
)
from cloudhelm_platform_api.services.environment_service import (
    EnvironmentService,
)

router = APIRouter(tags=["environments"])


@router.post(
    "/api/projects/{project_id}/environments",
    response_model=EnvironmentRead,
    status_code=status.HTTP_201_CREATED,
    summary="创建 staging/demo Environment",
)
def create_environment(
    project_id: UUID,
    payload: EnvironmentCreate,
    db: DbSession,
) -> EnvironmentRead:
    """创建项目环境；内部 env profile 不接受调用方覆盖。"""

    return EnvironmentService(db).create_environment(project_id, payload)


@router.get(
    "/api/projects/{project_id}/environments",
    response_model=PageResponse[EnvironmentRead],
    summary="分页读取项目 Environment",
)
def list_environments(
    project_id: UUID,
    db: DbSession,
    page: Annotated[tuple[int, str | None], Depends(pagination_params)],
) -> PageResponse[EnvironmentRead]:
    """分页读取项目下的真实 Environment。"""

    limit, cursor = page
    return EnvironmentService(db).list_environments(
        project_id,
        limit,
        cursor,
    )


@router.get(
    "/api/environments/{environment_id}",
    response_model=EnvironmentRead,
    summary="读取 Environment 详情",
)
def get_environment(
    environment_id: UUID,
    db: DbSession,
) -> EnvironmentRead:
    """读取单个 Environment。"""

    return EnvironmentService(db).get_environment(environment_id)
