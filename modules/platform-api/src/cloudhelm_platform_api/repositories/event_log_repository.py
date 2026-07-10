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

    def latest_by_task_and_type(self, task_id: UUID, event_type: str) -> EventLog | None:
        """读取任务某类型的最新事件。"""

        return self.session.execute(
            select(EventLog)
            .where(EventLog.task_id == task_id, EventLog.event_type == event_type)
            .order_by(EventLog.created_at.desc(), EventLog.id.desc())
            .limit(1)
        ).scalar_one_or_none()

    def list_by_task(self, task_id: UUID, limit: int, cursor: str | None) -> tuple[list[EventLog], str | None]:
        """读取最新一页事件，并在页内恢复为时间正序。"""

        statement: Select[tuple[EventLog]] = (
            select(EventLog)
            .where(EventLog.task_id == task_id)
            .order_by(EventLog.created_at.desc(), EventLog.id.desc())
        )
        items, next_cursor = fetch_page(self.session, statement, limit, cursor)
        items.reverse()
        return items, next_cursor
