"""M7 ServiceInstance ORM 模型。"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from cloudhelm_platform_api.db.base import (
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class ServiceInstance(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Deployment 下由 Remote Agent 发现的 Docker Compose 服务实例。

    跨表 Environment、Target 与 digest 一致性由后续 service 在父资源锁内
    重验；本模型只约束单行 runtime、状态和健康证据。
    """

    __tablename__ = "service_instances"
    __table_args__ = (
        CheckConstraint(
            "runtime_type = 'docker_compose'",
            name="ck_service_instances_runtime_type",
        ),
        CheckConstraint(
            """
            status IN (
              'starting', 'running', 'healthy',
              'unhealthy', 'stopped', 'failed'
            )
            """,
            name="ck_service_instances_status",
        ),
        CheckConstraint(
            """
            service_name ~ '^[a-z0-9][a-z0-9_-]{0,62}$'
            AND compose_project ~ '^[a-z0-9][a-z0-9_-]{0,62}$'
            """,
            name="ck_service_instances_slugs",
        ),
        CheckConstraint(
            """
            runtime_ref IS NULL
            OR (
              length(btrim(runtime_ref)) BETWEEN 1 AND 255
              AND runtime_ref !~ '[[:cntrl:]]'
            )
            """,
            name="ck_service_instances_runtime_ref",
        ),
        CheckConstraint(
            "image_digest ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_service_instances_image_digest",
        ),
        CheckConstraint(
            """
            health_url IS NULL
            OR (
              length(health_url) BETWEEN 1 AND 2048
              AND health_url ~ '^https?://[^[:space:]]+$'
              AND health_url !~ '[[:cntrl:]]'
              AND health_url ~ '^https?://[^/[:space:]?#]+'
              AND health_url !~ '^https?://[^/?#]*@'
              AND position(chr(92) IN health_url) = 0
              AND position('#' IN health_url) = 0
            )
            """,
            name="ck_service_instances_health_url",
        ),
        CheckConstraint(
            """
            health_result_json IS NULL
            OR jsonb_typeof(health_result_json)
              IS NOT DISTINCT FROM 'object'
            """,
            name="ck_service_instances_health_result_object",
        ),
        CheckConstraint(
            """
            health_result_json IS NULL
            OR jsonb_typeof(health_result_json) IS DISTINCT FROM 'object'
            OR (
              jsonb_array_length(
                jsonb_path_query_array(
                  health_result_json,
                  '$.keyvalue()'
                )
              ) <= 32
              AND NOT jsonb_path_exists(
                health_result_json,
                '$.keyvalue() ? (!(@.key like_regex "^[a-z][a-z0-9_]{0,63}$"))'
              )
              AND NOT jsonb_path_exists(
                health_result_json,
                '$.keyvalue() ? (@.key like_regex "(^|_)(token|tokens|secret|secrets|credential|credentials|password|passwords|cookie|cookies|authorization|raw_logs|stdout|stderr|log|logs)(_|$)" flag "i")'
              )
              AND NOT jsonb_path_exists(
                health_result_json,
                '$.* ? (@.type() == "array" || @.type() == "object")'
              )
              AND NOT jsonb_path_exists(
                health_result_json,
                '$.* ? (@.type() == "string" && @ like_regex "^.{255}.{255}.{3}" flag "s")'
              )
            )
            """,
            name="ck_service_instances_health_result_safe",
        ),
        CheckConstraint(
            """
            (health_result_json IS NULL) = (last_health_check_at IS NULL)
            AND (
              status NOT IN ('healthy', 'unhealthy')
              OR (
                health_result_json IS NOT NULL
                AND last_health_check_at IS NOT NULL
              )
            )
            """,
            name="ck_service_instances_health_lifecycle",
        ),
        CheckConstraint(
            """
            (
              last_error_code IS NULL
              OR last_error_code ~ '^[a-z][a-z0-9_]{0,127}$'
            )
            AND (status <> 'failed' OR last_error_code IS NOT NULL)
            """,
            name="ck_service_instances_error_code",
        ),
        CheckConstraint(
            """
            updated_at >= created_at
            AND (
              last_health_check_at IS NULL
              OR last_health_check_at >= created_at
            )
            """,
            name="ck_service_instances_time_order",
        ),
        UniqueConstraint(
            "deployment_id",
            "service_name",
            name="uq_service_instances_deployment_service",
        ),
    )

    deployment_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("deployments.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属 Deployment。",
    )
    environment_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("environments.id", ondelete="NO ACTION"),
        nullable=False,
        comment="所属 staging/demo Environment。",
    )
    remote_target_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("remote_targets.id", ondelete="NO ACTION"),
        nullable=False,
        comment="运行服务的 Linux RemoteTarget。",
    )
    service_name: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="受控 Compose service slug。",
    )
    compose_project: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="受控 Compose project slug。",
    )
    runtime_type: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="docker_compose",
        server_default="docker_compose",
        comment="M7 固定为 docker_compose。",
    )
    runtime_ref: Mapped[str | None] = mapped_column(
        Text,
        comment="Remote Agent 返回的容器或服务引用。",
    )
    image_digest: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="不可变 OCI digest。",
    )
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="starting",
        server_default="starting",
        comment="服务生命周期状态。",
    )
    health_url: Mapped[str | None] = mapped_column(
        Text,
        comment="服务端 profile 派生的健康 URL。",
    )
    health_result_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True),
        comment="最近一次结构化脱敏健康结果。",
    )
    last_health_check_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        comment="最近一次健康检查时间。",
    )
    last_error_code: Mapped[str | None] = mapped_column(
        Text,
        comment="稳定、脱敏的最近错误码。",
    )


Index(
    "ix_service_instances_environment_status_created",
    ServiceInstance.environment_id,
    ServiceInstance.status,
    ServiceInstance.created_at.desc(),
    ServiceInstance.id.desc(),
)
Index(
    "ix_service_instances_remote_target_status_created",
    ServiceInstance.remote_target_id,
    ServiceInstance.status,
    ServiceInstance.created_at.desc(),
    ServiceInstance.id.desc(),
)
