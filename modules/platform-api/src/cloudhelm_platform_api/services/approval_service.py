"""ApprovalRequest 业务服务。"""

from uuid import UUID

from sqlalchemy.orm import Session

from cloudhelm_platform_api.db.base import utc_now
from cloudhelm_platform_api.models.approval import ApprovalRequest
from cloudhelm_platform_api.repositories.agent_run_repository import AgentRunRepository
from cloudhelm_platform_api.repositories.approval_repository import ApprovalRepository
from cloudhelm_platform_api.repositories.design_repository import DesignRepository
from cloudhelm_platform_api.repositories.development_plan_repository import DevelopmentPlanRepository
from cloudhelm_platform_api.repositories.task_repository import TaskRepository
from cloudhelm_platform_api.schemas.approval import ApprovalRequestCreate, ApprovalRequestRead
from cloudhelm_platform_api.schemas.common import (
    ApprovalStatus,
    DevelopmentPlanStatus,
    PageInfo,
    PageResponse,
    ReviewStatus,
    TaskStatus,
)
from cloudhelm_platform_api.services.base import BaseService
from cloudhelm_platform_api.services.event_service import EventService
from cloudhelm_platform_api.services.exceptions import ServiceError
from cloudhelm_platform_api.services.review_invalidation_service import ReviewInvalidationService

DESIGN_APPROVAL_ACTION = "approve_technical_design"
PLAN_APPROVAL_ACTION = "approve_development_plan"
TERMINAL_TASK_STATUSES = {TaskStatus.DONE.value, TaskStatus.FAILED.value, TaskStatus.CANCELLED.value}


