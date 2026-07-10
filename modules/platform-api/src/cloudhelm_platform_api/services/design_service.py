"""TechnicalDesign 业务服务。"""

from uuid import UUID

from sqlalchemy.orm import Session

from cloudhelm_platform_api.db.base import utc_now
from cloudhelm_platform_api.models.design import TechnicalDesign
from cloudhelm_platform_api.repositories.agent_run_repository import AgentRunRepository
from cloudhelm_platform_api.repositories.approval_repository import ApprovalRepository
from cloudhelm_platform_api.repositories.design_repository import DesignRepository
from cloudhelm_platform_api.repositories.requirement_repository import RequirementRepository
from cloudhelm_platform_api.repositories.task_repository import TaskRepository
from cloudhelm_platform_api.schemas.common import ApprovalStatus, PageInfo, PageResponse, ReviewStatus, TaskStatus
from cloudhelm_platform_api.schemas.design import TechnicalDesignCreate, TechnicalDesignRead
from cloudhelm_platform_api.services.base import BaseService
from cloudhelm_platform_api.services.event_service import EventService
from cloudhelm_platform_api.services.exceptions import ServiceError
from cloudhelm_platform_api.services.review_invalidation_service import ReviewInvalidationService

TERMINAL_TASK_STATUSES = {TaskStatus.DONE.value, TaskStatus.FAILED.value, TaskStatus.CANCELLED.value}


