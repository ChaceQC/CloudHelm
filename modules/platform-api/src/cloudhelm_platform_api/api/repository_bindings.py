"""M7 ProjectRepositoryBinding API 路由。"""

from uuid import UUID

from fastapi import APIRouter

from cloudhelm_platform_api.api.deps import DbSession
from cloudhelm_platform_api.schemas.common import ErrorResponse
from cloudhelm_platform_api.schemas.repository_binding import (
    RepositoryBindingPut,
    RepositoryBindingRead,
)
from cloudhelm_platform_api.services.project_repository_binding_service import (
    ProjectRepositoryBindingService,
)

router = APIRouter(tags=["repository-bindings"])


@router.put(
    "/api/projects/{project_id}/repository-binding",
    response_model=RepositoryBindingRead,
    summary="配置项目受控 RepositoryBinding",
    responses={
        409: {
            "model": ErrorResponse,
            "description": "远端 repository identity 已被其他 Project 占用。",
        },
        503: {
            "model": ErrorResponse,
            "description": "服务端 profile 或 credential 配置不可用。",
        },
    },
)
def put_repository_binding(
    project_id: UUID,
    payload: RepositoryBindingPut,
    db: DbSession,
) -> RepositoryBindingRead:
    """按服务端 profile 创建或幂等更新项目仓库绑定。"""

    return ProjectRepositoryBindingService(db).put_binding(
        project_id,
        payload,
    )


@router.get(
    "/api/projects/{project_id}/repository-binding",
    response_model=RepositoryBindingRead,
    summary="读取项目 RepositoryBinding",
)
def get_repository_binding(
    project_id: UUID,
    db: DbSession,
) -> RepositoryBindingRead:
    """读取数据库物化结果，不依赖当前 profile 文件。"""

    return ProjectRepositoryBindingService(db).get_binding(project_id)
