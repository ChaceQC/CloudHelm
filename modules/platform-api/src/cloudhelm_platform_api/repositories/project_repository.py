"""Project 数据访问。"""

from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from cloudhelm_platform_api.models.project import Project
from cloudhelm_platform_api.repositories.pagination import fetch_page


class ProjectRepository:
    """Project 表访问对象。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, project: Project) -> Project:
        """新增 Project 并刷新主键。"""

        self.session.add(project)
        self.session.flush()
        return project

    def get(
        self,
        project_id: UUID,
        *,
        for_update: bool = False,
    ) -> Project | None:
        """按 ID 读取 Project；首次创建子资源时可作为 mutex 加锁。"""

        if not for_update:
            return self.session.get(Project, project_id)
        return self.session.scalar(
            select(Project)
            .where(Project.id == project_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def list(self, limit: int, cursor: str | None) -> tuple[list[Project], str | None]:
        """分页读取 Project。"""

        statement: Select[tuple[Project]] = select(Project).order_by(Project.created_at.desc(), Project.id.desc())
        return fetch_page(self.session, statement, limit, cursor)
