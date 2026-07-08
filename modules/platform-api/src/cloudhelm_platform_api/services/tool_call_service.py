"""ToolCall 业务服务。"""

from uuid import UUID

from sqlalchemy.orm import Session

from cloudhelm_platform_api.models.tool_call import ToolCall
from cloudhelm_platform_api.repositories.agent_run_repository import AgentRunRepository
from cloudhelm_platform_api.repositories.approval_repository import ApprovalRepository
from cloudhelm_platform_api.repositories.task_repository import TaskRepository
from cloudhelm_platform_api.repositories.tool_call_repository import ToolCallRepository
from cloudhelm_platform_api.schemas.common import PageInfo, PageResponse
from cloudhelm_platform_api.schemas.tool_call import ToolCallCreate, ToolCallRead, tool_call_to_read
from cloudhelm_platform_api.services.base import BaseService
from cloudhelm_platform_api.services.event_service import EventService
from cloudhelm_platform_api.services.exceptions import ServiceError


class ToolCallService(BaseService):
    """ToolCall 记录服务。"""

    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self.tool_calls = ToolCallRepository(session)
        self.tasks = TaskRepository(session)
        self.agent_runs = AgentRunRepository(session)
        self.approvals = ApprovalRepository(session)
        self.events = EventService(session)

    def create_tool_call(self, task_id: UUID, data: ToolCallCreate) -> ToolCallRead:
        """创建开发/内部联调用 ToolCall 记录。"""

        if self.tasks.get(task_id) is None:
            raise ServiceError("task_not_found", "创建 ToolCall 失败：任务不存在。", 404)
        if data.agent_run_id and self.agent_runs.get(data.agent_run_id) is None:
            raise ServiceError("agent_run_not_found", "创建 ToolCall 失败：AgentRun 不存在。", 404)
        if data.approval_id and self.approvals.get(data.approval_id) is None:
            raise ServiceError("approval_not_found", "创建 ToolCall 失败：审批请求不存在。", 404)
        tool_call = self.tool_calls.create(ToolCall(task_id=task_id, **data.model_dump(mode="json")))
        self.events.record(
            "ToolCallRecorded",
            "system",
            data.tool_name,
            {"tool_call_id": str(tool_call.id), "tool_name": tool_call.tool_name, "risk_level": tool_call.risk_level},
            task_id,
        )
        self.commit()
        return tool_call_to_read(tool_call)

    def get_tool_call(self, tool_call_id: UUID) -> ToolCallRead:
        """读取 ToolCall。"""

        tool_call = self.tool_calls.get(tool_call_id)
        if tool_call is None:
            raise ServiceError("tool_call_not_found", "ToolCall 不存在。", 404)
        return tool_call_to_read(tool_call)

    def list_by_task(self, task_id: UUID, limit: int, cursor: str | None) -> PageResponse[ToolCallRead]:
        """分页读取某任务 ToolCall。"""

        if self.tasks.get(task_id) is None:
            raise ServiceError("task_not_found", "任务不存在。", 404)
        items, next_cursor = self.tool_calls.list_by_task(task_id, limit, cursor)
        return PageResponse(
            items=[tool_call_to_read(item) for item in items],
            page=PageInfo(limit=limit, next_cursor=next_cursor),
        )
