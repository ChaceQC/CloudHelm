"""DevelopmentPlan API 路由。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from cloudhelm_platform_api.api.deps import DbSession, pagination_params
from cloudhelm_platform_api.schemas.common import PageResponse
from cloudhelm_platform_api.schemas.development_plan import DevelopmentPlanRead
from cloudhelm_platform_api.services.development_plan_service import DevelopmentPlanService

router = APIRouter(tags=["development-plans"])


@router.get(
    "/api/tasks/{task_id}/development-plans",
    response_model=PageResponse[DevelopmentPlanRead],
    summary="分页读取任务开发计划",
)
def list_development_plans(
    task_id: UUID,
    db: DbSession,
    page: Annotated[tuple[int, str | None], Depends(pagination_params)],
) -> PageResponse[DevelopmentPlanRead]:
    """读取 Planner Agent 写入的真实 DevelopmentPlan。"""

    limit, cursor = page
    return DevelopmentPlanService(db).list_by_task(task_id, limit, cursor)


@router.get(
    "/api/development-plans/{plan_id}",
    response_model=DevelopmentPlanRead,
    summary="读取开发计划",
)
def get_development_plan(plan_id: UUID, db: DbSession) -> DevelopmentPlanRead:
    """读取单个 DevelopmentPlan。"""

    return DevelopmentPlanService(db).get_plan(plan_id)
