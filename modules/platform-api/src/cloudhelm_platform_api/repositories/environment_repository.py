"""Environment 数据访问。"""

from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from cloudhelm_platform_api.models.environment import Environment
from cloudhelm_platform_api.repositories.pagination import fetch_page


class EnvironmentRepository:
    """Environment 表访问对象。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, environment: Environment) -> Environment:
        """新增 Environment 并刷新主键。"""

        self.session.add(environment)
        self.session.flush()
        return environment

    def get(self, environment_id: UUID) -> Environment | None:
        """按 ID 读取 Environment。"""

        return self.session.get(Environment, environment_id)

    def get_by_project_name(
        self,
        project_id: UUID,
        name: str,
    ) -> Environment | None:
        """按项目和名称读取 Environment。"""

        return self.session.execute(
            select(Environment).where(
                Environment.project_id == project_id,
                Environment.name == name,
            )
        ).scalar_one_or_none()

    def list_by_project(
        self,
        project_id: UUID,
        limit: int,
        cursor: str | None,
    ) -> tuple[list[Environment], str | None]:
        """分页读取项目下的 Environment。"""

        statement: Select[tuple[Environment]] = (
            select(Environment)
            .where(Environment.project_id == project_id)
            .order_by(Environment.created_at.desc(), Environment.id.desc())
        )
        return fetch_page(self.session, statement, limit, cursor)
