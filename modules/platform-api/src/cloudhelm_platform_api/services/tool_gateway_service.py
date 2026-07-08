"""Platform API Tool Gateway 集成服务。"""

from uuid import UUID

from sqlalchemy.orm import Session

from cloudhelm_platform_api.db.base import utc_now
from cloudhelm_platform_api.models.approval import ApprovalRequest
from cloudhelm_platform_api.models.tool_call import ToolCall
from cloudhelm_platform_api.repositories.agent_run_repository import AgentRunRepository
from cloudhelm_platform_api.repositories.approval_repository import ApprovalRepository
from cloudhelm_platform_api.repositories.task_repository import TaskRepository
from cloudhelm_platform_api.repositories.tool_call_repository import ToolCallRepository
from cloudhelm_platform_api.schemas.common import ApprovalStatus, PageInfo, PageResponse, ToolCallStatus
from cloudhelm_platform_api.schemas.tool_call import ToolCallRead, tool_call_to_read
from cloudhelm_platform_api.schemas.tool_gateway import ToolDeclarationRead, ToolGatewayCallCreate
from cloudhelm_platform_api.services.base import BaseService
from cloudhelm_platform_api.services.event_service import EventService
from cloudhelm_platform_api.services.exceptions import ServiceError
from cloudhelm_tool_gateway import ToolCallRequest, create_default_gateway
from cloudhelm_tool_gateway.schemas.tool_call import RiskLevel as GatewayRiskLevel


class ToolGatewayService(BaseService):
    """在数据库事务内执行 Tool Gateway 并记录 ToolCall、Approval 和 Event。"""

    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self.tasks = TaskRepository(session)
        self.agent_runs = AgentRunRepository(session)
        self.tool_calls = ToolCallRepository(session)
        self.approvals = ApprovalRepository(session)
        self.events = EventService(session)
        self.gateway = create_default_gateway()

    def list_tools(self) -> PageResponse[ToolDeclarationRead]:
        """列出 Tool Gateway 当前注册工具。"""

        items = [ToolDeclarationRead.model_validate(item) for item in self.gateway.list_tools()]
        return PageResponse(items=items, page=PageInfo(limit=len(items), next_cursor=None))

    def call_tool(self, task_id: UUID, data: ToolGatewayCallCreate) -> ToolCallRead:
        """执行本地工具或为高风险工具创建审批请求。"""

        if self.tasks.get(task_id) is None:
            raise ServiceError("task_not_found", "执行工具失败：任务不存在。", 404)
        if data.agent_run_id and self.agent_runs.get(data.agent_run_id) is None:
            raise ServiceError("agent_run_not_found", "执行工具失败：AgentRun 不存在。", 404)
        if self.tool_calls.get_by_task_idempotency_key(task_id, data.idempotency_key) is not None:
            raise ServiceError("duplicate_idempotency_key", "同一任务内 idempotency_key 已使用。", 409)

        gateway_result = self.gateway.execute(
            ToolCallRequest(
                task_id=task_id,
                agent_run_id=data.agent_run_id,
                tool_name=data.tool_name,
                risk_level=GatewayRiskLevel(data.risk_level.value),
                idempotency_key=data.idempotency_key,
                arguments=data.arguments,
                reason=data.reason,
            )
        )
        approval_id = None
        if gateway_result.status == "waiting_approval":
            approval = self.approvals.create(
                ApprovalRequest(
                    task_id=task_id,
                    action=data.tool_name,
                    risk_level=data.risk_level.value,
                    reason=gateway_result.approval_reason or data.reason,
                    status=ApprovalStatus.PENDING.value,
                    requested_by_agent_run_id=data.agent_run_id,
                )
            )
            approval_id = approval.id

        tool_call = self.tool_calls.create(
            ToolCall(
                task_id=task_id,
                agent_run_id=data.agent_run_id,
                tool_name=data.tool_name,
                risk_level=data.risk_level.value,
                arguments_json=data.arguments,
                result_json=gateway_result.result_json,
                status=self._status_from_gateway(gateway_result.status),
                approval_id=approval_id,
                idempotency_key=data.idempotency_key,
                arguments_summary=gateway_result.arguments_summary,
                result_summary=gateway_result.summary,
                stdout_summary=gateway_result.stdout_summary,
                stderr_summary=gateway_result.stderr_summary,
                duration_ms=gateway_result.duration_ms,
                error_code=gateway_result.error_code,
                started_at=gateway_result.started_at,
                finished_at=gateway_result.finished_at,
            )
        )
        self.events.record(
            "ToolCallStarted",
            "agent" if data.agent_run_id else "system",
            str(data.agent_run_id) if data.agent_run_id else "tool-gateway",
            {"tool_call_id": str(tool_call.id), "tool_name": data.tool_name, "risk_level": data.risk_level.value},
            task_id,
        )
        self._record_terminal_event(task_id, tool_call, gateway_result.status)
        self.commit()
        return tool_call_to_read(tool_call)

    def _record_terminal_event(self, task_id: UUID, tool_call: ToolCall, status: str) -> None:
        """写入工具调用终态事件。"""

        payload = {
            "tool_call_id": str(tool_call.id),
            "tool_name": tool_call.tool_name,
            "risk_level": tool_call.risk_level,
            "summary": tool_call.result_summary,
            "error_code": tool_call.error_code,
        }
        if status == "succeeded":
            event_type = "ToolCallSucceeded"
        elif status == "waiting_approval":
            event_type = "ApprovalRequested"
            payload["approval_id"] = str(tool_call.approval_id)
        else:
            event_type = "ToolCallFailed"
        self.events.record(event_type, "system", "tool-gateway", payload, task_id)

    def _status_from_gateway(self, status: str) -> str:
        """映射 Tool Gateway 状态到 Platform API ToolCall 状态。"""

        if status == "succeeded":
            return ToolCallStatus.SUCCEEDED.value
        if status == "waiting_approval":
            return ToolCallStatus.WAITING_APPROVAL.value
        return ToolCallStatus.FAILED.value
