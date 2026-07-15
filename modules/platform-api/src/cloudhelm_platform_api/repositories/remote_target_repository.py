"""RemoteTarget、machine credential 与 replay nonce 数据访问。"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, delete, select
from sqlalchemy.orm import Session

from cloudhelm_platform_api.models.remote_target import (
    RemoteAgentCredential,
    RemoteAgentReplayNonce,
    RemoteTarget,
)
from cloudhelm_platform_api.repositories.pagination import fetch_page


class RemoteTargetRepository:
    """RemoteTarget 及其认证子资源的表访问对象。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create_target(self, target: RemoteTarget) -> RemoteTarget:
        """新增 RemoteTarget 并刷新主键。"""

        self.session.add(target)
        self.session.flush()
        return target

    def get(self, target_id: UUID) -> RemoteTarget | None:
        """按 ID 读取 RemoteTarget。"""

        return self.session.get(RemoteTarget, target_id)

    def get_for_update(self, target_id: UUID) -> RemoteTarget | None:
        """锁定 RemoteTarget，串行化心跳状态与事件判定。"""

        return self.session.execute(
            select(RemoteTarget)
            .where(RemoteTarget.id == target_id)
            .with_for_update()
        ).scalar_one_or_none()

    def get_by_environment_agent(
        self,
        environment_id: UUID,
        agent_id: str,
    ) -> RemoteTarget | None:
        """按 Environment 与 Agent 身份读取目标。"""

        return self.session.execute(
            select(RemoteTarget).where(
                RemoteTarget.environment_id == environment_id,
                RemoteTarget.agent_id == agent_id,
            )
        ).scalar_one_or_none()

    def list_by_environment(
        self,
        environment_id: UUID,
        limit: int,
        cursor: str | None,
    ) -> tuple[list[RemoteTarget], str | None]:
        """分页读取 Environment 下的 RemoteTarget。"""

        statement: Select[tuple[RemoteTarget]] = (
            select(RemoteTarget)
            .where(RemoteTarget.environment_id == environment_id)
            .order_by(RemoteTarget.created_at.desc(), RemoteTarget.id.desc())
        )
        return fetch_page(self.session, statement, limit, cursor)

    def list_expired_active_for_update(
        self,
        environment_id: UUID,
        cutoff: datetime,
    ) -> list[RemoteTarget]:
        """锁定超过心跳阈值的 online/degraded targets。"""

        return list(
            self.session.scalars(
                select(RemoteTarget)
                .where(
                    RemoteTarget.environment_id == environment_id,
                    RemoteTarget.status.in_(("online", "degraded")),
                    RemoteTarget.last_heartbeat_at.is_not(None),
                    RemoteTarget.last_heartbeat_at < cutoff,
                )
                .order_by(RemoteTarget.id)
                .with_for_update()
            )
        )

    def create_credential(
        self,
        credential: RemoteAgentCredential,
    ) -> RemoteAgentCredential:
        """新增 machine credential 元数据。"""

        self.session.add(credential)
        self.session.flush()
        return credential

    def get_credential(
        self,
        target_id: UUID,
        agent_id: str,
        key_id: str,
    ) -> RemoteAgentCredential | None:
        """读取精确绑定 target/agent/key 的 machine credential。"""

        return self.session.execute(
            select(RemoteAgentCredential).where(
                RemoteAgentCredential.target_id == target_id,
                RemoteAgentCredential.agent_id == agent_id,
                RemoteAgentCredential.key_id == key_id,
            )
        ).scalar_one_or_none()

    def get_credential_for_update(
        self,
        target_id: UUID,
        agent_id: str,
        key_id: str,
    ) -> RemoteAgentCredential | None:
        """锁定精确 machine credential，避免认证期间被并发轮换。"""

        return self.session.execute(
            select(RemoteAgentCredential)
            .where(
                RemoteAgentCredential.target_id == target_id,
                RemoteAgentCredential.agent_id == agent_id,
                RemoteAgentCredential.key_id == key_id,
            )
            .with_for_update()
        ).scalar_one_or_none()

    def list_credentials(
        self,
        target_id: UUID,
    ) -> list[RemoteAgentCredential]:
        """读取目标的 credential 元数据，用于返回安全 fingerprint。"""

        return list(
            self.session.scalars(
                select(RemoteAgentCredential)
                .where(RemoteAgentCredential.target_id == target_id)
                .order_by(RemoteAgentCredential.created_at, RemoteAgentCredential.id)
            )
        )

    def create_replay_nonce(
        self,
        nonce: RemoteAgentReplayNonce,
    ) -> RemoteAgentReplayNonce:
        """插入 replay identity，由 PostgreSQL 唯一约束裁决并发。"""

        self.session.add(nonce)
        self.session.flush()
        return nonce

    def delete_expired_replay_nonces(self, now: datetime) -> int:
        """删除已过清理时间的 replay identity，避免长期无界增长。"""

        result = self.session.execute(
            delete(RemoteAgentReplayNonce).where(
                RemoteAgentReplayNonce.expires_at <= now
            )
        )
        return int(result.rowcount or 0)
