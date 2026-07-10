"""DevelopmentPlan 数据访问。"""

from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from cloudhelm_platform_api.models.development_plan import DevelopmentPlan
from cloudhelm_platform_api.repositories.pagination import fetch_page


class DevelopmentPlanRepository:
    """DevelopmentPlan 表访问对象。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, plan: DevelopmentPlan) -> DevelopmentPlan:
        """新增 DevelopmentPlan 并刷新主键。"""

        self.session.add(plan)
        self.session.flush()
        return plan

    def get(self, plan_id: UUID) -> DevelopmentPlan | None:
        """按 ID 读取 DevelopmentPlan。"""

        return self.session.get(DevelopmentPlan, plan_id)

    def list_by_task(self, task_id: UUID, limit: int, cursor: str | None) -> tuple[list[DevelopmentPlan], str | None]:
        """分页读取某任务下的开发计划。"""

        statement: Select[tuple[DevelopmentPlan]] = (
            select(DevelopmentPlan)
            .where(DevelopmentPlan.task_id == task_id)
            .order_by(DevelopmentPlan.created_at, DevelopmentPlan.id)
        )
        return fetch_page(self.session, statement, limit, cursor)

    def latest_by_task(self, task_id: UUID) -> DevelopmentPlan | None:
        """读取任务下最新开发计划。"""

        return self.session.execute(
            select(DevelopmentPlan)
            .where(DevelopmentPlan.task_id == task_id)
            .order_by(DevelopmentPlan.created_at.desc(), DevelopmentPlan.id.desc())
            .limit(1)
        ).scalar_one_or_none()

    def latest_by_task_and_agent_run(self, task_id: UUID, agent_run_id: UUID) -> DevelopmentPlan | None:
        """读取由指定 Planner AgentRun 创建的最新开发计划。"""

        return self.session.execute(
            select(DevelopmentPlan)
            .where(
                DevelopmentPlan.task_id == task_id,
                DevelopmentPlan.created_by_agent_run_id == agent_run_id,
            )
            .order_by(DevelopmentPlan.created_at.desc(), DevelopmentPlan.id.desc())
            .limit(1)
        ).scalar_one_or_none()
