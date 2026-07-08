"""ApprovalRequest API 路由。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query, status

from cloudhelm_platform_api.api.deps import DbSession, pagination_params
from cloudhelm_platform_api.schemas.approval import ApprovalRequestCreate, ApprovalRequestRead
from cloudhelm_platform_api.schemas.common import ApprovalStatus, DecisionRequest, PageResponse
from cloudhelm_platform_api.services.approval_service import ApprovalService

router = APIRouter(tags=["approvals"])


@router.post(
    "/api/tasks/{task_id}/approvals",
    response_model=ApprovalRequestRead,
    status_code=status.HTTP_201_CREATED,
    summary="创建审批请求（M2 内部联调）",
)
def create_approval(task_id: UUID, payload: ApprovalRequestCreate, db: DbSession) -> ApprovalRequestRead:
    """创建 ApprovalRequest；M2 不自动触发工具执行。"""

    return ApprovalService(db).create_approval(task_id, payload)


@router.get("/api/approvals", response_model=PageResponse[ApprovalRequestRead], summary="分页读取审批请求")
def list_approvals(
    db: DbSession,
    page: Annotated[tuple[int, str | None], Depends(pagination_params)],
    status_filter: Annotated[ApprovalStatus | None, Query(alias="status", description="按状态过滤。")] = None,
) -> PageResponse[ApprovalRequestRead]:
    """分页读取审批请求。"""

    limit, cursor = page
    return ApprovalService(db).list_approvals(limit, cursor, status_filter)


@router.get("/api/approvals/{approval_id}", response_model=ApprovalRequestRead, summary="读取审批请求")
def get_approval(approval_id: UUID, db: DbSession) -> ApprovalRequestRead:
    """读取单个 ApprovalRequest。"""

    return ApprovalService(db).get_approval(approval_id)


@router.post("/api/approvals/{approval_id}/approve", response_model=ApprovalRequestRead, summary="通过审批请求")
def approve_approval(
    approval_id: UUID,
    db: DbSession,
    payload: DecisionRequest | None = Body(default=None),
) -> ApprovalRequestRead:
    """通过审批并写入 ApprovalApproved 事件。"""

    payload = payload or DecisionRequest()
    return ApprovalService(db).approve(approval_id, payload.actor_id, payload.reason)


@router.post("/api/approvals/{approval_id}/reject", response_model=ApprovalRequestRead, summary="拒绝审批请求")
def reject_approval(
    approval_id: UUID,
    db: DbSession,
    payload: DecisionRequest | None = Body(default=None),
) -> ApprovalRequestRead:
    """拒绝审批并写入 ApprovalRejected 事件。"""

    payload = payload or DecisionRequest()
    return ApprovalService(db).reject(approval_id, payload.actor_id, payload.reason)
