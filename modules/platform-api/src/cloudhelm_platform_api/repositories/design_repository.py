"""TechnicalDesign 数据访问。"""

from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from cloudhelm_platform_api.models.design import TechnicalDesign
from cloudhelm_platform_api.repositories.pagination import fetch_page


class DesignRepository:
    """TechnicalDesign 表访问对象。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, design: TechnicalDesign) -> TechnicalDesign:
        """新增 TechnicalDesign 并刷新主键。"""

        self.session.add(design)
        self.session.flush()
        return design

    def get(self, design_id: UUID) -> TechnicalDesign | None:
        """按 ID 读取 TechnicalDesign。"""

        return self.session.get(TechnicalDesign, design_id)

    def list_by_task(self, task_id: UUID, limit: int, cursor: str | None) -> tuple[list[TechnicalDesign], str | None]:
        """分页读取某个任务的技术设计。"""

        statement: Select[tuple[TechnicalDesign]] = (
            select(TechnicalDesign)
            .where(TechnicalDesign.task_id == task_id)
            .order_by(TechnicalDesign.created_at.desc(), TechnicalDesign.id.desc())
        )
        return fetch_page(self.session, statement, limit, cursor)

    def latest_by_task(self, task_id: UUID) -> TechnicalDesign | None:
        """读取任务最新技术设计。"""

        return self.session.execute(
            select(TechnicalDesign)
            .where(TechnicalDesign.task_id == task_id)
            .order_by(TechnicalDesign.created_at.desc(), TechnicalDesign.id.desc())
            .limit(1)
        ).scalar_one_or_none()
