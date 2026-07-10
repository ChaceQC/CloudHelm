"""RequirementSpec 业务服务。"""

from uuid import UUID

from sqlalchemy.orm import Session

from cloudhelm_platform_api.models.requirement import RequirementSpec
from cloudhelm_platform_api.repositories.requirement_repository import RequirementRepository
from cloudhelm_platform_api.repositories.task_repository import TaskRepository
from cloudhelm_platform_api.schemas.common import PageInfo, PageResponse, ReviewStatus, TaskStatus
from cloudhelm_platform_api.schemas.requirement import RequirementSpecCreate, RequirementSpecRead
from cloudhelm_platform_api.services.base import BaseService
from cloudhelm_platform_api.services.event_service import EventService
from cloudhelm_platform_api.services.exceptions import ServiceError
from cloudhelm_platform_api.services.review_invalidation_service import ReviewInvalidationService

TERMINAL_TASK_STATUSES = {TaskStatus.DONE.value, TaskStatus.FAILED.value, TaskStatus.CANCELLED.value}


class RequirementService(BaseService):
    """需求规格用例服务。"""

    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self.requirements = RequirementRepository(session)
        self.tasks = TaskRepository(session)
        self.events = EventService(session)
        self.review_invalidation = ReviewInvalidationService(session)

    def create_requirement(self, task_id: UUID, data: RequirementSpecCreate) -> RequirementSpecRead:
        """为任务创建需求规格并写入事件。"""

        task = self.tasks.get(task_id)
        if task is None:
            raise ServiceError("task_not_found", "创建需求失败：任务不存在。", 404)
        self._ensure_task_mutable(task.status)
        requirement = self.requirements.create(
            RequirementSpec(
                task_id=task.id,
                project_id=task.project_id,
                status=ReviewStatus.DRAFT.value,
                **data.model_dump(),
            )
        )
        self.events.record(
            "RequirementSpecCreated",
            "user",
            "user",
            {"requirement_id": str(requirement.id), "task_id": str(task.id)},
            task.id,
        )
        self.commit()
        return RequirementSpecRead.model_validate(requirement)

    def get_requirement(self, requirement_id: UUID) -> RequirementSpecRead:
        """读取需求规格。"""

        return RequirementSpecRead.model_validate(self._require_requirement(requirement_id))

    def list_by_task(self, task_id: UUID, limit: int, cursor: str | None) -> PageResponse[RequirementSpecRead]:
        """分页读取某任务需求规格。"""

        self._require_task(task_id)
        items, next_cursor = self.requirements.list_by_task(task_id, limit, cursor)
        return PageResponse(
            items=[RequirementSpecRead.model_validate(item) for item in items],
            page=PageInfo(limit=limit, next_cursor=next_cursor),
        )

    def approve(self, requirement_id: UUID, actor_id: str, reason: str | None = None) -> RequirementSpecRead:
        """通过需求规格并写入事件。"""

        requirement = self._require_requirement(requirement_id)
        task = self.tasks.get(requirement.task_id)
        if task is not None:
            self._ensure_task_mutable(task.status)
        if requirement.status != ReviewStatus.DRAFT.value:
            raise ServiceError("invalid_requirement_review_transition", "只有 draft 需求规格可以通过。", 409)
        requirement.status = ReviewStatus.APPROVED.value
        self.events.record(
            "RequirementSpecApproved",
            "user",
            actor_id,
            {"requirement_id": str(requirement.id), "reason": reason},
            requirement.task_id,
        )
        self.commit()
        return RequirementSpecRead.model_validate(requirement)

    def request_changes(self, requirement_id: UUID, actor_id: str, reason: str | None = None) -> RequirementSpecRead:
        """要求修改需求规格并写入事件。"""

        requirement = self._require_requirement(requirement_id)
        task = self.tasks.get(requirement.task_id)
        if task is not None:
            self._ensure_task_mutable(task.status)
        if requirement.status not in {ReviewStatus.DRAFT.value, ReviewStatus.APPROVED.value}:
            raise ServiceError("invalid_requirement_review_transition", "当前需求规格不能重复要求修改。", 409)
        requirement.status = ReviewStatus.CHANGES_REQUESTED.value
        if task is not None:
            previous_phase = task.current_phase
            if task.status != TaskStatus.PAUSED.value:
                task.status = TaskStatus.RUNNING.value
            task.current_phase = "RequirementClarifying"
            if previous_phase != task.current_phase:
                self.events.record(
                    "TaskPhaseChanged",
                    "user",
                    actor_id,
                    {"task_id": str(task.id), "from": previous_phase, "to": task.current_phase, "reason": reason or "需求规格要求修改"},
                    task.id,
                )
            self.review_invalidation.invalidate_after_requirement_change(
                task.id,
                actor_id,
                reason or "需求规格要求修改，旧设计与计划失效。",
            )
        self.events.record(
            "RequirementSpecChangesRequested",
            "user",
            actor_id,
            {"requirement_id": str(requirement.id), "reason": reason},
            requirement.task_id,
        )
        self.commit()
        return RequirementSpecRead.model_validate(requirement)

    def _require_requirement(self, requirement_id: UUID) -> RequirementSpec:
        """读取需求规格或返回 404。"""

        requirement = self.requirements.get(requirement_id)
        if requirement is None:
            raise ServiceError("requirement_not_found", "需求规格不存在。", 404)
        return requirement

    def _require_task(self, task_id: UUID) -> None:
        """确认任务存在。"""

        if self.tasks.get(task_id) is None:
            raise ServiceError("task_not_found", "任务不存在。", 404)

    def _ensure_task_mutable(self, status: str) -> None:
        """终态任务不得继续创建或评审需求。"""

        if status in TERMINAL_TASK_STATUSES:
            raise ServiceError("task_terminal", "终态任务不能继续修改需求规格。", 409)
