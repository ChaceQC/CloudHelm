"""Platform API Tool Gateway 集成服务。"""

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cloudhelm_tool_gateway import ToolCallRequest, ToolGateway, create_default_gateway
from cloudhelm_tool_gateway.schemas.tool_call import RiskLevel as GatewayRiskLevel

from cloudhelm_platform_api.core.config import get_settings
from cloudhelm_platform_api.db.base import utc_now
from cloudhelm_platform_api.models.approval import ApprovalRequest
from cloudhelm_platform_api.models.tool_call import ToolCall
from cloudhelm_platform_api.repositories.agent_run_repository import AgentRunRepository
from cloudhelm_platform_api.repositories.approval_repository import ApprovalRepository
from cloudhelm_platform_api.repositories.task_repository import TaskRepository
from cloudhelm_platform_api.repositories.tool_call_repository import ToolCallRepository
from cloudhelm_platform_api.schemas.common import AgentRunStatus, ApprovalStatus, PageInfo, PageResponse, ToolCallStatus
from cloudhelm_platform_api.schemas.tool_call import ToolCallRead, tool_call_to_read
from cloudhelm_platform_api.schemas.tool_gateway import ToolDeclarationRead, ToolGatewayCallCreate
from cloudhelm_platform_api.services.base import BaseService
from cloudhelm_platform_api.services.event_service import EventService
from cloudhelm_platform_api.services.exceptions import ServiceError


class ToolGatewayService(BaseService):
    """在数据库事务内执行 Tool Gateway 并记录 ToolCall、Approval 和 Event。"""

    def __init__(self, session: Session, gateway: ToolGateway | None = None) -> None:
        super().__init__(session)
        self.tasks = TaskRepository(session)
        self.agent_runs = AgentRunRepository(session)
        self.tool_calls = ToolCallRepository(session)
        self.approvals = ApprovalRepository(session)
        self.events = EventService(session)
        settings = get_settings()
        self.gateway = gateway or create_default_gateway(
            max_calls=settings.tool_rate_limit_calls,
            window_seconds=settings.tool_rate_limit_window_seconds,
        )

    def list_tools(self) -> PageResponse[ToolDeclarationRead]:
        """列出 Tool Gateway 当前注册工具。"""

        items = [ToolDeclarationRead.model_validate(item) for item in self.gateway.list_tools()]
        return PageResponse(items=items, page=PageInfo(limit=len(items), next_cursor=None))

    def call_tool(self, task_id: UUID, data: ToolGatewayCallCreate) -> ToolCallRead:
        """原子抢占幂等键后执行本地工具或创建审批请求。"""

        if self.tasks.get(task_id) is None:
            raise ServiceError("task_not_found", "执行工具失败：任务不存在。", 404)
        agent_run = self.agent_runs.get(data.agent_run_id) if data.agent_run_id else None
        if data.agent_run_id and agent_run is None:
            raise ServiceError("agent_run_not_found", "执行工具失败：AgentRun 不存在。", 404)
        if agent_run is not None and agent_run.task_id != task_id:
            raise ServiceError("agent_run_task_mismatch", "AgentRun 不属于当前任务。", 409)
        if agent_run is not None and agent_run.status != AgentRunStatus.RUNNING.value:
            raise ServiceError("agent_run_not_running", "只有 running AgentRun 可以调用 Tool Gateway。", 409)

        tool_call = self._claim_idempotency_key(task_id, data)
        gateway_result = self.gateway.execute(
            ToolCallRequest(
                task_id=task_id,
                agent_run_id=data.agent_run_id,
                agent_type=agent_run.agent_type if agent_run else None,
                tool_name=data.tool_name,
                risk_level=GatewayRiskLevel(data.risk_level.value),
                idempotency_key=data.idempotency_key,
                arguments=data.arguments,
                reason=data.reason,
            )
        )
        approval_id = self._create_approval_if_required(task_id, data, gateway_result)
        self._apply_gateway_result(tool_call, gateway_result, approval_id)
        self._record_terminal_event(task_id, tool_call, gateway_result.status)
        self.commit()
        return tool_call_to_read(tool_call)

    def _claim_idempotency_key(self, task_id: UUID, data: ToolGatewayCallCreate) -> ToolCall:
        """先持久化 pending 调用，数据库唯一索引负责并发幂等。"""

        tool_call = ToolCall(
            task_id=task_id,
            agent_run_id=data.agent_run_id,
            tool_name=data.tool_name,
            risk_level=data.risk_level.value,
            arguments_json=data.arguments,
            status=ToolCallStatus.PENDING.value,
            idempotency_key=data.idempotency_key,
            arguments_summary="pending validation",
            started_at=utc_now(),
        )
        try:
            self.tool_calls.create(tool_call)
            self.events.record(
                "ToolCallStarted",
                "agent" if data.agent_run_id else "system",
                str(data.agent_run_id) if data.agent_run_id else "tool-gateway",
                {"tool_call_id": str(tool_call.id), "tool_name": data.tool_name, "risk_level": data.risk_level.value},
                task_id,
            )
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ServiceError("duplicate_idempotency_key", "同一任务内 idempotency_key 已使用。", 409) from exc
        return tool_call

    def _create_approval_if_required(self, task_id, data, gateway_result) -> UUID | None:
        """为 waiting_approval 结果创建审批记录。"""

        if gateway_result.status != "waiting_approval":
            return None
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
        return approval.id

    def _apply_gateway_result(self, tool_call: ToolCall, gateway_result, approval_id: UUID | None) -> None:
        """把 Tool Gateway 稳定结果写回已抢占的 ToolCall。"""

        tool_call.result_json = gateway_result.result_json
        tool_call.status = self._status_from_gateway(gateway_result.status)
        tool_call.approval_id = approval_id
        tool_call.arguments_summary = gateway_result.arguments_summary
        tool_call.result_summary = gateway_result.summary
        tool_call.stdout_summary = gateway_result.stdout_summary
        tool_call.stderr_summary = gateway_result.stderr_summary
        tool_call.duration_ms = gateway_result.duration_ms
        tool_call.error_code = gateway_result.error_code
        tool_call.started_at = gateway_result.started_at
        tool_call.finished_at = gateway_result.finished_at

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
