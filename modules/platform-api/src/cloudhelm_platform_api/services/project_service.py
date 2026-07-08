"""Project 业务服务。"""

from uuid import UUID

from sqlalchemy.orm import Session

from cloudhelm_platform_api.models.project import Project
from cloudhelm_platform_api.repositories.project_repository import ProjectRepository
from cloudhelm_platform_api.schemas.common import PageInfo, PageResponse
from cloudhelm_platform_api.schemas.project import ProjectCreate, ProjectRead
from cloudhelm_platform_api.services.base import BaseService
from cloudhelm_platform_api.services.event_service import EventService
from cloudhelm_platform_api.services.exceptions import ServiceError


class ProjectService(BaseService):
    """Project 用例服务。"""

    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self.projects = ProjectRepository(session)
        self.events = EventService(session)

    def create_project(self, data: ProjectCreate) -> ProjectRead:
        """创建项目并记录 ProjectCreated 事件。"""

        project = self.projects.create(Project(**data.model_dump()))
        self.events.record(
            event_type="ProjectCreated",
            actor_type="user",
            actor_id="user",
            payload={"project_id": str(project.id), "name": project.name},
        )
        self.commit()
        return ProjectRead.model_validate(project)

    def get_project(self, project_id: UUID) -> ProjectRead:
        """读取项目，不存在时返回 404 业务错误。"""

        project = self.projects.get(project_id)
        if project is None:
            raise ServiceError("project_not_found", "项目不存在。", 404)
        return ProjectRead.model_validate(project)

    def list_projects(self, limit: int, cursor: str | None) -> PageResponse[ProjectRead]:
        """分页读取项目。"""

        items, next_cursor = self.projects.list(limit, cursor)
        return PageResponse(
            items=[ProjectRead.model_validate(item) for item in items],
            page=PageInfo(limit=limit, next_cursor=next_cursor),
        )
