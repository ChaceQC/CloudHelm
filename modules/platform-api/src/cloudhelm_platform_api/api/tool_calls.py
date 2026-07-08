"""ToolCall API 路由。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from cloudhelm_platform_api.api.deps import DbSession, pagination_params
from cloudhelm_platform_api.schemas.common import PageResponse
from cloudhelm_platform_api.schemas.tool_call import ToolCallCreate, ToolCallRead
from cloudhelm_platform_api.services.tool_call_service import ToolCallService

router = APIRouter(tags=["tool-calls"])


@router.post(
    "/api/tasks/{task_id}/tool-calls",
    response_model=ToolCallRead,
    status_code=status.HTTP_201_CREATED,
    summary="创建 ToolCall 记录（M2 内部联调）",
)
def create_tool_call(task_id: UUID, payload: ToolCallCreate, db: DbSession) -> ToolCallRead:
    """写入 ToolCall 记录；M2 不执行真实工具。"""

    return ToolCallService(db).create_tool_call(task_id, payload)


@router.get("/api/tasks/{task_id}/tool-calls", response_model=PageResponse[ToolCallRead], summary="分页读取任务 ToolCall")
def list_tool_calls(
    task_id: UUID,
    db: DbSession,
    page: Annotated[tuple[int, str | None], Depends(pagination_params)],
) -> PageResponse[ToolCallRead]:
    """读取某任务下的 ToolCall 记录。"""

    limit, cursor = page
    return ToolCallService(db).list_by_task(task_id, limit, cursor)


@router.get("/api/tool-calls/{tool_call_id}", response_model=ToolCallRead, summary="读取 ToolCall")
def get_tool_call(tool_call_id: UUID, db: DbSession) -> ToolCallRead:
    """读取单个 ToolCall。"""

    return ToolCallService(db).get_tool_call(tool_call_id)
