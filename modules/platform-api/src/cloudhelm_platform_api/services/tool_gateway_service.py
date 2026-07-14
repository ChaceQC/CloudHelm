"""Platform API Tool Gateway 集成服务。"""

from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from sqlalchemy.orm import Session

from cloudhelm_tool_gateway import ToolCallRequest, ToolGateway, create_default_gateway
from cloudhelm_tool_gateway.audit import utf8_sha256
from cloudhelm_tool_gateway.schemas.tool_call import RiskLevel as GatewayRiskLevel

from cloudhelm_platform_api.core.config import get_settings
from cloudhelm_platform_api.repositories.agent_run_repository import AgentRunRepository
from cloudhelm_platform_api.repositories.task_repository import TaskRepository
from cloudhelm_platform_api.schemas.common import (
    AgentRunStatus,
    PageInfo,
    PageResponse,
    TaskStatus,
    ToolCallStatus,
)
from cloudhelm_platform_api.schemas.tool_call import ToolCallRead, tool_call_to_read
from cloudhelm_platform_api.schemas.tool_gateway import ToolDeclarationRead, ToolGatewayCallCreate
from cloudhelm_platform_api.services.base import BaseService
from cloudhelm_platform_api.services.exceptions import ServiceError
from cloudhelm_platform_api.services.subagent_conversation_policy import SubagentConversationPolicy
from cloudhelm_platform_api.services.subagent_tool_call_policy import evaluate_subagent_tool_call_policy
from cloudhelm_platform_api.services.tool_call_execution import ToolCallExecution
from cloudhelm_platform_api.services.tool_call_replay_policy import validate_and_audit_replay

_LOSSLESS_RESULT_TOOLS = frozenset({"git.diff", "git.format_patch"})


@dataclass(frozen=True, slots=True)
class AgentToolCallResult:
    """Agent 工具调用的持久化记录与仅限进程内使用的原始结果。"""

    record: ToolCallRead
    raw_result_json: dict[str, Any] | None


class ToolGatewayService(BaseService):
    """以短事务抢占幂等键，执行 Gateway 后再写终态审计与事件。"""

    def __init__(self, session: Session, gateway: ToolGateway | None = None) -> None:
        super().__init__(session)
        self.tasks = TaskRepository(session)
        self.agent_runs = AgentRunRepository(session)
        self.execution = ToolCallExecution(session)
        settings = get_settings()
        self.subagent_policy = SubagentConversationPolicy(session, settings)
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

        return self._call_tool(
            task_id,
            data,
            execution_source=execution_source,
            execution_policy_fingerprint=execution_policy_fingerprint,
            execution_policy_error=execution_policy_error,
        ).record

    def call_tool_for_agent(
        self,
        task_id: UUID,
        data: ToolGatewayCallCreate,
        *,
        execution_policy_fingerprint: str,
        execution_policy_error: tuple[str, str] | None = None,
    ) -> AgentToolCallResult:
        """执行 M6 Agent 工具，并返回可用于 Artifact 的瞬时原始结果。"""

        return self._call_tool(
            task_id,
            data,
            execution_source="agent_executor",
            execution_policy_fingerprint=execution_policy_fingerprint,
            execution_policy_error=execution_policy_error,
        )

    def _call_tool(
        self,
        task_id: UUID,
        data: ToolGatewayCallCreate,
        *,
        execution_source: Literal["public_api", "agent_executor"],
        execution_policy_fingerprint: str | None,
        execution_policy_error: tuple[str, str] | None,
    ) -> AgentToolCallResult:
        """执行共享主流程；原始结果始终与数据库/API 投影分离。"""

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
        subagent_policy = evaluate_subagent_tool_call_policy(
            self.session,
            self.subagent_policy,
            task_id,
            data,
            agent_run,
            agent_type,
            current_fingerprint=execution_policy_fingerprint,
            current_error=execution_policy_error,
        )
        subagent_scope = subagent_policy.scope
        execution_policy_fingerprint = subagent_policy.fingerprint
        execution_policy_error = subagent_policy.error
        gateway_request = ToolCallRequest(
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
        tool_call, claimed = self.execution.claim(
            task_id,
            data,
            agent_type,
            execution_policy_fingerprint=execution_policy_fingerprint,
            execution_policy_context=(
                {
                    "subagent_permission_scope": subagent_scope.audit_payload(),
                }
                if subagent_scope is not None
                else None
            ),
        )
        if not claimed:
            validate_and_audit_replay(
                self.session,
                task_id,
                data,
                tool_call,
                agent_type=agent_type,
                current_fingerprint=execution_policy_fingerprint,
                current_error=execution_policy_error,
            )
            raw_result = None
            if execution_source == "agent_executor":
                raw_result = self._recover_lossless_result(
                    gateway_request,
                    tool_call,
                )
            return AgentToolCallResult(
                record=tool_call_to_read(tool_call),
                raw_result_json=raw_result,
            )
        if execution_policy_error is not None:
            code, message = execution_policy_error
            self.execution.reject_execution_policy(
                tool_call,
                code,
                message,
                execution_policy_fingerprint,
                execution_source,
            )
            self.execution.record_terminal_event(
                task_id,
                tool_call,
                "failed",
            )
            self.commit()
            return AgentToolCallResult(
                record=tool_call_to_read(tool_call),
                raw_result_json=None,
            )
        gateway_result = self.gateway.execute(gateway_request)
        guarded = self.execution.guard_late_result(
            task_id,
            data.agent_run_id,
            tool_call.id,
            execution_policy_fingerprint,
        )
        if guarded is not None:
            return AgentToolCallResult(
                record=guarded,
                raw_result_json=None,
            )
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
        if subagent_scope is not None:
            tool_call.audit_json = {
                **(tool_call.audit_json or {}),
                "subagent_permission_scope": subagent_scope.audit_payload(),
            }
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
        return AgentToolCallResult(
            record=tool_call_to_read(tool_call),
            raw_result_json=gateway_result.raw_result_json,
        )

    def _recover_lossless_result(
        self,
        request: ToolCallRequest,
        tool_call,
    ) -> dict[str, Any] | None:
        """幂等复用只读 Git ToolCall 时重算原始 patch 并校验既有 SHA。"""

        if (
            request.tool_name not in _LOSSLESS_RESULT_TOOLS
            or tool_call.status != ToolCallStatus.SUCCEEDED.value
        ):
            return None
        replay = self.gateway.execute(request)
        raw_result = replay.raw_result_json
        patch = raw_result.get("patch") if raw_result is not None else None
        expected_sha = (tool_call.audit_json or {}).get("patch_sha256")
        if (
            replay.status != "succeeded"
            or not isinstance(patch, str)
            or not isinstance(expected_sha, str)
            or utf8_sha256(patch) != expected_sha
        ):
            raise ServiceError(
                "tool_call_raw_result_mismatch",
                "幂等 ToolCall 的原始 patch 与已记录 SHA 不一致。",
                409,
            )
        return raw_result