class ApprovalService(BaseService):
    """审批请求服务。"""

    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self.approvals = ApprovalRepository(session)
        self.tasks = TaskRepository(session)
        self.agent_runs = AgentRunRepository(session)
        self.designs = DesignRepository(session)
        self.plans = DevelopmentPlanRepository(session)
        self.events = EventService(session)
        self.review_invalidation = ReviewInvalidationService(session)

    def create_approval(self, task_id: UUID, data: ApprovalRequestCreate) -> ApprovalRequestRead:
        """创建审批请求并写入 ApprovalRequested 事件。"""

        self._require_active_task(task_id)
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
        self,
        limit: int,
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

        approval = self._require_pending_approval(approval_id)
        task = self._require_active_task(approval.task_id)
        resource_payload = self._approve_domain_resource(approval, task, actor_id, reason)
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
        self.commit()
        return ApprovalRequestRead.model_validate(approval)

    def reject(self, approval_id: UUID, actor_id: str, reason: str | None = None) -> ApprovalRequestRead:
        """拒绝审批并写入 ApprovalRejected 事件。"""

        approval = self._require_pending_approval(approval_id)
        task = self._require_active_task(approval.task_id)
        resource_payload = self._reject_domain_resource(approval, task, actor_id, reason)
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
        self.commit()
        return ApprovalRequestRead.model_validate(approval)

    def _require_approval(self, approval_id: UUID) -> ApprovalRequest:
        """读取审批请求或返回 404。"""

        approval = self.approvals.get(approval_id)
        if approval is None:
            raise ServiceError("approval_not_found", "审批请求不存在。", 404)
        return approval

    def _require_pending_approval(self, approval_id: UUID) -> ApprovalRequest:
        """读取待审批请求并校验状态。"""

        approval = self._require_approval(approval_id)
        if approval.status != ApprovalStatus.PENDING.value:
            raise ServiceError("invalid_approval_transition", "审批请求已决策，不能重复处理。", 409)
        return approval

    def _require_active_task(self, task_id: UUID):
        """审批决策必须关联仍可继续推进的任务。"""

        task = self.tasks.get(task_id)
        if task is None:
            raise ServiceError("task_not_found", "审批关联任务不存在。", 404)
        if task.status in TERMINAL_TASK_STATUSES:
            raise ServiceError("task_terminal", "终态任务不能继续处理审批。", 409)
        return task

    def _approve_domain_resource(self, approval: ApprovalRequest, task, actor_id: str, reason: str | None) -> dict:
        """同步通过设计或开发计划，并校验审批没有过期。"""

        if approval.action == DESIGN_APPROVAL_ACTION:
            design = self._current_design_for_approval(approval)
            design.status = ReviewStatus.APPROVED.value
            previous_phase = task.current_phase
            task.current_phase = "Planning"
            if task.status != TaskStatus.PAUSED.value:
                task.status = TaskStatus.RUNNING.value
            if previous_phase != task.current_phase:
                self.events.record(
                    "TaskPhaseChanged",
                    "user",
                    actor_id,
                    {
                        "task_id": str(task.id),
                        "from": previous_phase,
                        "to": task.current_phase,
                        "reason": reason or "技术设计审批通过。",
                    },
                    task.id,
                )
            self.events.record(
                "TechnicalDesignApproved",
                "user",
                actor_id,
                {"design_id": str(design.id), "reason": reason or "技术设计审批通过。"},
                task.id,
            )
            return {"design_id": str(design.id)}
        if approval.action == PLAN_APPROVAL_ACTION:
            plan = self._current_plan_for_approval(approval)
            plan.status = DevelopmentPlanStatus.APPROVED.value
            if task.status != TaskStatus.PAUSED.value:
                task.status = TaskStatus.RUNNING.value
            self.events.record(
                "DevelopmentPlanApproved",
                "user",
                actor_id,
                {"development_plan_id": str(plan.id), "reason": reason or "开发计划审批通过。"},
                task.id,
            )
            return {"development_plan_id": str(plan.id), "development_plan_status": plan.status}
        return {}

    def _reject_domain_resource(self, approval: ApprovalRequest, task, actor_id: str, reason: str | None) -> dict:
        """同步拒绝设计或开发计划，并回到可重新生成的阶段。"""

        if approval.action == DESIGN_APPROVAL_ACTION:
            design = self._current_design_for_approval(approval)
            design.status = ReviewStatus.CHANGES_REQUESTED.value
            previous_phase = task.current_phase
            if task.status != TaskStatus.PAUSED.value:
                task.status = TaskStatus.RUNNING.value
            task.current_phase = "Designing"
            if previous_phase != task.current_phase:
                self.events.record(
                    "TaskPhaseChanged",
                    "user",
                    actor_id,
                    {
                        "task_id": str(task.id),
                        "from": previous_phase,
                        "to": task.current_phase,
                        "reason": reason or "技术设计审批被拒绝。",
                    },
                    task.id,
                )
            self.review_invalidation.invalidate_after_design_change(
                task.id,
                design.id,
                actor_id,
                reason or "技术设计审批被拒绝，关联开发计划失效。",
            )
            self.events.record(
                "TechnicalDesignChangesRequested",
                "user",
                actor_id,
                {"design_id": str(design.id), "reason": reason or "技术设计审批被拒绝。"},
                task.id,
            )
            return {"design_id": str(design.id)}
        if approval.action == PLAN_APPROVAL_ACTION:
            plan = self._current_plan_for_approval(approval)
            plan.status = DevelopmentPlanStatus.CHANGES_REQUESTED.value
            if task.status != TaskStatus.PAUSED.value:
                task.status = TaskStatus.RUNNING.value
            task.current_phase = "Planning"
            self.events.record(
                "DevelopmentPlanChangesRequested",
                "user",
                actor_id,
                {"development_plan_id": str(plan.id), "reason": reason or "开发计划审批被拒绝。"},
                task.id,
            )
            return {"development_plan_id": str(plan.id), "development_plan_status": plan.status}
        return {}

    def _current_design_for_approval(self, approval: ApprovalRequest):
        """读取审批绑定的当前最新版技术设计。"""

        design = self.designs.latest_by_task(approval.task_id)
        if (
            design is None
            or approval.requested_by_agent_run_id is None
            or design.created_by_agent_run_id != approval.requested_by_agent_run_id
            or design.status == ReviewStatus.CHANGES_REQUESTED.value
        ):
            raise ServiceError("stale_approval", "审批不再对应当前最新版技术设计。", 409)
        return design

    def _current_plan_for_approval(self, approval: ApprovalRequest):
        """读取审批绑定的当前最新版开发计划。"""

        plan = self.plans.latest_by_task(approval.task_id)
        design = self.designs.latest_by_task(approval.task_id)
        if (
            plan is None
            or design is None
            or approval.requested_by_agent_run_id is None
            or plan.created_by_agent_run_id != approval.requested_by_agent_run_id
            or plan.technical_design_id != design.id
            or design.status != ReviewStatus.APPROVED.value
            or plan.status == DevelopmentPlanStatus.CHANGES_REQUESTED.value
        ):
            raise ServiceError("stale_approval", "审批不再对应当前最新版开发计划。", 409)
        return plan
