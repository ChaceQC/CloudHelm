"""设计/开发计划审批对领域资源和 Task 阶段的同步更新。"""

from cloudhelm_platform_api.models.approval import ApprovalRequest
from cloudhelm_platform_api.repositories.design_repository import DesignRepository
from cloudhelm_platform_api.repositories.development_plan_repository import (
    DevelopmentPlanRepository,
)
from cloudhelm_platform_api.schemas.common import (
    DevelopmentPlanStatus,
    ReviewStatus,
    TaskStatus,
)
from cloudhelm_platform_api.services.event_service import EventService
from cloudhelm_platform_api.services.exceptions import ServiceError
from cloudhelm_platform_api.services.review_invalidation_service import (
    ReviewInvalidationService,
)

DESIGN_APPROVAL_ACTION = "approve_technical_design"
PLAN_APPROVAL_ACTION = "approve_development_plan"


class ApprovalDomainDecisionService:
    """同步审批对应的设计/计划状态、Task 阶段和失效链。"""

    def __init__(self, session) -> None:
        self.designs = DesignRepository(session)
        self.plans = DevelopmentPlanRepository(session)
        self.events = EventService(session)
        self.review_invalidation = ReviewInvalidationService(session)

    def approve(
        self,
        approval: ApprovalRequest,
        task,
        actor_id: str,
        reason: str | None,
    ) -> dict:
        """通过设计或开发计划，并校验审批仍绑定最新版资源。"""

        if approval.action == DESIGN_APPROVAL_ACTION:
            design = self._current_design(approval)
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
                {
                    "design_id": str(design.id),
                    "reason": reason or "技术设计审批通过。",
                },
                task.id,
            )
            return {"design_id": str(design.id)}
        if approval.action == PLAN_APPROVAL_ACTION:
            plan = self._current_plan(approval)
            plan.status = DevelopmentPlanStatus.APPROVED.value
            if task.status != TaskStatus.PAUSED.value:
                task.status = TaskStatus.RUNNING.value
            self.events.record(
                "DevelopmentPlanApproved",
                "user",
                actor_id,
                {
                    "development_plan_id": str(plan.id),
                    "reason": reason or "开发计划审批通过。",
                },
                task.id,
            )
            return {
                "development_plan_id": str(plan.id),
                "development_plan_status": plan.status,
            }
        return {}

    def reject(
        self,
        approval: ApprovalRequest,
        task,
        actor_id: str,
        reason: str | None,
    ) -> dict:
        """拒绝设计或开发计划，并同步回退阶段和下游失效。"""

        if approval.action == DESIGN_APPROVAL_ACTION:
            design = self._current_design(approval)
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
                {
                    "design_id": str(design.id),
                    "reason": reason or "技术设计审批被拒绝。",
                },
                task.id,
            )
            return {"design_id": str(design.id)}
        if approval.action == PLAN_APPROVAL_ACTION:
            plan = self._current_plan(approval)
            plan.status = DevelopmentPlanStatus.CHANGES_REQUESTED.value
            if task.status != TaskStatus.PAUSED.value:
                task.status = TaskStatus.RUNNING.value
            task.current_phase = "Planning"
            self.events.record(
                "DevelopmentPlanChangesRequested",
                "user",
                actor_id,
                {
                    "development_plan_id": str(plan.id),
                    "reason": reason or "开发计划审批被拒绝。",
                },
                task.id,
            )
            return {
                "development_plan_id": str(plan.id),
                "development_plan_status": plan.status,
            }
        return {}

    def _current_design(self, approval: ApprovalRequest):
        """读取审批绑定的当前最新版技术设计。"""

        design = self.designs.latest_by_task(approval.task_id)
        if (
            design is None
            or approval.requested_by_agent_run_id is None
            or design.created_by_agent_run_id
            != approval.requested_by_agent_run_id
            or design.status == ReviewStatus.CHANGES_REQUESTED.value
        ):
            raise ServiceError(
                "stale_approval",
                "审批不再对应当前最新版技术设计。",
                409,
            )
        return design

    def _current_plan(self, approval: ApprovalRequest):
        """读取审批绑定的当前最新版开发计划。"""

        plan = self.plans.latest_by_task(approval.task_id)
        design = self.designs.latest_by_task(approval.task_id)
        if (
            plan is None
            or design is None
            or approval.requested_by_agent_run_id is None
            or plan.created_by_agent_run_id
            != approval.requested_by_agent_run_id
            or plan.technical_design_id != design.id
            or design.status != ReviewStatus.APPROVED.value
            or plan.status == DevelopmentPlanStatus.CHANGES_REQUESTED.value
        ):
            raise ServiceError(
                "stale_approval",
                "审批不再对应当前最新版开发计划。",
                409,
            )
        return plan
