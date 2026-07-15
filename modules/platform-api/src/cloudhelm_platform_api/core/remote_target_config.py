"""M7 RemoteTarget profile 与 machine credential 配置模型。

这些模型只描述服务端受控配置，不是普通 API 请求 DTO。endpoint、TLS
指纹、credential 引用和 secret 均由部署配置注入，调用方只能引用
``profile_key``，从而避免把远端连接边界变成用户可覆盖字段。
"""

from datetime import UTC, datetime
from typing import Literal

from pydantic import (
    BaseModel,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)


class RemoteAgentCredentialConfig(BaseModel):
    """服务端受控的 Remote Agent machine credential 元数据。

    ``credential_ref`` 只指向 ``Settings.remote_agent_credentials`` 中的
    ``SecretStr``；真实 secret 不进入 ORM、API、EventLog 或异常消息。
    """

    key_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
        description="轮换期间稳定区分新旧密钥的 key id。",
    )
    credential_ref: str = Field(
        min_length=1,
        max_length=255,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$",
        description="指向服务端 secret 映射的引用。",
    )
    scopes: list[str] = Field(
        default_factory=lambda: ["heartbeat"],
        min_length=1,
        max_length=32,
        description="该密钥允许调用的 machine API scope。",
    )
    active_from: datetime = Field(
        default_factory=lambda: datetime(1970, 1, 1, tzinfo=UTC),
        description="密钥开始生效时间。",
    )
    expires_at: datetime | None = Field(
        default=None,
        description="密钥过期时间；为空表示由轮换或撤销控制。",
    )
    revoked_at: datetime | None = Field(
        default=None,
        description="密钥撤销时间；为空表示尚未撤销。",
    )

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, value: list[str]) -> list[str]:
        """拒绝空白、重复或不规范 scope，保证授权比较可预测。"""

        normalized = [item.strip() for item in value]
        if any(
            not item
            or len(item) > 64
            or not all(
                character.isalnum() or character in "._:-"
                for character in item
            )
            for item in normalized
        ):
            raise ValueError("Remote Agent credential scope 格式非法。")
        if len(normalized) != len(set(normalized)):
            raise ValueError("Remote Agent credential scope 不能重复。")
        return normalized

    @field_validator("active_from", "expires_at", "revoked_at")
    @classmethod
    def require_timezone(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        """所有 credential 时间必须携带时区，避免本地时区歧义。"""

        if value is not None and (
            value.tzinfo is None or value.utcoffset() is None
        ):
            raise ValueError("Remote Agent credential 时间必须携带时区。")
        return value

    @model_validator(mode="after")
    def validate_lifecycle(self) -> "RemoteAgentCredentialConfig":
        """过期时间必须晚于生效时间；撤销时间可位于任意有效轮换点。"""

        if (
            self.expires_at is not None
            and self.expires_at <= self.active_from
        ):
            raise ValueError("Remote Agent credential 过期时间必须晚于生效时间。")
        return self


class RemoteTargetProfileConfig(BaseModel):
    """普通 API 可引用、但不能覆盖的 RemoteTarget 服务端配置。"""

    agent_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
        description="远端 Agent 稳定身份。",
    )
    agent_endpoint: HttpUrl = Field(
        description="Deployment Controller 使用的受控 HTTPS endpoint。",
    )
    tls_fingerprint: str = Field(
        pattern=r"^sha256:[0-9a-f]{64}$",
        description="Remote Agent TLS 证书指纹。",
    )
    target_type: Literal["linux_remote_agent"] = Field(
        default="linux_remote_agent",
        description="M7 远端目标类型。",
    )
    credentials: list[RemoteAgentCredentialConfig] = Field(
        min_length=1,
        max_length=8,
        description="支持短期重叠轮换的 machine credentials。",
    )

    @field_validator("agent_endpoint")
    @classmethod
    def require_safe_https_origin(cls, value: HttpUrl) -> HttpUrl:
        """Remote Agent endpoint 必须是无用户信息、查询和片段的 HTTPS origin。"""

        if value.scheme != "https":
            raise ValueError("Remote Agent endpoint 必须使用 HTTPS。")
        if value.username or value.password or value.query or value.fragment:
            raise ValueError("Remote Agent endpoint 只能配置 HTTPS origin。")
        if value.path not in ("", "/"):
            raise ValueError("Remote Agent endpoint 不能包含业务路径。")
        return value

    @field_validator("credentials")
    @classmethod
    def validate_credential_ids(
        cls,
        value: list[RemoteAgentCredentialConfig],
    ) -> list[RemoteAgentCredentialConfig]:
        """同一 profile 内的 key id 和 credential ref 必须唯一。"""

        key_ids = [item.key_id for item in value]
        credential_refs = [item.credential_ref for item in value]
        if len(key_ids) != len(set(key_ids)):
            raise ValueError("Remote Agent credential key_id 不能重复。")
        if len(credential_refs) != len(set(credential_refs)):
            raise ValueError("Remote Agent credential_ref 不能重复。")
        return value
