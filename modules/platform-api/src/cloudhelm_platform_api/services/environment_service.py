"""M7 Environment 业务服务。"""

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cloudhelm_platform_api.models.environment import Environment
from cloudhelm_platform_api.repositories.environment_repository import (
    EnvironmentRepository,
)
from cloudhelm_platform_api.repositories.project_repository import ProjectRepository
from cloudhelm_platform_api.schemas.common import PageInfo, PageResponse
from cloudhelm_platform_api.schemas.environment import (
    EnvironmentCreate,
    EnvironmentRead,
)
from cloudhelm_platform_api.services.base import BaseService
from cloudhelm_platform_api.services.database_errors import (
    database_write_error,
    integrity_constraint_name,
)
from cloudhelm_platform_api.services.event_service import EventService
from cloudhelm_platform_api.services.exceptions import ServiceError


class EnvironmentService(BaseService):
    """管理项目下 staging/demo Environment。

    Environment 的 env profile 引用属于后续部署配置，本切片不允许普通 API
    提交该内部字段。
    """

    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self.projects = ProjectRepository(session)
        self.environments = EnvironmentRepository(session)
        self.events = EventService(session)

    def create_environment(
        self,
        project_id: UUID,
        data: EnvironmentCreate,
    ) -> EnvironmentRead:
        """创建 Environment，并在同一事务写入 EnvironmentCreated。"""

        if self.projects.get(project_id) is None:
            raise ServiceError("project_not_found", "项目不存在。", 404)
        if self.environments.get_by_project_name(project_id, data.name):
            raise ServiceError(
                "environment_name_conflict",
                "项目内已存在同名 Environment。",
                409,
            )

        try:
            environment = self.environments.create(
                Environment(
                    project_id=project_id,
                    name=data.name,
                    environment_type=data.environment_type,
                    status="active",
                    base_url=str(data.base_url),
                    env_profile_ref=None,
                )
            )
        except IntegrityError as exc:
            self.session.rollback()
            if integrity_constraint_name(exc) == (
                "uq_environments_project_name"
            ):
                raise ServiceError(
                    "environment_name_conflict",
                    "项目内已存在同名 Environment。",
                    409,
                ) from None
            raise database_write_error(exc) from exc
        self.events.record(
            event_type="EnvironmentCreated",
            actor_type="user",
            actor_id="user",
            payload={
                "project_id": str(project_id),
                "environment_id": str(environment.id),
                "name": environment.name,
                "environment_type": environment.environment_type,
            },
        )
        self.commit()
        return EnvironmentRead.model_validate(environment)

    def get_environment(self, environment_id: UUID) -> EnvironmentRead:
        """读取 Environment，不存在时返回稳定 404。"""

        environment = self.environments.get(environment_id)
        if environment is None:
            raise ServiceError(
                "environment_not_found",
                "Environment 不存在。",
                404,
            )
        return EnvironmentRead.model_validate(environment)

    def list_environments(
        self,
        project_id: UUID,
        limit: int,
        cursor: str | None,
    ) -> PageResponse[EnvironmentRead]:
        """分页读取项目下 Environment。"""

        if self.projects.get(project_id) is None:
            raise ServiceError("project_not_found", "项目不存在。", 404)
        items, next_cursor = self.environments.list_by_project(
            project_id,
            limit,
            cursor,
        )
        return PageResponse(
            items=[EnvironmentRead.model_validate(item) for item in items],
            page=PageInfo(limit=limit, next_cursor=next_cursor),
        )
