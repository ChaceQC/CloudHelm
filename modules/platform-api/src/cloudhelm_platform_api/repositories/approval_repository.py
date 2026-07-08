"""ApprovalRequest 数据访问。"""

from uuid import UUID

from sqlalchemy import Select, select
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

    def get(self, approval_id: UUID) -> ApprovalRequest | None:
        """按 ID 读取 ApprovalRequest。"""

        return self.session.get(ApprovalRequest, approval_id)

    def list(self, limit: int, cursor: str | None, status: str | None = None) -> tuple[list[ApprovalRequest], str | None]:
        """分页读取审批请求，可按状态过滤。"""

        statement: Select[tuple[ApprovalRequest]] = select(ApprovalRequest).order_by(
            ApprovalRequest.created_at,
            ApprovalRequest.id,
        )
        if status is not None:
            statement = statement.where(ApprovalRequest.status == status)
        return fetch_page(self.session, statement, limit, cursor)

    def latest_by_task_and_action(self, task_id: UUID, action: str) -> ApprovalRequest | None:
        """读取某任务某动作的最新审批请求。"""

        return self.session.execute(
            select(ApprovalRequest)
            .where(ApprovalRequest.task_id == task_id, ApprovalRequest.action == action)
            .order_by(ApprovalRequest.created_at.desc(), ApprovalRequest.id.desc())
            .limit(1)
        ).scalar_one_or_none()
