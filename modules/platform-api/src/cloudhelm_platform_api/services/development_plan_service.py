"""DevelopmentPlan 业务服务。"""

from uuid import UUID

from sqlalchemy.orm import Session

from cloudhelm_platform_api.models.development_plan import DevelopmentPlan
from cloudhelm_platform_api.repositories.development_plan_repository import DevelopmentPlanRepository
from cloudhelm_platform_api.repositories.task_repository import TaskRepository
from cloudhelm_platform_api.schemas.common import PageInfo, PageResponse
from cloudhelm_platform_api.schemas.development_plan import DevelopmentPlanCreate, DevelopmentPlanRead
from cloudhelm_platform_api.services.base import BaseService
from cloudhelm_platform_api.services.exceptions import ServiceError


class DevelopmentPlanService(BaseService):
    """DevelopmentPlan 查询和内部创建服务。"""

    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self.plans = DevelopmentPlanRepository(session)
        self.tasks = TaskRepository(session)

    def create_plan(self, task_id: UUID, data: DevelopmentPlanCreate) -> DevelopmentPlan:
        """在当前事务内创建开发计划，不主动提交。

        调用方负责同步写入 AgentRun、Task 状态和 EventLog 后统一提交。
        """

        task = self.tasks.get(task_id)
        if task is None:
            raise ServiceError("task_not_found", "创建开发计划失败：任务不存在。", 404)
        return self.plans.create(
            DevelopmentPlan(
                task_id=task.id,
                project_id=task.project_id,
                **data.model_dump(mode="json"),
            )
        )

    def get_plan(self, plan_id: UUID) -> DevelopmentPlanRead:
        """读取单个开发计划。"""

        plan = self.plans.get(plan_id)
        if plan is None:
            raise ServiceError("development_plan_not_found", "开发计划不存在。", 404)
        return DevelopmentPlanRead.model_validate(plan)

    def list_by_task(self, task_id: UUID, limit: int, cursor: str | None) -> PageResponse[DevelopmentPlanRead]:
        """分页读取某任务下的开发计划。"""

        if self.tasks.get(task_id) is None:
            raise ServiceError("task_not_found", "任务不存在。", 404)
        items, next_cursor = self.plans.list_by_task(task_id, limit, cursor)
        return PageResponse(
            items=[DevelopmentPlanRead.model_validate(item) for item in items],
            page=PageInfo(limit=limit, next_cursor=next_cursor),
        )
