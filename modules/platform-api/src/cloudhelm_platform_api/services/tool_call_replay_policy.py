"""ToolCall 幂等重放时的执行策略一致性校验。"""

from uuid import UUID

from sqlalchemy.orm import Session

from cloudhelm_platform_api.models.tool_call import ToolCall
from cloudhelm_platform_api.schemas.common import ToolCallStatus
from cloudhelm_platform_api.schemas.tool_gateway import ToolGatewayCallCreate
from cloudhelm_platform_api.services.exceptions import ServiceError
from cloudhelm_platform_api.services.tool_call_rejection_audit import (
    record_tool_call_rejected,
)


def ensure_replay_policy_matches(
    tool_call: ToolCall,
    *,
    current_fingerprint: str | None,
    current_error: tuple[str, str] | None,
) -> None:
    """拒绝在权限或 execution recipe 已变化时复用旧终态。"""

    stored_fingerprint = (tool_call.audit_json or {}).get(
        "execution_policy_fingerprint"
    )
    if current_error is not None:
        current_code, _ = current_error
        same_denial = (
            tool_call.status == ToolCallStatus.FAILED.value
            and tool_call.error_code == current_code
            and stored_fingerprint == current_fingerprint
        )
        if same_denial:
            return
        raise ServiceError(
            "idempotency_policy_conflict",
            "幂等 ToolCall 的当前执行策略与已保存终态不一致。",
            409,
            {"tool_call_id": str(tool_call.id)},
        )
    if stored_fingerprint != current_fingerprint:
        raise ServiceError(
            "idempotency_policy_conflict",
            "幂等 ToolCall 的执行策略指纹已变化。",
            409,
            {"tool_call_id": str(tool_call.id)},
        )


def validate_and_audit_replay(
    session: Session,
    task_id: UUID,
    data: ToolGatewayCallCreate,
    tool_call: ToolCall,
    *,
    agent_type: str | None,
    current_fingerprint: str | None,
    current_error: tuple[str, str] | None,
) -> None:
    """校验重放策略；冲突时保留原 ToolCall 并追加拒绝事件。"""

    try:
        ensure_replay_policy_matches(
            tool_call,
            current_fingerprint=current_fingerprint,
            current_error=current_error,
        )
    except ServiceError as exc:
        record_tool_call_rejected(
            session,
            task_id,
            data,
            agent_type=agent_type,
            error_code=exc.code,
            stage="replay",
            tool_call_id=tool_call.id,
            stored_fingerprint=(tool_call.audit_json or {}).get(
                "execution_policy_fingerprint"
            ),
            current_fingerprint=current_fingerprint,
        )
        raise
