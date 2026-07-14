"""ToolCall 幂等抢占与严格重放校验。"""

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cloudhelm_tool_gateway.audit import (
    sanitize_arguments_for_storage,
    stable_json_hash,
    summarize_mapping,
)

from cloudhelm_platform_api.db.base import utc_now
from cloudhelm_platform_api.models.tool_call import ToolCall
from cloudhelm_platform_api.repositories.tool_call_repository import (
    ToolCallRepository,
)
from cloudhelm_platform_api.schemas.common import ToolCallStatus
from cloudhelm_platform_api.schemas.tool_gateway import ToolGatewayCallCreate
from cloudhelm_platform_api.services.event_service import EventService
from cloudhelm_platform_api.services.exceptions import ServiceError


class ToolCallClaim:
    """在短事务中抢占工具调用身份并处理并发重放。"""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.tool_calls = ToolCallRepository(session)
        self.events = EventService(session)

    def claim(
        self,
        task_id: UUID,
        data: ToolGatewayCallCreate,
        agent_type: str | None,
        execution_policy_fingerprint: str | None = None,
        execution_policy_context: dict[str, object] | None = None,
    ) -> tuple[ToolCall, bool]:
        """抢占幂等键；相同终态调用直接返回已有记录。"""

        existing = self.tool_calls.get_by_task_idempotency_key(
            task_id,
            data.idempotency_key,
        )
        if existing is not None:
            return (
                self._validate_replay(
                    existing,
                    data,
                    agent_type,
                    execution_policy_fingerprint,
                ),
                False,
            )
        tool_call = ToolCall(
            task_id=task_id,
            agent_run_id=data.agent_run_id,
            tool_name=data.tool_name,
            provider_call_id=data.provider_call_id,
            provider_item_type=data.provider_item_type,
            risk_level=data.risk_level.value,
            arguments_json=sanitize_arguments_for_storage(data.arguments),
            audit_json=self._initial_audit(
                task_id,
                data,
                agent_type,
                execution_policy_fingerprint,
                execution_policy_context,
            ),
            status=ToolCallStatus.PENDING.value,
            idempotency_key=data.idempotency_key,
            arguments_summary=summarize_mapping(data.arguments),
            started_at=utc_now(),
        )
        try:
            self.tool_calls.create(tool_call)
            self.events.record(
                "ToolCallStarted",
                "agent" if data.agent_run_id else "system",
                (
                    str(data.agent_run_id)
                    if data.agent_run_id
                    else "tool-gateway"
                ),
                {
                    "tool_call_id": str(tool_call.id),
                    "tool_name": data.tool_name,
                    "risk_level": data.risk_level.value,
                },
                task_id,
            )
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            existing = self.tool_calls.get_by_task_idempotency_key(
                task_id,
                data.idempotency_key,
            )
            if existing is None and data.agent_run_id and data.provider_call_id:
                existing = self.tool_calls.get_by_agent_provider_call(
                    data.agent_run_id,
                    data.provider_call_id,
                )
            if existing is None:
                raise ServiceError(
                    "tool_call_claim_conflict",
                    "工具调用幂等键或 provider call_id 已被并发占用。",
                    409,
                ) from exc
            return (
                self._validate_replay(
                    existing,
                    data,
                    agent_type,
                    execution_policy_fingerprint,
                ),
                False,
            )
        return tool_call, True

    @staticmethod
    def _initial_audit(
        task_id: UUID,
        data: ToolGatewayCallCreate,
        agent_type: str | None,
        execution_policy_fingerprint: str | None,
        execution_policy_context: dict[str, object] | None,
    ) -> dict:
        """生成调用方不能覆盖的初始审计主体。"""

        return {
            "tool": data.tool_name,
            "task_id": str(task_id),
            "agent_run_id": (
                str(data.agent_run_id) if data.agent_run_id else None
            ),
            "agent_type": agent_type,
            "provider_call_id": data.provider_call_id,
            "provider_item_type": data.provider_item_type,
            "risk_level": data.risk_level.value,
            "idempotency_key": data.idempotency_key,
            "arguments_hash": stable_json_hash(data.arguments),
            "reason_hash": stable_json_hash({"reason": data.reason}),
            "status": ToolCallStatus.PENDING.value,
            "execution_policy_fingerprint": execution_policy_fingerprint,
            **(execution_policy_context or {}),
        }

    @staticmethod
    def _validate_replay(
        existing: ToolCall,
        data: ToolGatewayCallCreate,
        agent_type: str | None,
        execution_policy_fingerprint: str | None,
    ) -> ToolCall:
        """只允许完全相同的终态工具调用按幂等语义重放。"""

        audit = existing.audit_json or {}
        matches = (
            existing.tool_name == data.tool_name
            and existing.agent_run_id == data.agent_run_id
            and existing.risk_level == data.risk_level.value
            and audit.get("arguments_hash")
            == stable_json_hash(data.arguments)
            and audit.get("agent_type") == agent_type
            and existing.provider_call_id == data.provider_call_id
            and existing.provider_item_type == data.provider_item_type
        )
        if not matches:
            raise ServiceError(
                "idempotency_conflict",
                "相同 idempotency_key 或 provider call_id 对应不同工具参数。",
                409,
            )
        if existing.status in {
            ToolCallStatus.PENDING.value,
            ToolCallStatus.RUNNING.value,
        }:
            raise ServiceError(
                "tool_call_in_progress",
                "相同工具调用仍在执行中。",
                409,
            )
        return existing
