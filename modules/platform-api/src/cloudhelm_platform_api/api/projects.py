"""Project API 路由。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from cloudhelm_platform_api.api.deps import DbSession, pagination_params
from cloudhelm_platform_api.schemas.common import PageResponse
from cloudhelm_platform_api.schemas.project import ProjectCreate, ProjectRead
from cloudhelm_platform_api.services.project_service import ProjectService

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED, summary="创建项目")
def create_project(payload: ProjectCreate, db: DbSession) -> ProjectRead:
    """创建 Project，并在同一事务中追加 ProjectCreated 事件。"""

    return ProjectService(db).create_project(payload)


@router.get("", response_model=PageResponse[ProjectRead], summary="分页读取项目")
def list_projects(
    db: DbSession,
    page: Annotated[tuple[int, str | None], Depends(pagination_params)],
) -> PageResponse[ProjectRead]:
    """分页读取项目列表。"""

    limit, cursor = page
    return ProjectService(db).list_projects(limit, cursor)


@router.get("/{project_id}", response_model=ProjectRead, summary="读取项目详情")
def get_project(project_id: UUID, db: DbSession) -> ProjectRead:
    """读取单个 Project。"""

    return ProjectService(db).get_project(project_id)
