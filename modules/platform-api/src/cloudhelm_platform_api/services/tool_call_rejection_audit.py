"""ToolCall 进入 claim 前或幂等重放时的拒绝审计。"""

from typing import Literal
from uuid import UUID

from sqlalchemy.orm import Session

from cloudhelm_tool_gateway.audit import stable_json_hash

from cloudhelm_platform_api.schemas.tool_gateway import ToolGatewayCallCreate
from cloudhelm_platform_api.services.event_service import EventService


def record_tool_call_rejected(
    session: Session,
    task_id: UUID,
    data: ToolGatewayCallCreate,
    *,
    agent_type: str | None,
    error_code: str,
    stage: Literal["context", "replay"],
    tool_call_id: UUID | None = None,
    stored_fingerprint: str | None = None,
    current_fingerprint: str | None = None,
) -> None:
    """只保存稳定哈希和身份，不记录原始参数或拒绝原因正文。"""

    EventService(session).record(
        "ToolCallRejected",
        "agent" if data.agent_run_id else "system",
        str(data.agent_run_id) if data.agent_run_id else "tool-gateway",
        {
            "tool_call_id": str(tool_call_id) if tool_call_id else None,
            "agent_run_id": (
                str(data.agent_run_id) if data.agent_run_id else None
            ),
            "agent_type": agent_type,
            "tool_name": data.tool_name,
            "error_code": error_code,
            "rejection_stage": stage,
            "arguments_hash": stable_json_hash(data.arguments),
            "idempotency_key_hash": stable_json_hash(
                {"idempotency_key": data.idempotency_key}
            ),
            "stored_policy_fingerprint": stored_fingerprint,
            "current_policy_fingerprint": current_fingerprint,
        },
        task_id,
    )
    session.commit()
