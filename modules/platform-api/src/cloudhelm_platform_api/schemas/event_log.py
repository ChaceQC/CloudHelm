"""EventLog API DTO。"""

from datetime import datetime
from typing import Any
from uuid import UUID

from cloudhelm_platform_api.schemas.common import OrmModel


class EventLogRead(OrmModel):
    """事件日志响应结构。"""

    id: UUID
    task_id: UUID | None
    event_type: str
    actor_type: str
    actor_id: str | None
    payload: dict[str, Any]
    created_at: datetime
