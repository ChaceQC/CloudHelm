"""ApprovalRequest 业务服务。"""

from uuid import UUID

from sqlalchemy.orm import Session

from cloudhelm_platform_api.core.config import get_settings
from cloudhelm_platform_api.db.base import utc_now
from cloudhelm_platform_api.models.approval import ApprovalRequest
from cloudhelm_platform_api.repositories.agent_run_repository import AgentRunRepository
from cloudhelm_platform_api.repositories.approval_repository import ApprovalRepository
from cloudhelm_platform_api.repositories.task_repository import TaskRepository
from cloudhelm_platform_api.schemas.approval import ApprovalRequestCreate, ApprovalRequestRead
from cloudhelm_platform_api.schemas.common import (
    ApprovalStatus, PageInfo, PageResponse, TaskStatus,
)
from cloudhelm_platform_api.services.base import BaseService
from cloudhelm_platform_api.services.agent_context_messages import append_approval_decision_context
from cloudhelm_platform_api.services.agent_conversation_service import AgentConversationService
from cloudhelm_platform_api.services.approval_domain_decision_service import (
    ApprovalDomainDecisionService,
)
from cloudhelm_platform_api.services.event_service import EventService
from cloudhelm_platform_api.services.exceptions import ServiceError
TERMINAL_TASK_STATUSES = {TaskStatus.DONE.value, TaskStatus.FAILED.value, TaskStatus.CANCELLED.value}
RESERVED_APPROVAL_ACTIONS = {"approve_release_candidate"}


class ApprovalService(BaseService):
    """审批请求服务。"""

    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self.approvals = ApprovalRepository(session)
        self.tasks = TaskRepository(session)
        self.agent_runs = AgentRunRepository(session)
        self.events = EventService(session)
        self.domain = ApprovalDomainDecisionService(session)
        self.agent_conversations = AgentConversationService(session, get_settings())

    def create_approval(self, task_id: UUID, data: ApprovalRequestCreate) -> ApprovalRequestRead:
        """创建审批请求并写入 ApprovalRequested 事件。"""

        if data.action in RESERVED_APPROVAL_ACTIONS:
            raise ServiceError(
                "approval_action_reserved",
                "候选发布审批只能由服务端 ReleaseCandidate 流程创建。",
                422,
            )
        self._require_active_task(task_id, for_update=True)
        agent_run = self.agent_runs.get(data.requested_by_agent_run_id) if data.requested_by_agent_run_id else None
        if data.requested_by_agent_run_id and agent_run is None:
            raise ServiceError("agent_run_not_found", "创建审批失败：AgentRun 不存在。", 404)
        if agent_run is not None and agent_run.task_id != task_id:
            raise ServiceError("agent_run_task_mismatch", "创建审批失败：AgentRun 不属于当前任务。", 409)
        approval = self.approvals.create(
            ApprovalRequest(
                task_id=task_id,
                status=ApprovalStatus.PENDING.value,
                **data.model_dump(mode="json"),
            )
        )
        self.events.record(
            "ApprovalRequested",
            "system",
            str(data.requested_by_agent_run_id) if data.requested_by_agent_run_id else "user",
            {"approval_id": str(approval.id), "action": approval.action, "risk_level": approval.risk_level},
            task_id,
        )
        self.commit()
        return ApprovalRequestRead.model_validate(approval)

    def get_approval(self, approval_id: UUID) -> ApprovalRequestRead:
        """读取审批请求。"""

        return ApprovalRequestRead.model_validate(self._require_approval(approval_id))

    def list_approvals(
        self, limit: int,
        cursor: str | None,
        status: ApprovalStatus | None = None,
        task_id: UUID | None = None,
    ) -> PageResponse[ApprovalRequestRead]:
        """分页读取审批请求。"""

        items, next_cursor = self.approvals.list(limit, cursor, status.value if status else None, task_id)
        return PageResponse(
            items=[ApprovalRequestRead.model_validate(item) for item in items],
            page=PageInfo(limit=limit, next_cursor=next_cursor),
        )

    def approve(self, approval_id: UUID, actor_id: str, reason: str | None = None) -> ApprovalRequestRead:
        """通过审批并写入 ApprovalApproved 事件。"""

        approval_hint = self._require_approval(approval_id)
        task = self._require_active_task(
            approval_hint.task_id,
            for_update=True,
        )
        approval = self._require_pending_approval(
            approval_id,
            for_update=True,
        )
        resource_payload = self.domain.approve(
            approval,
            task,
            actor_id,
            reason,
        )
        approval.status = ApprovalStatus.APPROVED.value
        approval.decided_by = actor_id
        approval.decided_at = utc_now()
        self.events.record(
            "ApprovalApproved",
            "user",
            actor_id,
            {"approval_id": str(approval.id), "reason": reason, "action": approval.action, **resource_payload},
            approval.task_id,
        )
        append_approval_decision_context(
            self.agent_conversations,
            approval,
            status="approved",
            actor_id=actor_id,
            reason=reason,
            resource_payload=resource_payload,
        )
        self.commit()
        return ApprovalRequestRead.model_validate(approval)

    def reject(self, approval_id: UUID, actor_id: str, reason: str | None = None) -> ApprovalRequestRead:
        """拒绝审批并写入 ApprovalRejected 事件。"""

        approval_hint = self._require_approval(approval_id)
        task = self._require_active_task(
            approval_hint.task_id,
            for_update=True,
        )
        approval = self._require_pending_approval(
            approval_id,
            for_update=True,
        )
        resource_payload = self.domain.reject(
            approval,
            task,
            actor_id,
            reason,
        )
        approval.status = ApprovalStatus.REJECTED.value
        approval.decided_by = actor_id
        approval.decided_at = utc_now()
        self.events.record(
            "ApprovalRejected",
            "user",
            actor_id,
            {"approval_id": str(approval.id), "reason": reason, "action": approval.action, **resource_payload},
            approval.task_id,
        )
        append_approval_decision_context(
            self.agent_conversations,
            approval,
            status="rejected",
            actor_id=actor_id,
            reason=reason,
            resource_payload=resource_payload,
        )
        self.commit()
        return ApprovalRequestRead.model_validate(approval)

    def _require_approval(
        self,
        approval_id: UUID,
        *,
        for_update: bool = False,
    ) -> ApprovalRequest:
        """读取审批请求或返回 404。"""

        approval = self.approvals.get(approval_id, for_update=for_update)
        if approval is None:
            raise ServiceError("approval_not_found", "审批请求不存在。", 404)
        return approval

    def _require_pending_approval(
        self,
        approval_id: UUID,
        *,
        for_update: bool = False,
    ) -> ApprovalRequest:
        """读取待审批请求并校验状态。"""

        approval = self._require_approval(
            approval_id,
            for_update=for_update,
        )
        if approval.status != ApprovalStatus.PENDING.value:
            raise ServiceError("invalid_approval_transition", "审批请求已决策，不能重复处理。", 409)
        return approval

    def _require_active_task(
        self,
        task_id: UUID,
        *,
        for_update: bool = False,
    ):
        """审批决策必须关联仍可继续推进的任务。"""

        task = self.tasks.get(task_id, for_update=for_update)
        if task is None:
            raise ServiceError("task_not_found", "审批关联任务不存在。", 404)
        if task.status in TERMINAL_TASK_STATUSES:
            raise ServiceError("task_terminal", "终态任务不能继续处理审批。", 409)
        return task
