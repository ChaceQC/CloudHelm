"""TechnicalDesign API 路由。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, status

from cloudhelm_platform_api.api.deps import DbSession, pagination_params
from cloudhelm_platform_api.schemas.common import DecisionRequest, PageResponse
from cloudhelm_platform_api.schemas.design import TechnicalDesignCreate, TechnicalDesignRead
from cloudhelm_platform_api.services.design_service import DesignService

router = APIRouter(tags=["technical-designs"])


@router.post(
    "/api/tasks/{task_id}/technical-designs",
    response_model=TechnicalDesignRead,
    status_code=status.HTTP_201_CREATED,
    summary="创建技术设计",
)
def create_design(task_id: UUID, payload: TechnicalDesignCreate, db: DbSession) -> TechnicalDesignRead:
    """保存真实技术设计内容，不触发自动 Architect Agent。"""

    return DesignService(db).create_design(task_id, payload)


@router.get(
    "/api/tasks/{task_id}/technical-designs",
    response_model=PageResponse[TechnicalDesignRead],
    summary="分页读取任务技术设计",
)
def list_designs(
    task_id: UUID,
    db: DbSession,
    page: Annotated[tuple[int, str | None], Depends(pagination_params)],
) -> PageResponse[TechnicalDesignRead]:
    """读取某任务下的技术设计列表。"""

    limit, cursor = page
    return DesignService(db).list_by_task(task_id, limit, cursor)


@router.get("/api/technical-designs/{design_id}", response_model=TechnicalDesignRead, summary="读取技术设计")
def get_design(design_id: UUID, db: DbSession) -> TechnicalDesignRead:
    """读取单个技术设计。"""

    return DesignService(db).get_design(design_id)


@router.post("/api/technical-designs/{design_id}/approve", response_model=TechnicalDesignRead, summary="通过技术设计")
def approve_design(
    design_id: UUID,
    db: DbSession,
    payload: DecisionRequest | None = Body(default=None),
) -> TechnicalDesignRead:
    """通过技术设计并写入 TechnicalDesignApproved 事件。"""

    payload = payload or DecisionRequest()
    return DesignService(db).approve(design_id, payload.actor_id, payload.reason)


@router.post(
    "/api/technical-designs/{design_id}/request-changes",
    response_model=TechnicalDesignRead,
    summary="要求修改技术设计",
)
def request_design_changes(
    design_id: UUID,
    db: DbSession,
    payload: DecisionRequest | None = Body(default=None),
) -> TechnicalDesignRead:
    """要求修改技术设计并写入事件。"""

    payload = payload or DecisionRequest()
    return DesignService(db).request_changes(design_id, payload.actor_id, payload.reason)
