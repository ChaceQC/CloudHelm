"""AgentRun 数据访问。"""

from uuid import UUID

from sqlalchemy import Select, func, select
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

    def get_by_task_idempotency_key(
        self,
        task_id: UUID,
        idempotency_key: str,
    ) -> AgentRun | None:
        """按任务内工作流幂等键读取 AgentRun。"""

        return self.session.scalar(
            select(AgentRun)
            .where(
                AgentRun.task_id == task_id,
                AgentRun.idempotency_key == idempotency_key,
            )
            .limit(1)
        )

    def next_attempt(self, task_id: UUID, workflow_step: str) -> int:
        """返回任务指定工作流步骤的下一个 attempt。"""

        latest = self.session.scalar(
            select(func.max(AgentRun.attempt)).where(
                AgentRun.task_id == task_id,
                AgentRun.workflow_step == workflow_step,
            )
        )
        return int(latest or 0) + 1

    def active_workflow_run(
        self,
        task_id: UUID,
        workflow_step: str,
    ) -> AgentRun | None:
        """读取指定步骤尚未结束的 AgentRun。"""

        return self.session.scalar(
            select(AgentRun)
            .where(
                AgentRun.task_id == task_id,
                AgentRun.workflow_step == workflow_step,
                AgentRun.status.in_(("pending", "running")),
            )
            .order_by(AgentRun.started_at.desc(), AgentRun.id.desc())
            .limit(1)
        )

    def latest_by_workflow_step(
        self,
        task_id: UUID,
        workflow_step: str,
        *,
        status: str | None = None,
    ) -> AgentRun | None:
        """读取任务指定 M6 步骤的最新 AgentRun。"""

        statement = select(AgentRun).where(
            AgentRun.task_id == task_id,
            AgentRun.workflow_step == workflow_step,
        )
        if status is not None:
            statement = statement.where(AgentRun.status == status)
        return self.session.scalar(
            statement.order_by(
                AgentRun.attempt.desc(),
                AgentRun.started_at.desc(),
                AgentRun.id.desc(),
            ).limit(1)
        )

    def list_by_task(self, task_id: UUID, limit: int, cursor: str | None) -> tuple[list[AgentRun], str | None]:
        """分页读取某个任务的 AgentRun。"""

        statement: Select[tuple[AgentRun]] = (
            select(AgentRun)
            .where(AgentRun.task_id == task_id)
            .order_by(AgentRun.started_at.desc(), AgentRun.id.desc())
        )
        return fetch_page(self.session, statement, limit, cursor)

    def list_active_by_task(self, task_id: UUID) -> list[AgentRun]:
        """读取任务中尚未结束的 AgentRun。"""

        return list(
            self.session.scalars(
                select(AgentRun).where(
                    AgentRun.task_id == task_id,
                    AgentRun.status.in_(("pending", "running")),
                )
            )
        )