class DesignService(BaseService):
    """技术设计用例服务。"""

    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self.designs = DesignRepository(session)
        self.tasks = TaskRepository(session)
        self.requirements = RequirementRepository(session)
        self.agent_runs = AgentRunRepository(session)
        self.approvals = ApprovalRepository(session)
        self.events = EventService(session)
        self.review_invalidation = ReviewInvalidationService(session)

    def create_design(self, task_id: UUID, data: TechnicalDesignCreate) -> TechnicalDesignRead:
        """为任务创建技术设计并写入事件。"""

        task = self.tasks.get(task_id)
        if task is None:
            raise ServiceError("task_not_found", "创建技术设计失败：任务不存在。", 404)
        self._ensure_task_mutable(task.status)
        requirement = self.requirements.get(data.requirement_spec_id)
        if requirement is None or requirement.task_id != task_id:
            raise ServiceError("requirement_not_found", "关联需求规格不存在或不属于该任务。", 404)
        current_requirement = self.requirements.latest_by_task(task_id)
        if current_requirement is None or current_requirement.id != requirement.id:
            raise ServiceError("stale_requirement", "只能基于当前最新版需求规格创建设计。", 409)
        if requirement.status != ReviewStatus.APPROVED.value:
            raise ServiceError("requirement_not_approved", "需求规格通过后才能创建技术设计。", 409)
        agent_run = self.agent_runs.get(data.created_by_agent_run_id) if data.created_by_agent_run_id else None
        if data.created_by_agent_run_id and agent_run is None:
            raise ServiceError("agent_run_not_found", "创建技术设计失败：AgentRun 不存在。", 404)
        if agent_run is not None and agent_run.task_id != task_id:
            raise ServiceError("agent_run_task_mismatch", "创建技术设计失败：AgentRun 不属于当前任务。", 409)
        previous_design = self.designs.latest_by_task(task.id)
        design = self.designs.create(
            TechnicalDesign(
                task_id=task.id,
                status=ReviewStatus.DRAFT.value,
                version=(previous_design.version + 1) if previous_design is not None else 1,
                **data.model_dump(mode="json"),
            )
        )
        self._move_task_to_phase(task, "Designing", "创建了新的技术设计版本。", "user")
        if previous_design is not None:
            self.review_invalidation.invalidate_after_design_change(
                task.id,
                previous_design.id,
                "user",
                "新技术设计版本已创建，旧开发计划失效。",
            )
            self.review_invalidation.reject_design_approval(
                task.id,
                previous_design.created_by_agent_run_id,
                "user",
                "新技术设计版本已创建，旧设计审批失效。",
            )
        self.events.record(
            "TechnicalDesignCreated",
            "user",
            "user",
            {"design_id": str(design.id), "requirement_id": str(requirement.id), "version": design.version},
            task.id,
        )
        self.commit()
        return TechnicalDesignRead.model_validate(design)

    def get_design(self, design_id: UUID) -> TechnicalDesignRead:
        """读取技术设计。"""

        return TechnicalDesignRead.model_validate(self._require_design(design_id))

    def list_by_task(self, task_id: UUID, limit: int, cursor: str | None) -> PageResponse[TechnicalDesignRead]:
        """分页读取某任务技术设计。"""

        if self.tasks.get(task_id) is None:
            raise ServiceError("task_not_found", "任务不存在。", 404)
        items, next_cursor = self.designs.list_by_task(task_id, limit, cursor)
        return PageResponse(
            items=[TechnicalDesignRead.model_validate(item) for item in items],
            page=PageInfo(limit=limit, next_cursor=next_cursor),
        )

    def approve(self, design_id: UUID, actor_id: str, reason: str | None = None) -> TechnicalDesignRead:
        """通过技术设计并写入事件。"""

        design = self._require_design(design_id)
        self._ensure_current_design(design)
        task = self.tasks.get(design.task_id)
        if task is not None:
            self._ensure_task_mutable(task.status)
        if design.status != ReviewStatus.DRAFT.value:
            raise ServiceError("invalid_design_review_transition", "只有 draft 技术设计可以通过。", 409)
        design.status = ReviewStatus.APPROVED.value
        approval = self._matching_pending_design_approval(design)
        if approval is not None:
            approval.status = ApprovalStatus.APPROVED.value
            approval.decided_by = actor_id
            approval.decided_at = utc_now()
            self.events.record(
                "ApprovalApproved",
                "system",
                actor_id,
                {
                    "approval_id": str(approval.id),
                    "action": approval.action,
                    "reason": reason,
                    "design_id": str(design.id),
                },
                design.task_id,
            )
        self.events.record(
            "TechnicalDesignApproved",
            "user",
            actor_id,
            {"design_id": str(design.id), "reason": reason},
            design.task_id,
        )
        if task is not None:
            self._move_task_to_phase(task, "Planning", reason or "技术设计已通过。", actor_id)
        self.commit()
        return TechnicalDesignRead.model_validate(design)

    def request_changes(self, design_id: UUID, actor_id: str, reason: str | None = None) -> TechnicalDesignRead:
        """要求修改技术设计并写入事件。"""

        design = self._require_design(design_id)
        self._ensure_current_design(design)
        task = self.tasks.get(design.task_id)
        if task is not None:
            self._ensure_task_mutable(task.status)
        if design.status not in {ReviewStatus.DRAFT.value, ReviewStatus.APPROVED.value}:
            raise ServiceError("invalid_design_review_transition", "当前技术设计不能重复要求修改。", 409)
        design.status = ReviewStatus.CHANGES_REQUESTED.value
        if task is not None:
            self._move_task_to_phase(task, "Designing", reason or "技术设计要求修改", actor_id)
            self.review_invalidation.invalidate_after_design_change(
                task.id,
                design.id,
                actor_id,
                reason or "技术设计要求修改，关联开发计划失效。",
            )
        self.review_invalidation.reject_design_approval(
            design.task_id,
            design.created_by_agent_run_id,
            actor_id,
            reason or "技术设计要求修改。",
        )
        self.events.record(
            "TechnicalDesignChangesRequested",
            "user",
            actor_id,
            {"design_id": str(design.id), "reason": reason},
            design.task_id,
        )
        self.commit()
        return TechnicalDesignRead.model_validate(design)

    def _require_design(self, design_id: UUID) -> TechnicalDesign:
        """读取技术设计或返回 404。"""

        design = self.designs.get(design_id)
        if design is None:
            raise ServiceError("technical_design_not_found", "技术设计不存在。", 404)
        return design

    def _matching_pending_design_approval(self, design: TechnicalDesign):
        """读取与当前设计 AgentRun 匹配的待审批记录。"""

        if design.created_by_agent_run_id is None:
            return None
        approval = self.approvals.latest_by_task_and_action(design.task_id, "approve_technical_design")
        if (
            approval is not None
            and approval.status == ApprovalStatus.PENDING.value
            and approval.requested_by_agent_run_id == design.created_by_agent_run_id
        ):
            return approval
        return None

    def _ensure_task_mutable(self, status: str) -> None:
        """终态任务不得继续创建或评审技术设计。"""

        if status in TERMINAL_TASK_STATUSES:
            raise ServiceError("task_terminal", "终态任务不能继续修改技术设计。", 409)

    def _ensure_current_design(self, design: TechnicalDesign) -> None:
        """旧版本 TechnicalDesign 不得改变当前任务状态或计划。"""

        current = self.designs.latest_by_task(design.task_id)
        if current is None or current.id != design.id:
            raise ServiceError("stale_technical_design", "只能评审当前最新版技术设计。", 409)

    def _move_task_to_phase(self, task, target_phase: str, reason: str, actor_id: str) -> None:
        """更新任务阶段；暂停任务保留 paused 运行状态。"""

        previous_phase = task.current_phase
        if task.status != TaskStatus.PAUSED.value:
            task.status = TaskStatus.RUNNING.value
        task.current_phase = target_phase
        if previous_phase != target_phase:
            self.events.record(
                "TaskPhaseChanged",
                "user",
                actor_id,
                {
                    "task_id": str(task.id),
                    "from": previous_phase,
                    "to": target_phase,
                    "reason": reason,
                },
                task.id,
            )
