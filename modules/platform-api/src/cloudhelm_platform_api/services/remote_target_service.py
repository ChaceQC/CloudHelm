"""M7 RemoteTarget 注册、脱敏读取和离线收敛服务。"""

import hashlib
from datetime import timedelta
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cloudhelm_platform_api.core.config import Settings, get_settings
from cloudhelm_platform_api.core.remote_target_config import (
    RemoteAgentCredentialConfig,
)
from cloudhelm_platform_api.db.base import utc_now
from cloudhelm_platform_api.models.remote_target import (
    RemoteAgentCredential,
    RemoteTarget,
)
from cloudhelm_platform_api.providers.remote_target_profile_provider import (
    RemoteTargetProfileProvider,
)
from cloudhelm_platform_api.repositories.environment_repository import (
    EnvironmentRepository,
)
from cloudhelm_platform_api.repositories.remote_target_repository import (
    RemoteTargetRepository,
)
from cloudhelm_platform_api.schemas.common import PageInfo, PageResponse
from cloudhelm_platform_api.schemas.remote_target import (
    RemoteTargetCreate,
    RemoteTargetRead,
)
from cloudhelm_platform_api.services.base import BaseService
from cloudhelm_platform_api.services.database_errors import (
    database_write_error,
    integrity_constraint_name,
)
from cloudhelm_platform_api.services.event_service import EventService
from cloudhelm_platform_api.services.exceptions import ServiceError


