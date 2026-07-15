"""M7 RemoteTarget 与 heartbeat API DTO。"""

from datetime import datetime
import re
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)

_CAPABILITY = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")


class RemoteTargetCreate(BaseModel):
    """通过服务端 profile 注册 RemoteTarget。

    endpoint、agent、TLS 和 credential 均由 profile 派生，调用方只能提交
    `profile_key` 与展示名称。
    """

    model_config = ConfigDict(extra="forbid")

    profile_key: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
        description="服务端受控 RemoteTarget profile key。",
    )
    display_name: str = Field(
        min_length=1,
        max_length=120,
        description="控制台展示名称。",
    )


class RemoteTargetRead(BaseModel):
    """脱敏后的 RemoteTarget 响应。"""

    id: UUID
    environment_id: UUID
    display_name: str
    target_type: Literal["linux_remote_agent"]
    agent_id: str
    endpoint_display: str
    tls_fingerprint: str
    credential_fingerprints: list[str]
    status: Literal["offline", "online", "degraded", "disabled"]
    agent_version: str | None
    capabilities: list[str]
    last_heartbeat_at: datetime | None
    last_error_code: str | None
    last_event_at: datetime | None
    last_status_changed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class RemoteAgentHeartbeat(BaseModel):
    """Remote Agent 已签名心跳请求体。"""

    model_config = ConfigDict(extra="forbid")

    target_id: UUID
    agent_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    agent_version: str = Field(min_length=1, max_length=64)
    capabilities: list[str] = Field(min_length=1, max_length=32)
    reported_at: datetime

    @field_validator("capabilities")
    @classmethod
    def validate_capabilities(cls, value: list[str]) -> list[str]:
        """拒绝空白、重复或过长 capability。"""

        normalized = [item.strip() for item in value]
        if any(not _CAPABILITY.fullmatch(item) for item in normalized):
            raise ValueError("capability 格式非法。")
        if len(normalized) != len(set(normalized)):
            raise ValueError("capability 不能重复。")
        return normalized

    @field_validator("reported_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        """Agent 上报时间必须携带时区。"""

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("reported_at 必须携带时区。")
        return value


class RemoteAgentHeartbeatRead(BaseModel):
    """心跳接收结果。"""

    target_id: UUID
    agent_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    status: Literal["online", "degraded"]
    accepted_at: datetime
    next_heartbeat_after_seconds: int = Field(ge=1, le=3600)
