"""Remote Agent machine-auth HMAC 校验与 replay 防护。"""

from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import logging
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cloudhelm_platform_api.core.config import Settings, get_settings
from cloudhelm_platform_api.db.base import utc_now
from cloudhelm_platform_api.models.remote_target import RemoteAgentReplayNonce
from cloudhelm_platform_api.providers.remote_target_profile_provider import (
    RemoteTargetProfileProvider,
)
from cloudhelm_platform_api.repositories.remote_target_repository import (
    RemoteTargetRepository,
)
from cloudhelm_platform_api.services.base import BaseService
from cloudhelm_platform_api.services.database_errors import (
    database_write_error,
    integrity_constraint_name,
)
from cloudhelm_platform_api.services.exceptions import ServiceError
from cloudhelm_platform_api.services.machine_auth_contract import (
    IDENTITY_PATTERN,
    NONCE_PATTERN,
    SHA256_PATTERN,
    MachineIdentity,
    body_sha256,
    canonical_request,
)
_DUMMY_MACHINE_SECRET = hashlib.sha256(
    b"cloudhelm-machine-auth-missing-secret"
).digest()
logger = logging.getLogger(__name__)

class MachineAuthService(BaseService):
    """验证 machine credential、签名、时钟和 nonce。

    nonce 在认证成功后立即独立提交，因此后续 heartbeat DTO 或状态校验失败时
    同一已认证请求也不能重放。
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
        self.targets = RemoteTargetRepository(session)

    def authenticate(
        self,
        *,
        method: str,
        path: str,
        body: bytes,
        target_id: str | None,
        agent_id: str | None,
        key_id: str | None,
        timestamp: str | None,
        nonce: str | None,
        signature: str | None,
    ) -> MachineIdentity:
        """校验签名并消费 replay nonce，返回安全身份投影。"""

        values = (target_id, agent_id, key_id, timestamp, nonce, signature)
        if any(value is None for value in values):
            raise ServiceError(
                "machine_auth_required",
                "缺少 Remote Agent machine authentication 请求头。",
                401,
            )
        assert target_id is not None
        assert agent_id is not None
        assert key_id is not None
        assert timestamp is not None
        assert nonce is not None
        assert signature is not None
        if (
            not IDENTITY_PATTERN.fullmatch(agent_id)
            or not IDENTITY_PATTERN.fullmatch(key_id)
            or not NONCE_PATTERN.fullmatch(nonce)
            or not timestamp.isdecimal()
            or not SHA256_PATTERN.fullmatch(signature)
        ):
            raise ServiceError(
                "machine_auth_invalid",
                "Machine authentication 请求无效。",
                401,
            )
        try:
            parsed_target_id = UUID(target_id)
            request_epoch = int(timestamp)
            request_time = datetime.fromtimestamp(request_epoch, UTC)
        except (ValueError, OverflowError, OSError):
            raise ServiceError(
                "machine_auth_invalid",
                "Machine authentication 请求无效。",
                401,
            ) from None

        now = utc_now()
        if abs((now - request_time).total_seconds()) > (
            self.settings.remote_agent_timestamp_tolerance_seconds
        ):
            raise ServiceError(
                "machine_auth_expired",
                "Machine authentication 请求时间已失效。",
                401,
            )

        target = self.targets.get(parsed_target_id)
        credential = self.targets.get_credential_for_update(
            parsed_target_id,
            agent_id,
            key_id,
        )
        if (
            target is None
            or credential is None
            or target.agent_id != agent_id
        ):
            raise ServiceError(
                "machine_auth_invalid",
                "Machine authentication 请求无效。",
                401,
            )
        configured_secret = self.profiles.find_secret(
            credential.credential_ref
        )
        secret_missing = configured_secret is None
        secret = (
            _DUMMY_MACHINE_SECRET
            if configured_secret is None
            else configured_secret.get_secret_value().encode("utf-8")
        )
        canonical = canonical_request(
            method,
            path,
            timestamp,
            nonce,
            body_sha256(body),
        )
        expected = hmac.new(
            secret,
            canonical.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        signature_matches = hmac.compare_digest(expected, signature)
        if secret_missing:
            logger.error(
                "Remote Agent machine credential 配置缺失，target_id=%s key_id=%s",
                parsed_target_id,
                key_id,
            )
            raise ServiceError(
                "machine_auth_invalid",
                "Machine authentication 请求无效。",
                401,
            )
        if not signature_matches:
            raise ServiceError(
                "machine_auth_invalid",
                "Machine authentication 请求无效。",
                401,
            )
        if len(secret) < 32:
            raise ServiceError(
                "remote_agent_credential_too_short",
                "Remote Agent machine credential 配置不符合最小长度要求。",
                503,
            )
        configured_fingerprint = "sha256:" + hashlib.sha256(secret).hexdigest()
        if not hmac.compare_digest(
            configured_fingerprint,
            credential.secret_fingerprint,
        ):
            raise ServiceError(
                "remote_agent_credential_fingerprint_mismatch",
                "Remote Agent machine credential 配置与登记记录不一致。",
                503,
            )
        if target.status == "disabled":
            raise ServiceError(
                "remote_target_disabled",
                "RemoteTarget 已禁用。",
                403,
            )
        if credential.revoked_at is not None:
            raise ServiceError(
                "machine_auth_revoked",
                "Machine credential 已撤销。",
                401,
            )
        if credential.active_from > now:
            raise ServiceError(
                "machine_auth_invalid",
                "Machine authentication 请求无效。",
                401,
            )
        if credential.expires_at is not None and credential.expires_at <= now:
            raise ServiceError(
                "machine_auth_expired",
                "Machine credential 已过期。",
                401,
            )
        if "heartbeat" not in credential.scopes_json:
            raise ServiceError(
                "machine_auth_scope_denied",
                "Machine credential scope 不允许该操作。",
                403,
            )

        self.targets.delete_expired_replay_nonces(now)
        replay_expires_at = max(
            now
            + timedelta(
                seconds=self.settings.remote_agent_nonce_ttl_seconds
            ),
            request_time
            + timedelta(
                seconds=(
                    self.settings.remote_agent_timestamp_tolerance_seconds + 1
                )
            ),
        )
        try:
            self.targets.create_replay_nonce(
                RemoteAgentReplayNonce(
                    credential_id=credential.id,
                    nonce_hash=hashlib.sha256(
                        nonce.encode("utf-8")
                    ).hexdigest(),
                    request_timestamp=request_time,
                    expires_at=replay_expires_at,
                )
            )
            self.commit()
        except IntegrityError as exc:
            self.session.rollback()
            if integrity_constraint_name(exc) == (
                "uq_remote_agent_replay_nonces_credential_hash"
            ):
                raise ServiceError(
                    "machine_auth_replay",
                    "Machine authentication nonce 已使用。",
                    401,
                ) from None
            raise database_write_error(exc) from exc
        except ServiceError as exc:
            cause = exc.__cause__
            if isinstance(cause, IntegrityError):
                if integrity_constraint_name(cause) == (
                    "uq_remote_agent_replay_nonces_credential_hash"
                ):
                    raise ServiceError(
                        "machine_auth_replay",
                        "Machine authentication nonce 已使用。",
                        401,
                    ) from None
            raise

        return MachineIdentity(
            target_id=parsed_target_id,
            agent_id=agent_id,
            key_id=key_id,
            credential_id=credential.id,
            key_fingerprint=credential.secret_fingerprint,
        )
