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

    def list_by_task(self, task_id: UUID, limit: int, cursor: str | None) -> tuple[list[ToolCall], str | None]:
        """分页读取某个任务的工具调用。"""

        statement: Select[tuple[ToolCall]] = (
            select(ToolCall)
            .where(ToolCall.task_id == task_id)
            .order_by(ToolCall.started_at.desc(), ToolCall.id.desc())
        )
        return fetch_page(self.session, statement, limit, cursor)
