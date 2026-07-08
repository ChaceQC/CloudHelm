"""Task API 路由。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query, status

from cloudhelm_platform_api.api.deps import DbSession, pagination_params
from cloudhelm_platform_api.schemas.common import DecisionRequest, PageResponse
from cloudhelm_platform_api.schemas.task import TaskCreate, TaskRead
from cloudhelm_platform_api.services.task_service import TaskService

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.post("", response_model=TaskRead, status_code=status.HTTP_201_CREATED, summary="创建任务")
def create_task(payload: TaskCreate, db: DbSession) -> TaskRead:
    """创建 Task，校验项目存在，并写入 TaskCreated 事件。"""

    return TaskService(db).create_task(payload)


@router.get("", response_model=PageResponse[TaskRead], summary="分页读取任务")
def list_tasks(
    db: DbSession,
    page: Annotated[tuple[int, str | None], Depends(pagination_params)],
    project_id: Annotated[UUID | None, Query(description="按项目过滤。")] = None,
) -> PageResponse[TaskRead]:
    """分页读取任务列表。"""

    limit, cursor = page
    return TaskService(db).list_tasks(limit, cursor, project_id)


@router.get("/{task_id}", response_model=TaskRead, summary="读取任务详情")
def get_task(task_id: UUID, db: DbSession) -> TaskRead:
    """读取单个 Task。"""

    return TaskService(db).get_task(task_id)


@router.post("/{task_id}/pause", response_model=TaskRead, summary="暂停任务")
def pause_task(
    task_id: UUID,
    db: DbSession,
    payload: DecisionRequest | None = Body(default=None),
) -> TaskRead:
    """暂停任务并写入 TaskPaused 事件。"""

    payload = payload or DecisionRequest()
    return TaskService(db).pause_task(task_id, payload.actor_id, payload.reason)


@router.post("/{task_id}/resume", response_model=TaskRead, summary="恢复任务")
def resume_task(
    task_id: UUID,
    db: DbSession,
    payload: DecisionRequest | None = Body(default=None),
) -> TaskRead:
    """恢复暂停任务并写入 TaskResumed 事件。"""

    payload = payload or DecisionRequest()
    return TaskService(db).resume_task(task_id, payload.actor_id, payload.reason)


@router.post("/{task_id}/cancel", response_model=TaskRead, summary="取消任务")
def cancel_task(
    task_id: UUID,
    db: DbSession,
    payload: DecisionRequest | None = Body(default=None),
) -> TaskRead:
    """取消任务并写入 TaskCancelled 事件。"""

    payload = payload or DecisionRequest()
    return TaskService(db).cancel_task(task_id, payload.actor_id, payload.reason)
