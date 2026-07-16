"""M7 ServiceInstance 内部严格 record 契约。"""

from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    WithJsonSchema,
    field_validator,
    model_validator,
)

from cloudhelm_platform_api.schemas.health_evidence import (
    HealthEvidence,
    validate_health_evidence,
)
from cloudhelm_platform_api.schemas.m7_lifecycle_schema import (
    SERVICE_INSTANCE_JSON_SCHEMA_EXTRA,
)

Digest = Annotated[
    str,
    Field(pattern=r"^sha256:[0-9a-f]{64}$"),
]
Slug = Annotated[
    str,
    Field(
        min_length=1,
        max_length=63,
        pattern=r"^[a-z0-9][a-z0-9_-]{0,62}$",
    ),
]
HealthUrl = Annotated[
    str,
    Field(
        min_length=1,
        max_length=2048,
        pattern=r"^https?://[^\s]+$",
    ),
    WithJsonSchema(
        {
            "type": "string",
            "minLength": 1,
            "maxLength": 2048,
            "format": "uri",
            "pattern": r"^https?://[^\s]+$",
            "not": {
                "pattern": r"^https?://[^/?#]*@",
            },
        }
    ),
]
ServiceInstanceStatus = Literal[
    "starting",
    "running",
    "healthy",
    "unhealthy",
    "stopped",
    "failed",
]


class ServiceInstanceRecord(BaseModel):
    """可跨模块传递的完整 ServiceInstance 数据记录。"""

    model_config = ConfigDict(
        extra="forbid",
        from_attributes=True,
        json_schema_extra=SERVICE_INSTANCE_JSON_SCHEMA_EXTRA,
    )

    id: UUID
    deployment_id: UUID
    environment_id: UUID
    remote_target_id: UUID
    service_name: Slug
    compose_project: Slug
    runtime_type: Literal["docker_compose"]
    runtime_ref: str | None = Field(min_length=1, max_length=255)
    image_digest: Digest
    status: ServiceInstanceStatus
    health_url: HealthUrl | None
    health_result_json: HealthEvidence | None
    last_health_check_at: datetime | None
    last_error_code: str | None = Field(
        max_length=128,
        pattern=r"^[a-z][a-z0-9_]{0,127}$",
    )
    created_at: datetime
    updated_at: datetime

    @field_validator(
        "last_health_check_at",
        "created_at",
        "updated_at",
    )
    @classmethod
    def require_timezone(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        """所有 record 时间必须携带时区。"""

        if value is not None and (
            value.tzinfo is None or value.utcoffset() is None
        ):
            raise ValueError("ServiceInstance 时间字段必须携带时区。")
        return value

    @field_validator("runtime_ref", "health_url")
    @classmethod
    def reject_control_characters(
        cls,
        value: str | None,
    ) -> str | None:
        """拒绝空白边界和控制字符进入运行时引用。"""

        if value is None:
            return value
        if value != value.strip() or any(ord(char) < 32 for char in value):
            raise ValueError("ServiceInstance 文本字段格式非法。")
        if value.startswith(("http://", "https://")):
            try:
                parsed = urlsplit(value)
                has_userinfo = (
                    parsed.username is not None
                    or parsed.password is not None
                )
            except ValueError as error:
                raise ValueError("health_url 不是合法 HTTP URL。") from error
            if (
                parsed.scheme not in {"http", "https"}
                or parsed.hostname is None
                or has_userinfo
                or "\\" in value
                or parsed.fragment
            ):
                raise ValueError(
                    "health_url 必须具有 host 且不能包含 userinfo。"
                )
        return value

    @field_validator("health_result_json")
    @classmethod
    def reject_sensitive_health_evidence(
        cls,
        value: HealthEvidence | None,
    ) -> HealthEvidence | None:
        """健康结果只允许受控、脱敏的标量字段。"""

        return validate_health_evidence(value)

    @model_validator(mode="after")
    def validate_health_evidence(self) -> "ServiceInstanceRecord":
        """验证健康证据、失败码与时间顺序。"""

        evidence_pair = (
            self.health_result_json is None
            and self.last_health_check_at is None
        ) or (
            self.health_result_json is not None
            and self.last_health_check_at is not None
        )
        if not evidence_pair:
            raise ValueError("health result 与 check time 必须成对出现。")
        if (
            self.status in {"healthy", "unhealthy"}
            and self.health_result_json is None
        ):
            raise ValueError("健康状态必须具有结构化健康证据。")
        if self.status == "failed" and self.last_error_code is None:
            raise ValueError("failed 必须具有 last_error_code。")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at 不能早于 created_at。")
        if (
            self.last_health_check_at is not None
            and self.last_health_check_at < self.created_at
        ):
            raise ValueError("last_health_check_at 不能早于 created_at。")
        return self
