"""Tool Gateway 的 ToolCall 抢占、重放、审批与终态持久化。"""

from uuid import UUID

from sqlalchemy.orm import Session

from cloudhelm_platform_api.db.base import utc_now
from cloudhelm_platform_api.models.agent_run import AgentRun
from cloudhelm_platform_api.models.approval import ApprovalRequest
from cloudhelm_platform_api.models.tool_call import ToolCall
from cloudhelm_platform_api.repositories.approval_repository import (
    ApprovalRepository,
)
from cloudhelm_platform_api.repositories.task_repository import TaskRepository
from cloudhelm_platform_api.schemas.common import (
    AgentRunStatus,
    ApprovalStatus,
    TaskStatus,
    ToolCallStatus,
)
from cloudhelm_platform_api.schemas.tool_call import (
    ToolCallRead,
    tool_call_to_read,
)
from cloudhelm_platform_api.schemas.tool_gateway import ToolGatewayCallCreate
from cloudhelm_platform_api.services.event_service import EventService
from cloudhelm_platform_api.services.exceptions import ServiceError
from cloudhelm_platform_api.services.tool_call_claim import ToolCallClaim


class ToolCallExecution:
    """把外部工具副作用前后的数据库短事务集中在单一组件。"""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.tasks = TaskRepository(session)
        self.claims = ToolCallClaim(session)
        self.approvals = ApprovalRepository(session)
        self.events = EventService(session)

    def claim(
        self,
        task_id: UUID,
        data: ToolGatewayCallCreate,
        agent_type: str | None,
    ) -> tuple[ToolCall, bool]:
        """抢占幂等键；相同终态调用直接返回已有记录。"""

        return self.claims.claim(task_id, data, agent_type)

    def guard_late_result(
        self,
        task_id: UUID,
        agent_run_id: UUID | None,
        tool_call_id: UUID,
        fingerprint: str | None,
    ) -> ToolCallRead | None:
        """长工具返回后拒绝覆盖已暂停或取消的 Task/AgentRun。"""

        self.session.expire_all()
        task = self.tasks.get(task_id, for_update=True)
        run = (
            self.session.get(
                AgentRun,
                agent_run_id,
                populate_existing=True,
                with_for_update=True,
            )
            if agent_run_id is not None
            else None
        )
        tool_call = self.session.get(
            ToolCall,
            tool_call_id,
            populate_existing=True,
            with_for_update=True,
        )
        if task is None or tool_call is None:
            raise ServiceError(
                "tool_call_finalize_context_missing",
                "工具执行返回后缺少任务或 ToolCall 上下文。",
                409,
            )
        task_running = task.status == TaskStatus.RUNNING.value
        run_running = (
            run is None or run.status == AgentRunStatus.RUNNING.value
        )
        if task_running and run_running:
            return None
        if tool_call.status in {
            ToolCallStatus.PENDING.value,
            ToolCallStatus.RUNNING.value,
        }:
            tool_call.status = ToolCallStatus.FAILED.value
            tool_call.error_code = (
                "task_state_changed_during_tool_execution"
            )
            tool_call.result_summary = (
                "工具执行返回前 Task 或 AgentRun 状态已变化，结果未写入业务终态。"
            )
            tool_call.result_json = {
                "task_status": task.status,
                "agent_run_status": run.status if run is not None else None,
            }
            tool_call.finished_at = utc_now()
            tool_call.audit_json = {
                **(tool_call.audit_json or {}),
                "status": ToolCallStatus.FAILED.value,
                "error_code": tool_call.error_code,
                "late_result_discarded": True,
                "execution_policy_fingerprint": fingerprint,
            }
            self.record_terminal_event(task_id, tool_call, "failed")
            self.session.commit()
        return tool_call_to_read(tool_call)

    @staticmethod
    def reject_execution_policy(
        tool_call: ToolCall,
        code: str,
        message: str,
        fingerprint: str | None,
    ) -> None:
        """持久化未匹配 execution recipe 的拒绝，不执行工具。"""

        tool_call.status = ToolCallStatus.FAILED.value
        tool_call.result_json = {"message": message}
        tool_call.result_summary = message
        tool_call.error_code = code
        tool_call.finished_at = utc_now()
        tool_call.audit_json = {
            **(tool_call.audit_json or {}),
            "status": ToolCallStatus.FAILED.value,
            "error_code": code,
            "execution_source": "agent_executor",
            "execution_policy_fingerprint": fingerprint,
        }

    def create_approval_if_required(
        self,
        task_id: UUID,
        data: ToolGatewayCallCreate,
        gateway_result,
    ) -> UUID | None:
        """为 waiting_approval 工具结果创建审批记录。"""

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

    @staticmethod
    def apply_gateway_result(
        tool_call: ToolCall,
        gateway_result,
        approval_id: UUID | None,
    ) -> None:
        """把 Tool Gateway 稳定结果写回已抢占的 ToolCall。"""

        tool_call.result_json = gateway_result.result_json
        tool_call.status = ToolCallExecution._status_from_gateway(
            gateway_result.status
        )
        tool_call.approval_id = approval_id
        tool_call.arguments_summary = gateway_result.arguments_summary
        tool_call.result_summary = gateway_result.summary
        tool_call.stdout_summary = gateway_result.stdout_summary
        tool_call.stderr_summary = gateway_result.stderr_summary
        tool_call.duration_ms = gateway_result.duration_ms
        tool_call.error_code = gateway_result.error_code
        tool_call.audit_json = gateway_result.audit_json
        tool_call.started_at = gateway_result.started_at
        tool_call.finished_at = gateway_result.finished_at

    def record_terminal_event(
        self,
        task_id: UUID,
        tool_call: ToolCall,
        status: str,
    ) -> None:
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
        self.events.record(
            event_type,
            "system",
            "tool-gateway",
            payload,
            task_id,
        )

    @staticmethod
    def _status_from_gateway(status: str) -> str:
        """映射 Tool Gateway 状态到 Platform ToolCall 状态。"""

        if status == "succeeded":
            return ToolCallStatus.SUCCEEDED.value
        if status == "waiting_approval":
            return ToolCallStatus.WAITING_APPROVAL.value
        return ToolCallStatus.FAILED.value
