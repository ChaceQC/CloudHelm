"""RequirementSpec 数据访问。"""

from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from cloudhelm_platform_api.models.requirement import RequirementSpec
from cloudhelm_platform_api.repositories.pagination import fetch_page


class RequirementRepository:
    """RequirementSpec 表访问对象。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, requirement: RequirementSpec) -> RequirementSpec:
        """新增 RequirementSpec 并刷新主键。"""

        self.session.add(requirement)
        self.session.flush()
        return requirement

    def get(self, requirement_id: UUID) -> RequirementSpec | None:
        """按 ID 读取 RequirementSpec。"""

        return self.session.get(RequirementSpec, requirement_id)

    def list_by_task(self, task_id: UUID, limit: int, cursor: str | None) -> tuple[list[RequirementSpec], str | None]:
        """分页读取某个任务的需求规格。"""

        statement: Select[tuple[RequirementSpec]] = (
            select(RequirementSpec)
            .where(RequirementSpec.task_id == task_id)
            .order_by(RequirementSpec.created_at.desc(), RequirementSpec.id.desc())
        )
        return fetch_page(self.session, statement, limit, cursor)

    def latest_by_task(self, task_id: UUID) -> RequirementSpec | None:
        """读取任务最新需求规格。"""

        return self.session.execute(
            select(RequirementSpec)
            .where(RequirementSpec.task_id == task_id)
            .order_by(RequirementSpec.created_at.desc(), RequirementSpec.id.desc())
            .limit(1)
        ).scalar_one_or_none()
