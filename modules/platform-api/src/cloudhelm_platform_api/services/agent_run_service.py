"""AgentRun 业务服务。"""

from uuid import UUID

from sqlalchemy.orm import Session

from cloudhelm_platform_api.models.agent_run import AgentRun
from cloudhelm_platform_api.repositories.agent_run_repository import AgentRunRepository
from cloudhelm_platform_api.repositories.task_repository import TaskRepository
from cloudhelm_platform_api.schemas.agent_run import AgentRunCreate, AgentRunRead
from cloudhelm_platform_api.schemas.common import PageInfo, PageResponse
from cloudhelm_platform_api.services.base import BaseService
from cloudhelm_platform_api.services.event_service import EventService
from cloudhelm_platform_api.services.exceptions import ServiceError


class AgentRunService(BaseService):
    """AgentRun 记录服务。"""

    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self.agent_runs = AgentRunRepository(session)
        self.tasks = TaskRepository(session)
        self.events = EventService(session)

    def create_agent_run(self, task_id: UUID, data: AgentRunCreate) -> AgentRunRead:
        """创建开发/内部联调用 AgentRun 记录。"""

        if self.tasks.get(task_id) is None:
            raise ServiceError("task_not_found", "创建 AgentRun 失败：任务不存在。", 404)
        agent_run = self.agent_runs.create(AgentRun(task_id=task_id, **data.model_dump(mode="json")))
        self.events.record(
            "AgentRunRecorded",
            "system",
            data.agent_type,
            {"agent_run_id": str(agent_run.id), "agent_type": agent_run.agent_type, "status": agent_run.status},
            task_id,
        )
        self.commit()
        return AgentRunRead.model_validate(agent_run)

    def get_agent_run(self, run_id: UUID) -> AgentRunRead:
        """读取 AgentRun。"""

        agent_run = self.agent_runs.get(run_id)
        if agent_run is None:
            raise ServiceError("agent_run_not_found", "AgentRun 不存在。", 404)
        return AgentRunRead.model_validate(agent_run)

    def list_by_task(self, task_id: UUID, limit: int, cursor: str | None) -> PageResponse[AgentRunRead]:
        """分页读取某任务 AgentRun。"""

        if self.tasks.get(task_id) is None:
            raise ServiceError("task_not_found", "任务不存在。", 404)
        items, next_cursor = self.agent_runs.list_by_task(task_id, limit, cursor)
        return PageResponse(
            items=[AgentRunRead.model_validate(item) for item in items],
            page=PageInfo(limit=limit, next_cursor=next_cursor),
        )
