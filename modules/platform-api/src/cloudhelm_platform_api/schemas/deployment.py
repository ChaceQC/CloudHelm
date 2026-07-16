"""M7 Deployment 内部严格 record 契约。"""

from datetime import datetime
from typing import Annotated, Literal
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
    DEPLOYMENT_JSON_SCHEMA_EXTRA,
)

CommitSha = Annotated[
    str,
    Field(pattern=r"^[0-9a-f]{40}([0-9a-f]{24})?$"),
]
Digest = Annotated[
    str,
    Field(pattern=r"^sha256:[0-9a-f]{64}$"),
]
ReleaseVersion = Annotated[
    str,
    Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
    ),
]
ImageRef = Annotated[
    str,
    Field(
        min_length=1,
        max_length=512,
        pattern=r"^[^\s@?#\\]+@sha256:[0-9a-f]{64}$",
    ),
    WithJsonSchema(
        {
            "type": "string",
            "minLength": 1,
            "maxLength": 512,
            "pattern": r"^[^\s@?#\\]+@sha256:[0-9a-f]{64}$",
            "not": {
                "pattern": r"^[A-Za-z][A-Za-z0-9+.-]*://",
            },
        }
    ),
]
DeploymentStatus = Literal[
    "planned",
    "pending_approval",
    "queued",
    "deploying",
    "verifying",
    "healthy",
    "unhealthy",
    "failed",
    "rollback_requested",
    "cancelled",
]


