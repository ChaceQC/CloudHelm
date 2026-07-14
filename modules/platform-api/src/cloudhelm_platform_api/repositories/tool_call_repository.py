"""ToolCall 数据访问。"""

from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from cloudhelm_platform_api.models.tool_call import ToolCall
from cloudhelm_platform_api.repositories.pagination import fetch_page


class ToolCallRepository:
    """ToolCall 表访问对象。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, tool_call: ToolCall) -> ToolCall:
        """新增 ToolCall 并刷新主键。"""

        self.session.add(tool_call)
        self.session.flush()
        return tool_call

    def get(self, tool_call_id: UUID) -> ToolCall | None:
        """按 ID 读取 ToolCall。"""

        return self.session.get(ToolCall, tool_call_id)

    def get_by_task_idempotency_key(self, task_id: UUID, idempotency_key: str) -> ToolCall | None:
        """按任务内幂等键读取 ToolCall。"""

        return self.session.execute(
            select(ToolCall).where(ToolCall.task_id == task_id, ToolCall.idempotency_key == idempotency_key).limit(1)
        ).scalar_one_or_none()

    def get_by_agent_provider_call(
        self,
        agent_run_id: UUID,
        provider_call_id: str,
    ) -> ToolCall | None:
        """按 AgentRun 和供应商 call_id 读取 ToolCall。"""

        return self.session.scalar(
            select(ToolCall)
            .where(
                ToolCall.agent_run_id == agent_run_id,
                ToolCall.provider_call_id == provider_call_id,
            )
            .limit(1)
        )

    def latest_by_task_and_tool(
        self,
        task_id: UUID,
        tool_name: str,
        *,
        status: str | None = None,
    ) -> ToolCall | None:
        """读取任务指定工具的最新调用。"""

        statement = select(ToolCall).where(
            ToolCall.task_id == task_id,
            ToolCall.tool_name == tool_name,
        )
        if status is not None:
            statement = statement.where(ToolCall.status == status)
        return self.session.scalar(
            statement.order_by(
                ToolCall.started_at.desc(),
                ToolCall.id.desc(),
            ).limit(1)
        )

    def list_by_agent_run(self, agent_run_id: UUID) -> list[ToolCall]:
        """按开始时间返回一个 AgentRun 的全部 ToolCall。"""

        return list(
            self.session.scalars(
                select(ToolCall)
                .where(ToolCall.agent_run_id == agent_run_id)
                .order_by(ToolCall.started_at.asc(), ToolCall.id.asc())
            )
        )

    def list_by_task(self, task_id: UUID, limit: int, cursor: str | None) -> tuple[list[ToolCall], str | None]:
        """分页读取某个任务的工具调用。"""

        statement: Select[tuple[ToolCall]] = (
            select(ToolCall)
            .where(ToolCall.task_id == task_id)
            .order_by(ToolCall.started_at.desc(), ToolCall.id.desc())
        )
        return fetch_page(self.session, statement, limit, cursor)

    def list_active_by_task(self, task_id: UUID) -> list[ToolCall]:
        """读取任务中尚未结束或仍在等待审批的 ToolCall。"""

        return list(
            self.session.scalars(
                select(ToolCall).where(
                    ToolCall.task_id == task_id,
                    ToolCall.status.in_(("pending", "running", "waiting_approval")),
                )
            )
        )
