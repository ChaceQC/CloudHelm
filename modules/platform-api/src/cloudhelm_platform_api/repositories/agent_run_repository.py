"""AgentRun 数据访问。"""

from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from cloudhelm_platform_api.models.agent_run import AgentRun
from cloudhelm_platform_api.repositories.pagination import fetch_page


class AgentRunRepository:
    """AgentRun 表访问对象。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, agent_run: AgentRun) -> AgentRun:
        """新增 AgentRun 并刷新主键。"""

        self.session.add(agent_run)
        self.session.flush()
        return agent_run

    def get(self, run_id: UUID) -> AgentRun | None:
        """按 ID 读取 AgentRun。"""

        return self.session.get(AgentRun, run_id)

    def list_by_task(self, task_id: UUID, limit: int, cursor: str | None) -> tuple[list[AgentRun], str | None]:
        """分页读取某个任务的 AgentRun。"""

        statement: Select[tuple[AgentRun]] = (
            select(AgentRun)
            .where(AgentRun.task_id == task_id)
            .order_by(AgentRun.started_at, AgentRun.id)
        )
        return fetch_page(self.session, statement, limit, cursor)