class RemoteTargetService(BaseService):
    """管理服务端 profile 派生的 RemoteTarget。

    endpoint、TLS 和 credential 均来自服务端配置。普通调用方只能选择
    profile_key 和展示名称。
    """

    def __init__(
        self,
        session: Session,
        *,
        settings: Settings | None = None,
        profiles: RemoteTargetProfileProvider | None = None,
    ) -> None:
        super().__init__(session)
        self.settings = settings or get_settings()
        self.profiles = profiles or RemoteTargetProfileProvider(self.settings)
        self.environments = EnvironmentRepository(session)
        self.targets = RemoteTargetRepository(session)
        self.events = EventService(session)

    def create_target(
        self,
        environment_id: UUID,
        data: RemoteTargetCreate,
    ) -> RemoteTargetRead:
        """注册 RemoteTarget、credential 元数据和审计事件。"""

        environment = self.environments.get(environment_id)
        if environment is None:
            raise ServiceError(
                "environment_not_found",
                "Environment 不存在。",
                404,
            )
        if environment.status != "active":
            raise ServiceError(
                "environment_not_active",
                "Environment 当前不可注册 RemoteTarget。",
                409,
            )

        profile = self.profiles.get_profile(data.profile_key)
        if self.targets.get_by_environment_agent(
            environment_id,
            profile.agent_id,
        ):
            raise ServiceError(
                "remote_target_conflict",
                "Environment 已注册该 Remote Agent。",
                409,
            )

        now = utc_now()
        prepared_credentials: list[
            tuple[RemoteAgentCredentialConfig, str]
        ] = []
        has_active_heartbeat_key = False
        for credential_config in profile.credentials:
            secret = self.profiles.get_secret(
                credential_config.credential_ref
            ).get_secret_value()
            fingerprint = "sha256:" + hashlib.sha256(
                secret.encode("utf-8")
            ).hexdigest()
            prepared_credentials.append((credential_config, fingerprint))
            if (
                "heartbeat" in credential_config.scopes
                and credential_config.active_from <= now
                and (
                    credential_config.expires_at is None
                    or credential_config.expires_at > now
                )
                and credential_config.revoked_at is None
            ):
                has_active_heartbeat_key = True
        if not has_active_heartbeat_key:
            raise ServiceError(
                "remote_target_profile_unusable",
                "RemoteTarget profile 没有可用 heartbeat credential。",
                503,
            )

        try:
            target = self.targets.create_target(
                RemoteTarget(
                    environment_id=environment_id,
                    display_name=data.display_name,
                    target_type=profile.target_type,
                    agent_id=profile.agent_id,
                    agent_endpoint=str(profile.agent_endpoint).rstrip("/"),
                    credential_ref=f"profile:{data.profile_key}",
                    tls_fingerprint=profile.tls_fingerprint,
                    status="offline",
                    capabilities_json=[],
                    last_status_changed_at=now,
                )
            )
        except IntegrityError as exc:
            self.session.rollback()
            if integrity_constraint_name(exc) == (
                "uq_remote_targets_environment_agent"
            ):
                raise ServiceError(
                    "remote_target_conflict",
                    "Environment 已注册该 Remote Agent。",
                    409,
                ) from None
            raise database_write_error(exc) from exc
        try:
            for credential_config, fingerprint in prepared_credentials:
                self.targets.create_credential(
                    RemoteAgentCredential(
                        target_id=target.id,
                        agent_id=target.agent_id,
                        key_id=credential_config.key_id,
                        credential_ref=credential_config.credential_ref,
                        scopes_json=list(credential_config.scopes),
                        secret_fingerprint=fingerprint,
                        active_from=credential_config.active_from,
                        expires_at=credential_config.expires_at,
                        revoked_at=credential_config.revoked_at,
                    )
                )
        except IntegrityError as exc:
            self.session.rollback()
            raise database_write_error(exc) from exc
        self.events.record(
            event_type="RemoteTargetRegistered",
            actor_type="user",
            actor_id="user",
            payload={
                "project_id": str(environment.project_id),
                "environment_id": str(environment_id),
                "remote_target_id": str(target.id),
                "agent_id": target.agent_id,
                "status": target.status,
                "target_type": target.target_type,
            },
        )
        self.commit()
        return self._to_read(target)

    def list_targets(
        self,
        environment_id: UUID,
        limit: int,
        cursor: str | None,
    ) -> PageResponse[RemoteTargetRead]:
        """分页读取目标，并在访问时收敛已超时的在线状态。

        M7-1 尚未接入 Celery 周期调度，因此离线事件由 target 列表访问或后续
        heartbeat 恢复路径触发；该边界必须保留在进度记录中。
        """

        if self.environments.get(environment_id) is None:
            raise ServiceError(
                "environment_not_found",
                "Environment 不存在。",
                404,
            )
        changed = self._reconcile_offline(environment_id)
        if changed:
            self.commit()
        items, next_cursor = self.targets.list_by_environment(
            environment_id,
            limit,
            cursor,
        )
        return PageResponse(
            items=[self._to_read(item) for item in items],
            page=PageInfo(limit=limit, next_cursor=next_cursor),
        )

    def _reconcile_offline(self, environment_id: UUID) -> int:
        """把超过心跳阈值的 online/degraded targets 收敛为 offline。"""

        now = utc_now()
        cutoff = now - timedelta(
            seconds=self.settings.remote_agent_offline_timeout_seconds
        )
        expired = self.targets.list_expired_active_for_update(
            environment_id,
            cutoff,
        )
        for target in expired:
            previous_status = target.status
            target.status = "offline"
            target.last_error_code = "heartbeat_timeout"
            target.last_status_changed_at = now
            target.last_event_at = now
            self.events.record(
                event_type="RemoteAgentOffline",
                actor_type="system",
                actor_id="heartbeat-reconciliation",
                payload={
                    "environment_id": str(environment_id),
                    "remote_target_id": str(target.id),
                    "agent_id": target.agent_id,
                    "previous_status": previous_status,
                    "status": "offline",
                    "last_heartbeat_at": (
                        target.last_heartbeat_at.isoformat()
                        if target.last_heartbeat_at
                        else None
                    ),
                    "timeout_seconds": (
                        self.settings.remote_agent_offline_timeout_seconds
                    ),
                },
            )
        return len(expired)

    def _to_read(self, target: RemoteTarget) -> RemoteTargetRead:
        """将内部目标与 credential 元数据转换为脱敏响应。"""

        credentials = self.targets.list_credentials(target.id)
        parsed = urlsplit(target.agent_endpoint)
        port = f":{parsed.port}" if parsed.port is not None else ""
        endpoint_display = f"{parsed.scheme}://<redacted>{port}"
        return RemoteTargetRead(
            id=target.id,
            environment_id=target.environment_id,
            display_name=target.display_name,
            target_type=target.target_type,
            agent_id=target.agent_id,
            endpoint_display=endpoint_display,
            tls_fingerprint=target.tls_fingerprint,
            credential_fingerprints=[
                item.secret_fingerprint for item in credentials
            ],
            status=target.status,
            agent_version=target.agent_version,
            capabilities=list(target.capabilities_json),
            last_heartbeat_at=target.last_heartbeat_at,
            last_error_code=target.last_error_code,
            last_event_at=target.last_event_at,
            last_status_changed_at=target.last_status_changed_at,
            created_at=target.created_at,
            updated_at=target.updated_at,
        )
