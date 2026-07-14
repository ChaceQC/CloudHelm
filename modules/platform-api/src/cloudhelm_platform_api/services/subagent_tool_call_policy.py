"""将 subagent lineage 权限映射为单次 ToolCall 执行策略。"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from cloudhelm_tool_gateway.audit import stable_json_hash

from cloudhelm_platform_api.models.agent_run import AgentRun
from cloudhelm_platform_api.schemas.tool_gateway import ToolGatewayCallCreate
from cloudhelm_platform_api.services.exceptions import ServiceError
from cloudhelm_platform_api.services.subagent_conversation_policy import (
    SubagentConversationPolicy,
)
from cloudhelm_platform_api.services.subagent_tool_scope import SubagentToolScope
from cloudhelm_platform_api.services.tool_call_rejection_audit import (
    record_tool_call_rejected,
)


@dataclass(frozen=True, slots=True)
class SubagentToolCallPolicyResult:
    """一次工具调用解析后的 scope、指纹和可选拒绝。"""

    scope: SubagentToolScope | None
    fingerprint: str | None
    error: tuple[str, str] | None


def evaluate_subagent_tool_call_policy(
    session: Session,
    policy: SubagentConversationPolicy,
    task_id: UUID,
    data: ToolGatewayCallCreate,
    agent_run: AgentRun | None,
    agent_type: str | None,
    *,
    current_fingerprint: str | None,
    current_error: tuple[str, str] | None,
) -> SubagentToolCallPolicyResult:
    """解析父子权限交集，并为 claim 前的上下文拒绝写入事件。"""

    try:
        scope = (
            policy.resolve_tool_scope(agent_run)
            if agent_run is not None
            else None
        )
    except ServiceError as exc:
        record_tool_call_rejected(
            session,
            task_id,
            data,
            agent_type=agent_type,
            error_code=exc.code,
            stage="context",
            current_fingerprint=current_fingerprint,
        )
        raise
    if scope is None:
        return SubagentToolCallPolicyResult(
            scope=None,
            fingerprint=current_fingerprint,
            error=current_error,
        )

    inherited_fingerprint = scope.fingerprint()
    fingerprint = (
        stable_json_hash(
            {
                "existing": current_fingerprint,
                "subagent": scope.audit_payload(),
            }
        )
        if current_fingerprint is not None
        else inherited_fingerprint
    )
    error = current_error
    if data.tool_name not in scope.effective_allowed_tools:
        error = (
            "subagent_tool_not_allowed",
            "子 Agent 工具不在父级与 child 角色权限交集中。",
        )
    return SubagentToolCallPolicyResult(
        scope=scope,
        fingerprint=fingerprint,
        error=error,
    )
