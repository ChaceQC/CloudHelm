"""Platform API Tool Gateway 集成服务。"""

from typing import Literal
from uuid import UUID

from sqlalchemy.orm import Session

from cloudhelm_tool_gateway import ToolCallRequest, ToolGateway, create_default_gateway
from cloudhelm_tool_gateway.schemas.tool_call import RiskLevel as GatewayRiskLevel

from cloudhelm_platform_api.core.config import get_settings
from cloudhelm_platform_api.repositories.agent_run_repository import AgentRunRepository
from cloudhelm_platform_api.repositories.task_repository import TaskRepository
from cloudhelm_platform_api.schemas.common import (
    AgentRunStatus,
    PageInfo,
    PageResponse,
    TaskStatus,
)
from cloudhelm_platform_api.schemas.tool_call import ToolCallRead, tool_call_to_read
from cloudhelm_platform_api.schemas.tool_gateway import ToolDeclarationRead, ToolGatewayCallCreate
from cloudhelm_platform_api.services.base import BaseService
from cloudhelm_platform_api.services.exceptions import ServiceError
from cloudhelm_platform_api.services.tool_call_execution import (
    ToolCallExecution,
)


class ToolGatewayService(BaseService):
    """以短事务抢占幂等键，执行 Gateway 后再写终态审计与事件。"""

    def __init__(self, session: Session, gateway: ToolGateway | None = None) -> None:
        super().__init__(session)
        self.tasks = TaskRepository(session)
        self.agent_runs = AgentRunRepository(session)
        self.execution = ToolCallExecution(session)
        settings = get_settings()
        self.gateway = gateway or create_default_gateway(
            max_calls=settings.tool_rate_limit_calls,
            window_seconds=settings.tool_rate_limit_window_seconds,
            allowed_workspace_roots=settings.tool_workspace_roots,
        )

    def list_tools(self) -> PageResponse[ToolDeclarationRead]:
        """列出 Tool Gateway 当前注册工具。"""

        items = [ToolDeclarationRead.model_validate(item) for item in self.gateway.list_tools()]
        return PageResponse(items=items, page=PageInfo(limit=len(items), next_cursor=None))

    def call_tool(
        self,
        task_id: UUID,
        data: ToolGatewayCallCreate,
        *,
        execution_source: Literal["public_api", "agent_executor"] = "public_api",
        execution_policy_fingerprint: str | None = None,
        execution_policy_error: tuple[str, str] | None = None,
    ) -> ToolCallRead:
        """原子抢占幂等键后执行本地工具或创建审批请求。"""

        task = self.tasks.get(task_id)
        if task is None:
            raise ServiceError("task_not_found", "执行工具失败：任务不存在。", 404)
        agent_run = self.agent_runs.get(data.agent_run_id) if data.agent_run_id else None
        if data.agent_run_id and agent_run is None:
            raise ServiceError("agent_run_not_found", "执行工具失败：AgentRun 不存在。", 404)
        if agent_run is not None and agent_run.task_id != task_id:
            raise ServiceError("agent_run_task_mismatch", "AgentRun 不属于当前任务。", 409)
        if agent_run is not None and agent_run.status != AgentRunStatus.RUNNING.value:
            raise ServiceError("agent_run_not_running", "只有 running AgentRun 可以调用 Tool Gateway。", 409)
        if agent_run is not None and task.status != TaskStatus.RUNNING.value:
            raise ServiceError("task_not_running", "只有 running 任务中的 AgentRun 可以调用 Tool Gateway。", 409)
        if agent_run is not None and agent_run.workflow_step is not None:
            if execution_source != "agent_executor":
                raise ServiceError(
                    "m6_agent_tool_executor_required",
                    "M6 AgentRun 的工具调用只能由本地开发执行器提交。",
                    403,
                )
            if execution_policy_fingerprint is None:
                raise ServiceError(
                    "m6_execution_policy_missing",
                    "M6 AgentRun 缺少 execution recipe 调用指纹。",
                    409,
                )
        if agent_run is None and task.status in {
            TaskStatus.DONE.value,
            TaskStatus.FAILED.value,
            TaskStatus.CANCELLED.value,
        }:
            raise ServiceError("task_terminal", "终态任务不能创建新的 ToolCall。", 409)

        agent_type = agent_run.agent_type if agent_run else None
        tool_call, claimed = self.execution.claim(
            task_id,
            data,
            agent_type,
        )
        if not claimed:
            return tool_call_to_read(tool_call)
        if execution_policy_error is not None:
            code, message = execution_policy_error
            self.execution.reject_execution_policy(
                tool_call,
                code,
                message,
                execution_policy_fingerprint,
            )
            self.execution.record_terminal_event(
                task_id,
                tool_call,
                "failed",
            )
            self.commit()
            return tool_call_to_read(tool_call)
        gateway_result = self.gateway.execute(
            ToolCallRequest(
                task_id=task_id,
                agent_run_id=data.agent_run_id,
                agent_type=agent_type,
                provider_call_id=data.provider_call_id,
                provider_item_type=data.provider_item_type,
                tool_name=data.tool_name,
                risk_level=GatewayRiskLevel(data.risk_level.value),
                idempotency_key=data.idempotency_key,
                arguments=data.arguments,
                reason=data.reason,
            )
        )
        guarded = self.execution.guard_late_result(
            task_id,
            data.agent_run_id,
            tool_call.id,
            execution_policy_fingerprint,
        )
        if guarded is not None:
            return guarded
        approval_id = self.execution.create_approval_if_required(
            task_id,
            data,
            gateway_result,
        )
        self.execution.apply_gateway_result(
            tool_call,
            gateway_result,
            approval_id,
        )
        if execution_policy_fingerprint is not None:
            tool_call.audit_json = {
                **(tool_call.audit_json or {}),
                "execution_source": execution_source,
                "execution_policy_fingerprint": execution_policy_fingerprint,
            }
        self.execution.record_terminal_event(
            task_id,
            tool_call,
            gateway_result.status,
        )
        self.commit()
        return tool_call_to_read(tool_call)
