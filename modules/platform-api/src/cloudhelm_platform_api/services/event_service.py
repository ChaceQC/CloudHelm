"""事件日志服务。"""

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from cloudhelm_platform_api.models.event_log import EventLog
from cloudhelm_platform_api.repositories.event_log_repository import EventLogRepository
from cloudhelm_platform_api.schemas.event_log import EventLogRead
from cloudhelm_platform_api.schemas.common import PageInfo, PageResponse
from cloudhelm_platform_api.services.base import BaseService


class EventService(BaseService):
    """负责追加事件和读取任务时间线。"""

    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self.events = EventLogRepository(session)

    def record(
        self,
        event_type: str,
        actor_type: str,
        actor_id: str | None,
        payload: dict[str, Any],
        task_id: UUID | None = None,
    ) -> EventLog:
        """在当前事务内追加事件，不主动提交。

        调用方必须在同一事务内提交业务记录与事件记录。
        """

        return self.events.create(
            EventLog(
                task_id=task_id,
                event_type=event_type,
                actor_type=actor_type,
                actor_id=actor_id,
                payload=payload,
            )
        )

    def list_timeline(self, task_id: UUID, limit: int, cursor: str | None) -> PageResponse[EventLogRead]:
        """读取某个任务的事件时间线。"""

        items, next_cursor = self.events.list_by_task(task_id, limit, cursor)
        return PageResponse(
            items=[EventLogRead.model_validate(item) for item in items],
            page=PageInfo(limit=limit, next_cursor=next_cursor),
        )
