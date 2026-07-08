"""TechnicalDesign 业务服务。"""

from uuid import UUID

from sqlalchemy.orm import Session

from cloudhelm_platform_api.models.design import TechnicalDesign
from cloudhelm_platform_api.repositories.agent_run_repository import AgentRunRepository
from cloudhelm_platform_api.repositories.design_repository import DesignRepository
from cloudhelm_platform_api.repositories.requirement_repository import RequirementRepository
from cloudhelm_platform_api.repositories.task_repository import TaskRepository
from cloudhelm_platform_api.schemas.common import PageInfo, PageResponse, ReviewStatus
from cloudhelm_platform_api.schemas.design import TechnicalDesignCreate, TechnicalDesignRead
from cloudhelm_platform_api.services.base import BaseService
from cloudhelm_platform_api.services.event_service import EventService
from cloudhelm_platform_api.services.exceptions import ServiceError


class DesignService(BaseService):
    """技术设计用例服务。"""

    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self.designs = DesignRepository(session)
        self.tasks = TaskRepository(session)
        self.requirements = RequirementRepository(session)
        self.agent_runs = AgentRunRepository(session)
        self.events = EventService(session)

    def create_design(self, task_id: UUID, data: TechnicalDesignCreate) -> TechnicalDesignRead:
        """为任务创建技术设计并写入事件。"""

        task = self.tasks.get(task_id)
        if task is None:
            raise ServiceError("task_not_found", "创建技术设计失败：任务不存在。", 404)
        requirement = self.requirements.get(data.requirement_spec_id)
        if requirement is None or requirement.task_id != task_id:
            raise ServiceError("requirement_not_found", "关联需求规格不存在或不属于该任务。", 404)
        if data.created_by_agent_run_id and self.agent_runs.get(data.created_by_agent_run_id) is None:
            raise ServiceError("agent_run_not_found", "创建技术设计失败：AgentRun 不存在。", 404)
        design = self.designs.create(
            TechnicalDesign(
                task_id=task.id,
                status=ReviewStatus.DRAFT.value,
                **data.model_dump(mode="json"),
            )
        )
        self.events.record(
            "TechnicalDesignCreated",
            "user",
            "user",
            {"design_id": str(design.id), "requirement_id": str(requirement.id)},
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
        design.status = ReviewStatus.APPROVED.value
        self.events.record(
            "TechnicalDesignApproved",
            "user",
            actor_id,
            {"design_id": str(design.id), "reason": reason},
            design.task_id,
        )
        self.commit()
        return TechnicalDesignRead.model_validate(design)

    def request_changes(self, design_id: UUID, actor_id: str, reason: str | None = None) -> TechnicalDesignRead:
        """要求修改技术设计并写入事件。"""

        design = self._require_design(design_id)
        design.status = ReviewStatus.CHANGES_REQUESTED.value
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
