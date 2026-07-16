"""ApprovalRequest 数据访问。"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from cloudhelm_platform_api.models.approval import ApprovalRequest
from cloudhelm_platform_api.repositories.pagination import fetch_page


class ApprovalRepository:
    """ApprovalRequest 表访问对象。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, approval: ApprovalRequest) -> ApprovalRequest:
        """新增 ApprovalRequest 并刷新主键。"""

        self.session.add(approval)
        self.session.flush()
        return approval

    def get(
        self,
        approval_id: UUID,
        *,
        for_update: bool = False,
    ) -> ApprovalRequest | None:
        """按 ID 读取 ApprovalRequest，可选加行锁。"""

        if not for_update:
            return self.session.get(ApprovalRequest, approval_id)
        return self.session.scalar(
            select(ApprovalRequest)
            .where(ApprovalRequest.id == approval_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def list(
        self,
        limit: int,
        cursor: str | None,
        status: str | None = None,
        task_id: UUID | None = None,
    ) -> tuple[list[ApprovalRequest], str | None]:
        """分页读取审批请求，可按状态过滤。"""

        statement: Select[tuple[ApprovalRequest]] = select(ApprovalRequest).order_by(
            ApprovalRequest.created_at.desc(),
            ApprovalRequest.id.desc(),
        )
        if status is not None:
            statement = statement.where(ApprovalRequest.status == status)
        if task_id is not None:
            statement = statement.where(ApprovalRequest.task_id == task_id)
        return fetch_page(self.session, statement, limit, cursor)

    def latest_by_task_and_action(self, task_id: UUID, action: str) -> ApprovalRequest | None:
        """读取某任务某动作的最新审批请求。"""

        return self.session.execute(
            select(ApprovalRequest)
            .where(ApprovalRequest.task_id == task_id, ApprovalRequest.action == action)
            .order_by(ApprovalRequest.created_at.desc(), ApprovalRequest.id.desc())
            .limit(1)
        ).scalar_one_or_none()

    def has_pending_by_task(self, task_id: UUID) -> bool:
        """判断任务是否仍有待处理审批。"""

        return (
            self.session.execute(
                select(ApprovalRequest.id)
                .where(ApprovalRequest.task_id == task_id, ApprovalRequest.status == "pending")
                .limit(1)
            ).scalar_one_or_none()
            is not None
        )

    def list_pending_by_task(
        self,
        task_id: UUID,
        *,
        for_update: bool = False,
    ) -> list[ApprovalRequest]:
        """读取任务全部待处理审批，供取消任务时统一过期。"""

        statement = select(ApprovalRequest).where(
            ApprovalRequest.task_id == task_id,
            ApprovalRequest.status == "pending",
        )
        if for_update:
            statement = statement.with_for_update().execution_options(
                populate_existing=True
            )
        return list(self.session.scalars(statement))

    def list_by_ids_for_update(
        self,
        approval_ids: list[UUID],
    ) -> list[ApprovalRequest]:
        """按 UUID 顺序锁定一组 Approval，避免漂移失效时形成锁序环。"""

        if not approval_ids:
            return []
        return list(
            self.session.scalars(
                select(ApprovalRequest)
                .where(ApprovalRequest.id.in_(approval_ids))
                .order_by(ApprovalRequest.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )

    def database_now(self) -> datetime:
        """读取 PostgreSQL 实时时钟，供资源审批过期与数据库约束统一。

        ``now()`` 固定为事务开始时间。事务等待其他行锁后再处理刚创建的审批时，
        该时间可能早于目标记录的 ``created_at``，因此这里必须使用会随语句推进的
        ``clock_timestamp()``。
        """

        value = self.session.scalar(select(func.clock_timestamp()))
        assert value is not None
        return value
