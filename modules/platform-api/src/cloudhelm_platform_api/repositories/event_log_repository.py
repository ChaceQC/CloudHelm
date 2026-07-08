"""EventLog 数据访问。"""

from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from cloudhelm_platform_api.models.event_log import EventLog
from cloudhelm_platform_api.repositories.pagination import fetch_page


class EventLogRepository:
    """EventLog 表访问对象。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, event: EventLog) -> EventLog:
        """新增 EventLog 并刷新主键。"""

        self.session.add(event)
        self.session.flush()
        return event

    def list_by_task(self, task_id: UUID, limit: int, cursor: str | None) -> tuple[list[EventLog], str | None]:
        """分页读取某个任务的事件时间线。"""

        statement: Select[tuple[EventLog]] = (
            select(EventLog)
            .where(EventLog.task_id == task_id)
            .order_by(EventLog.created_at, EventLog.id)
        )
        return fetch_page(self.session, statement, limit, cursor)