class DeploymentRecord(BaseModel):
    """可跨模块传递的完整 Deployment 数据记录。"""

    model_config = ConfigDict(
        extra="forbid",
        from_attributes=True,
        json_schema_extra=DEPLOYMENT_JSON_SCHEMA_EXTRA,
    )

    id: UUID
    task_id: UUID
    project_id: UUID
    environment_id: UUID
    remote_target_id: UUID
    ci_run_id: UUID
    release_plan_artifact_id: UUID
    commit_sha: CommitSha
    image_ref: ImageRef
    image_digest: Digest
    platform_manifest_digest: Digest
    release_version: ReleaseVersion
    request_hash: Digest
    approval_id: UUID | None
    remote_operation_id: str | None = Field(min_length=1, max_length=255)
    status: DeploymentStatus
    health_summary_json: HealthEvidence | None
    failure_code: str | None = Field(
        max_length=128,
        pattern=r"^[a-z][a-z0-9_]{0,127}$",
    )
    failure_summary: str | None = Field(min_length=1, max_length=2048)
    requested_by_actor: str = Field(min_length=1, max_length=255)
    approved_by_actor: str | None = Field(min_length=1, max_length=255)
    dispatched_by_agent_run_id: UUID | None
    idempotency_key: str = Field(min_length=1, max_length=180)
    started_at: datetime | None
    finished_at: datetime | None
    rollback_candidate_id: UUID | None
    rollback_request_artifact_id: UUID | None
    created_at: datetime
    updated_at: datetime

    @field_validator(
        "started_at",
        "finished_at",
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
            raise ValueError("Deployment 时间字段必须携带时区。")
        return value

    @field_validator(
        "image_ref",
        "requested_by_actor",
        "approved_by_actor",
        "remote_operation_id",
        "failure_summary",
    )
    @classmethod
    def reject_control_characters(
        cls,
        value: str | None,
    ) -> str | None:
        """拒绝空白边界和控制字符进入审计摘要。"""

        if value is None:
            return value
        if value != value.strip() or any(ord(char) < 32 for char in value):
            raise ValueError("Deployment 文本字段包含非法边界或控制字符。")
        return value

    @field_validator("health_summary_json")
    @classmethod
    def reject_sensitive_health_evidence(
        cls,
        value: HealthEvidence | None,
    ) -> HealthEvidence | None:
        """健康摘要只允许受控、脱敏的标量字段。"""

        return validate_health_evidence(value)

    @model_validator(mode="after")
    def validate_lifecycle(self) -> "DeploymentRecord":
        """验证 Approval、operation、健康、失败和 rollback 证据。"""

        self._validate_image_identity()
        self._validate_approval_evidence()
        self._validate_operation_evidence()
        self._validate_terminal_evidence()
        self._validate_time_order()
        return self

    def _validate_image_identity(self) -> None:
        """验证 OCI ref 只绑定当前不可变 digest。"""

        if "://" in self.image_ref or self.image_ref.count("@") != 1:
            raise ValueError("image_ref 不能包含 scheme、userinfo 或多重 @。")
        if not self.image_ref.endswith(f"@{self.image_digest}"):
            raise ValueError("image_ref 必须以不可变 image_digest 结尾。")

    def _validate_approval_evidence(self) -> None:
        """验证状态对应的第二道 Approval 与批准人投影。"""

        if self.status == "planned":
            approval_valid = (
                self.approval_id is None
                and self.approved_by_actor is None
            )
        elif self.status == "pending_approval":
            approval_valid = (
                self.approval_id is not None
                and self.approved_by_actor is None
            )
        elif self.status in {
            "queued",
            "deploying",
            "verifying",
            "healthy",
            "unhealthy",
            "rollback_requested",
        }:
            approval_valid = (
                self.approval_id is not None
                and self.approved_by_actor is not None
            )
        else:
            approval_valid = (
                self.approved_by_actor is None
                or self.approval_id is not None
            )
        if not approval_valid:
            raise ValueError("Deployment Approval 证据组合不一致。")

    def _validate_operation_evidence(self) -> None:
        """验证 Remote Agent operation 与开始/完成时间组合。"""

        if self.status in {"planned", "pending_approval", "queued"}:
            operation_valid = (
                self.remote_operation_id is None
                and self.started_at is None
                and self.finished_at is None
            )
        elif self.status in {"deploying", "verifying"}:
            operation_valid = (
                self.remote_operation_id is not None
                and self.started_at is not None
                and self.finished_at is None
            )
        elif self.status in {"healthy", "unhealthy", "rollback_requested"}:
            operation_valid = (
                self.remote_operation_id is not None
                and self.started_at is not None
                and self.finished_at is not None
            )
        else:
            operation_valid = (
                self.finished_at is not None
                and (
                    (
                        self.remote_operation_id is None
                        and self.started_at is None
                    )
                    or (
                        self.remote_operation_id is not None
                        and self.started_at is not None
                    )
                )
            )
        if not operation_valid:
            raise ValueError("Deployment operation 证据组合不一致。")

    def _validate_terminal_evidence(self) -> None:
        """验证健康、失败与 rollback 引用不会跨状态漂移。"""

        if (
            self.status in {"healthy", "unhealthy", "rollback_requested"}
            and self.health_summary_json is None
        ):
            raise ValueError("健康或回滚请求状态必须具有 health summary。")
        if self.status == "failed":
            if self.failure_code is None:
                raise ValueError("failed 必须具有 failure_code。")
        elif self.failure_code is not None or self.failure_summary is not None:
            raise ValueError("非 failed 状态不得携带 failure evidence。")

        rollback_values = (
            self.rollback_candidate_id,
            self.rollback_request_artifact_id,
        )
        if self.status == "rollback_requested":
            if any(value is None for value in rollback_values):
                raise ValueError("rollback_requested 缺少完整回滚引用。")
            if self.rollback_candidate_id == self.id:
                raise ValueError("rollback candidate 不能自引用。")
        elif any(value is not None for value in rollback_values):
            raise ValueError("非 rollback_requested 不得携带回滚引用。")

    def _validate_time_order(self) -> None:
        """验证创建、开始、完成和更新时间的单调顺序。"""

        if self.updated_at < self.created_at:
            raise ValueError("updated_at 不能早于 created_at。")
        if self.started_at is not None and self.started_at < self.created_at:
            raise ValueError("started_at 不能早于 created_at。")
        reference = self.started_at or self.created_at
        if self.finished_at is not None and self.finished_at < reference:
            raise ValueError("finished_at 时间顺序非法。")
