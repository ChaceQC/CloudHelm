"""Event Timeline 与事件流 API。"""

import json
from collections.abc import Iterable
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from cloudhelm_platform_api.api.deps import DbSession, pagination_params
from cloudhelm_platform_api.schemas.common import PageResponse
from cloudhelm_platform_api.schemas.event_log import EventLogRead
from cloudhelm_platform_api.services.event_service import EventService
from cloudhelm_platform_api.services.task_service import TaskService

router = APIRouter(tags=["events"])


@router.get("/api/tasks/{task_id}/timeline", response_model=PageResponse[EventLogRead], summary="读取任务事件时间线")
def get_timeline(
    task_id: UUID,
    db: DbSession,
    page: tuple[int, str | None] = Depends(pagination_params),
) -> PageResponse[EventLogRead]:
    """按创建时间读取某任务真实 EventLog。"""

    TaskService(db).get_task(task_id)
    limit, cursor = page
    return EventService(db).list_timeline(task_id, limit, cursor)


def sse_encode(events: Iterable[EventLogRead]) -> Iterable[str]:
    """将事件 DTO 编码为 Server-Sent Events 文本。"""

    for event in events:
        yield (
            f"event: {event.event_type}\n"
            f"data: {event.model_dump_json()}\n\n"
        )
    yield ": heartbeat\n\n"


@router.get("/api/tasks/{task_id}/events/stream", summary="读取任务事件流")
def stream_task_events(task_id: UUID, db: DbSession) -> StreamingResponse:
    """返回基于真实 EventLog 的 SSE 响应。

    M2 暂不维护长连接实时推送；本端点输出当前已有事件后追加一次 heartbeat，
    控制台可在 M3 通过重连或轮询方式刷新。
    """

    TaskService(db).get_task(task_id)
    timeline = EventService(db).list_timeline(task_id, 100, None)
    return StreamingResponse(
        sse_encode(timeline.items),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )
