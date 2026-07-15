"""Remote Agent HTTP 与 heartbeat 数据结构。"""

from datetime import datetime
import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

_CAPABILITY = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")


class HealthResponse(BaseModel):
    """进程健康状态；不包含凭据、路径或 Platform API 地址。"""

    service: Literal["cloudhelm-remote-agent"]
    status: Literal["ok"]
    version: str
    agent_id: str
    capabilities: list[str]


class VersionResponse(BaseModel):
    """Remote Agent 版本元数据。"""

    service: Literal["cloudhelm-remote-agent"]
    version: str
    agent_id: str


class CapabilitiesResponse(BaseModel):
    """Remote Agent 当前真实支持的 capability。"""

    service: Literal["cloudhelm-remote-agent"]
    agent_id: str
    capabilities: list[str]


class HeartbeatPayload(BaseModel):
    """发送给 Platform API 的固定心跳正文。"""

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
        """拒绝重复或不符合 Platform 契约的 capability。"""

        normalized = [item.strip() for item in value]
        if any(not _CAPABILITY.fullmatch(item) for item in normalized):
            raise ValueError("capability 格式非法。")
        if len(normalized) != len(set(normalized)):
            raise ValueError("capability 不能重复。")
        return normalized

    @field_validator("reported_at")
    @classmethod
    def validate_reported_at(cls, value: datetime) -> datetime:
        """拒绝无时区时间，避免签名正文产生本地时区歧义。"""

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("reported_at 必须包含时区。")
        return value


class HeartbeatAck(BaseModel):
    """Platform API 成功接收 heartbeat 后的确认结构。"""

    model_config = ConfigDict(extra="ignore")

    target_id: UUID
    agent_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    status: Literal["online", "degraded"]
    accepted_at: datetime
    next_heartbeat_after_seconds: int = Field(ge=1, le=3600)
