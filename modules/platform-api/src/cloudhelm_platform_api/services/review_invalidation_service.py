"""需求/设计返工时的下游产物失效处理。

Requirement 或 TechnicalDesign 被要求修改后，基于旧版本生成的设计、开发
计划和待审批记录都不能继续作为当前依据。本服务在调用方事务内统一完成
失效标记和事件写入，不主动提交。
"""

from uuid import UUID

from cloudhelm_platform_api.db.base import utc_now
from cloudhelm_platform_api.repositories.approval_repository import ApprovalRepository
from cloudhelm_platform_api.repositories.design_repository import DesignRepository
from cloudhelm_platform_api.repositories.development_plan_repository import DevelopmentPlanRepository
from cloudhelm_platform_api.schemas.common import ApprovalStatus, DevelopmentPlanStatus, ReviewStatus
from cloudhelm_platform_api.services.event_service import EventService

DESIGN_APPROVAL_ACTION = "approve_technical_design"
PLAN_APPROVAL_ACTION = "approve_development_plan"


class ReviewInvalidationService:
    """使旧设计、旧计划及其待审批记录失效。"""

    def __init__(self, session) -> None:
        self.designs = DesignRepository(session)
        self.plans = DevelopmentPlanRepository(session)
        self.approvals = ApprovalRepository(session)
        self.events = EventService(session)

    def invalidate_after_requirement_change(self, task_id: UUID, actor_id: str, reason: str) -> None:
        """需求返工时使当前技术设计和开发计划失效。"""

        design = self.designs.latest_by_task(task_id)
        if design is not None:
            if design.status != ReviewStatus.CHANGES_REQUESTED.value:
                design.status = ReviewStatus.CHANGES_REQUESTED.value
                self.events.record(
                    "TechnicalDesignChangesRequested",
                    "system",
                    actor_id,
                    {
                        "design_id": str(design.id),
                        "reason": reason,
                        "invalidated_by": "requirement_change",
                    },
                    task_id,
                )
            self._reject_pending_approval(
                task_id,
                DESIGN_APPROVAL_ACTION,
                design.created_by_agent_run_id,
                actor_id,
                reason,
            )
        self._invalidate_latest_plan(task_id, None, actor_id, reason, "requirement_change")

    def invalidate_after_design_change(
        self,
        task_id: UUID,
        design_id: UUID,
        actor_id: str,
        reason: str,
    ) -> None:
        """技术设计返工时使基于该设计的当前开发计划失效。"""

        self._invalidate_latest_plan(task_id, design_id, actor_id, reason, "design_change")

    def reject_design_approval(
        self,
        task_id: UUID,
        agent_run_id: UUID | None,
        actor_id: str,
        reason: str,
    ) -> None:
        """拒绝当前设计对应的待审批记录。"""

        self._reject_pending_approval(
            task_id,
            DESIGN_APPROVAL_ACTION,
            agent_run_id,
            actor_id,
            reason,
        )

    def _invalidate_latest_plan(
        self,
        task_id: UUID,
        design_id: UUID | None,
        actor_id: str,
        reason: str,
        invalidated_by: str,
    ) -> None:
        """标记当前计划返工，并关闭其待审批记录。"""

        plan = self.plans.latest_by_task(task_id)
        if plan is None or (design_id is not None and plan.technical_design_id != design_id):
            return
        if plan.status != DevelopmentPlanStatus.CHANGES_REQUESTED.value:
            plan.status = DevelopmentPlanStatus.CHANGES_REQUESTED.value
            self.events.record(
                "DevelopmentPlanChangesRequested",
                "system",
                actor_id,
                {
                    "development_plan_id": str(plan.id),
                    "reason": reason,
                    "invalidated_by": invalidated_by,
                },
                task_id,
            )
        self._reject_pending_approval(
            task_id,
            PLAN_APPROVAL_ACTION,
            plan.created_by_agent_run_id,
            actor_id,
            reason,
        )

    def _reject_pending_approval(
        self,
        task_id: UUID,
        action: str,
        agent_run_id: UUID | None,
        actor_id: str,
        reason: str,
    ) -> None:
        """关闭与当前产物 AgentRun 匹配的待审批记录。"""

        if agent_run_id is None:
            return
        approval = self.approvals.latest_by_task_and_action(task_id, action)
        if (
            approval is None
            or approval.status != ApprovalStatus.PENDING.value
            or approval.requested_by_agent_run_id != agent_run_id
        ):
            return
        approval.status = ApprovalStatus.REJECTED.value
        approval.decided_by = actor_id
        approval.decided_at = utc_now()
        self.events.record(
            "ApprovalRejected",
            "system",
            actor_id,
            {
                "approval_id": str(approval.id),
                "action": approval.action,
                "reason": reason,
                "invalidated": True,
            },
            task_id,
        )
