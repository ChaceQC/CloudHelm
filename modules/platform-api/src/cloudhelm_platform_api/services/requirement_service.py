"""RequirementSpec 业务服务。"""

from uuid import UUID

from sqlalchemy.orm import Session

from cloudhelm_platform_api.models.requirement import RequirementSpec
from cloudhelm_platform_api.repositories.requirement_repository import RequirementRepository
from cloudhelm_platform_api.repositories.task_repository import TaskRepository
from cloudhelm_platform_api.schemas.common import PageInfo, PageResponse, ReviewStatus
from cloudhelm_platform_api.schemas.requirement import RequirementSpecCreate, RequirementSpecRead
from cloudhelm_platform_api.services.base import BaseService
from cloudhelm_platform_api.services.event_service import EventService
from cloudhelm_platform_api.services.exceptions import ServiceError


class RequirementService(BaseService):
    """需求规格用例服务。"""

    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self.requirements = RequirementRepository(session)
        self.tasks = TaskRepository(session)
        self.events = EventService(session)

    def create_requirement(self, task_id: UUID, data: RequirementSpecCreate) -> RequirementSpecRead:
        """为任务创建需求规格并写入事件。"""

        task = self.tasks.get(task_id)
        if task is None:
            raise ServiceError("task_not_found", "创建需求失败：任务不存在。", 404)
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
        requirement.status = ReviewStatus.CHANGES_REQUESTED.value
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
