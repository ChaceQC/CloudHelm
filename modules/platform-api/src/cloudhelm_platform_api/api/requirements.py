"""RequirementSpec API 路由。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, status

from cloudhelm_platform_api.api.deps import DbSession, pagination_params
from cloudhelm_platform_api.schemas.common import DecisionRequest, PageResponse
from cloudhelm_platform_api.schemas.requirement import RequirementSpecCreate, RequirementSpecRead
from cloudhelm_platform_api.services.requirement_service import RequirementService

router = APIRouter(tags=["requirements"])


@router.post(
    "/api/tasks/{task_id}/requirements",
    response_model=RequirementSpecRead,
    status_code=status.HTTP_201_CREATED,
    summary="创建需求规格",
)
def create_requirement(task_id: UUID, payload: RequirementSpecCreate, db: DbSession) -> RequirementSpecRead:
    """保存真实需求规格，不自动生成或伪造 Agent 输出。"""

    return RequirementService(db).create_requirement(task_id, payload)


@router.get(
    "/api/tasks/{task_id}/requirements",
    response_model=PageResponse[RequirementSpecRead],
    summary="分页读取任务需求规格",
)
def list_requirements(
    task_id: UUID,
    db: DbSession,
    page: Annotated[tuple[int, str | None], Depends(pagination_params)],
) -> PageResponse[RequirementSpecRead]:
    """读取某任务下的需求规格列表。"""

    limit, cursor = page
    return RequirementService(db).list_by_task(task_id, limit, cursor)


@router.get("/api/requirements/{requirement_id}", response_model=RequirementSpecRead, summary="读取需求规格")
def get_requirement(requirement_id: UUID, db: DbSession) -> RequirementSpecRead:
    """读取单个需求规格。"""

    return RequirementService(db).get_requirement(requirement_id)


@router.post("/api/requirements/{requirement_id}/approve", response_model=RequirementSpecRead, summary="通过需求规格")
def approve_requirement(
    requirement_id: UUID,
    db: DbSession,
    payload: DecisionRequest | None = Body(default=None),
) -> RequirementSpecRead:
    """通过需求规格并写入 RequirementSpecApproved 事件。"""

    payload = payload or DecisionRequest()
    return RequirementService(db).approve(requirement_id, payload.actor_id, payload.reason)


@router.post(
    "/api/requirements/{requirement_id}/request-changes",
    response_model=RequirementSpecRead,
    summary="要求修改需求规格",
)
def request_requirement_changes(
    requirement_id: UUID,
    db: DbSession,
    payload: DecisionRequest | None = Body(default=None),
) -> RequirementSpecRead:
    """要求修改需求规格并写入事件。"""

    payload = payload or DecisionRequest()
    return RequirementService(db).request_changes(requirement_id, payload.actor_id, payload.reason)
