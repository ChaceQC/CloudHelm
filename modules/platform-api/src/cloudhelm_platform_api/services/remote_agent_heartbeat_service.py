"""Remote Agent heartbeat 状态、事件和恢复服务。"""

from datetime import timedelta

from sqlalchemy.orm import Session

from cloudhelm_platform_api.core.config import Settings, get_settings
from cloudhelm_platform_api.db.base import utc_now
from cloudhelm_platform_api.models.remote_target import RemoteTarget
from cloudhelm_platform_api.repositories.remote_target_repository import (
    RemoteTargetRepository,
)
from cloudhelm_platform_api.schemas.remote_target import (
    RemoteAgentHeartbeat,
    RemoteAgentHeartbeatRead,
)
from cloudhelm_platform_api.services.base import BaseService
from cloudhelm_platform_api.services.event_service import EventService
from cloudhelm_platform_api.services.exceptions import ServiceError
from cloudhelm_platform_api.services.machine_auth_contract import MachineIdentity


class RemoteAgentHeartbeatService(BaseService):
    """在已认证身份下更新 RemoteTarget 心跳和状态事件。"""

    def __init__(
        self,
        session: Session,
        *,
        settings: Settings | None = None,
    ) -> None:
        super().__init__(session)
        self.settings = settings or get_settings()
        self.targets = RemoteTargetRepository(session)
        self.events = EventService(session)

    def record_heartbeat(
        self,
        identity: MachineIdentity,
        payload: RemoteAgentHeartbeat,
    ) -> RemoteAgentHeartbeatRead:
        """记录一次心跳，并生成 online/heartbeat/recovery 事件。"""

        if (
            payload.target_id != identity.target_id
            or payload.agent_id != identity.agent_id
        ):
            raise ServiceError(
                "machine_auth_target_mismatch",
                "Heartbeat 身份与 machine authentication 不一致。",
                401,
            )

        now = utc_now()
        if abs((now - payload.reported_at).total_seconds()) > (
            self.settings.remote_agent_timestamp_tolerance_seconds
        ):
            raise ServiceError(
                "heartbeat_reported_at_invalid",
                "Heartbeat 上报时间超出允许偏差。",
                422,
            )
        target = self.targets.get_for_update(identity.target_id)
        if target is None or target.agent_id != identity.agent_id:
            raise ServiceError(
                "machine_auth_target_mismatch",
                "Heartbeat 身份与 RemoteTarget 不一致。",
                401,
            )
        if target.status == "disabled":
            raise ServiceError(
                "remote_target_disabled",
                "RemoteTarget 已禁用。",
                403,
            )

        stale_cutoff = now - timedelta(
            seconds=self.settings.remote_agent_offline_timeout_seconds
        )
        if (
            target.status in {"online", "degraded"}
            and target.last_heartbeat_at is not None
            and target.last_heartbeat_at < stale_cutoff
        ):
            previous = target.status
            target.status = "offline"
            target.last_error_code = "heartbeat_timeout"
            target.last_status_changed_at = now
            target.last_event_at = now
            self._record_event(
                "RemoteAgentOffline",
                target,
                identity,
                {
                    "previous_status": previous,
                    "status": "offline",
                    "timeout_seconds": (
                        self.settings.remote_agent_offline_timeout_seconds
                    ),
                },
            )

        previous_status = target.status
        first_online = target.last_heartbeat_at is None
        capabilities = sorted(payload.capabilities)
        details_changed = (
            target.agent_version != payload.agent_version
            or list(target.capabilities_json) != capabilities
            or target.last_error_code is not None
        )
        status_changed = previous_status != "online"

        target.status = "online"
        target.agent_version = payload.agent_version
        target.capabilities_json = capabilities
        target.last_heartbeat_at = now
        target.last_error_code = None
        if status_changed:
            target.last_status_changed_at = now

        event_type: str | None = None
        transition: str | None = None
        if first_online:
            event_type = "RemoteAgentOnline"
            transition = "first_online"
        elif previous_status in {"offline", "degraded"}:
            event_type = "RemoteAgentRecovered"
            transition = "recovered"
        elif (
            details_changed
            or target.last_event_at is None
            or (
                now - target.last_event_at
            ).total_seconds()
            >= self.settings.remote_agent_heartbeat_event_interval_seconds
        ):
            event_type = "RemoteAgentHeartbeat"

        if event_type is not None:
            target.last_event_at = now
            extra = {"status": "online"}
            if transition is not None:
                extra["transition"] = transition
            self._record_event(
                event_type,
                target,
                identity,
                extra,
            )
        self.commit()
        return RemoteAgentHeartbeatRead(
            target_id=target.id,
            agent_id=target.agent_id,
            status="online",
            accepted_at=now,
            next_heartbeat_after_seconds=(
                self.settings.remote_agent_next_heartbeat_seconds
            ),
        )

    def _record_event(
        self,
        event_type: str,
        target: RemoteTarget,
        identity: MachineIdentity,
        extra: dict[str, object],
    ) -> None:
        """写入不含 endpoint、credential 和 secret 的 heartbeat 事件。"""

        payload = {
            "environment_id": str(target.environment_id),
            "remote_target_id": str(target.id),
            "agent_id": target.agent_id,
            "agent_version": target.agent_version,
            "capabilities": list(target.capabilities_json),
            "key_fingerprint": identity.key_fingerprint,
            **extra,
        }
        self.events.record(
            event_type=event_type,
            actor_type="remote_agent",
            actor_id=target.agent_id,
            payload=payload,
        )
