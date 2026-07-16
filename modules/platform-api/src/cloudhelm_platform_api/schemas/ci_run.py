"""M7 CIRun 内部严格 record 契约。"""

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

from cloudhelm_platform_api.schemas.m7_lifecycle_schema import (
    CI_RUN_JSON_SCHEMA_EXTRA,
)

CommitSha = Annotated[
    str,
    Field(pattern=r"^[0-9a-f]{40}([0-9a-f]{24})?$"),
]
Digest = Annotated[
    str,
    Field(pattern=r"^sha256:[0-9a-f]{64}$"),
]
SourceRef = Annotated[
    str,
    Field(
        min_length=12,
        max_length=512,
        pattern=r"^refs/heads/[^\s~^:?*\[\\]+$",
    ),
    WithJsonSchema(
        {
            "type": "string",
            "minLength": 12,
            "maxLength": 512,
            "pattern": r"^refs/heads/[^\s~^:?*\[\\]+$",
            "allOf": [
                {
                    "not": {
                        "pattern": r"\.\.|//|@\{",
                    }
                },
                {
                    "not": {
                        "pattern": r"(^|/)\.",
                    }
                },
                {
                    "not": {
                        "pattern": r"\.lock(/|$)",
                    }
                },
                {
                    "not": {
                        "pattern": r"[./]$",
                    }
                },
            ],
        }
    ),
]
CIRunStatus = Literal[
    "triggered",
    "running",
    "passed",
    "failed",
    "cancelled",
]


class CIRunRecord(BaseModel):
    """可跨模块传递的完整 CIRun 数据记录。"""

    model_config = ConfigDict(
        extra="forbid",
        from_attributes=True,
        json_schema_extra=CI_RUN_JSON_SCHEMA_EXTRA,
    )

    id: UUID
    task_id: UUID
    project_id: UUID
    pull_request_record_id: UUID
    release_candidate_id: UUID
    provider: Literal["gitea"]
    repository_external_id: str = Field(min_length=1, max_length=255)
    external_run_id: str | None = Field(min_length=1, max_length=255)
    external_job_id: str | None = Field(min_length=1, max_length=255)
    workflow_id: str = Field(min_length=1, max_length=512)
    workflow_revision: str = Field(min_length=1, max_length=255)
    source_ref: SourceRef
    commit_sha: CommitSha
    status: CIRunStatus
    idempotency_key: str = Field(min_length=1, max_length=180)
    last_event_action: str | None = Field(min_length=1, max_length=128)
    last_event_status: str | None = Field(min_length=1, max_length=128)
    last_delivery_id: str | None = Field(min_length=1, max_length=255)
    provider_head_sha: CommitSha | None
    provider_updated_at: datetime | None
    artifact_manifest_id: UUID | None
    image_index_digest: Digest | None
    platform_manifest_digest: Digest | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @field_validator(
        "provider_updated_at",
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
            raise ValueError("CIRun 时间字段必须携带时区。")
        return value

    @field_validator("source_ref")
    @classmethod
    def validate_git_ref(cls, value: str) -> str:
        """补充 JSON Schema pattern 不便表达的 Git ref 门禁。"""

        invalid = (
            ".." in value
            or "//" in value
            or "@{" in value
            or value.endswith((".", "/", ".lock"))
            or any(part.startswith(".") for part in value.split("/"))
            or any(part.endswith(".lock") for part in value.split("/"))
        )
        if invalid:
            raise ValueError("source_ref 不是安全完整 Git ref。")
        return value

    @model_validator(mode="after")
    def validate_evidence(self) -> "CIRunRecord":
        """保证 provider 幂等线索和状态证据不会形成半组数据。"""

        self._validate_provider_identity()
        self._validate_state_evidence()
        self._validate_time_order()
        return self

    def _validate_provider_identity(self) -> None:
        """验证 provider event、run/job 与 head SHA 的绑定关系。"""

        event_group = (
            self.last_event_action,
            self.last_event_status,
            self.last_delivery_id,
            self.provider_updated_at,
        )
        if any(value is None for value in event_group) and any(
            value is not None for value in event_group
        ):
            raise ValueError("provider event 幂等线索必须全空或全有。")
        if (
            self.external_job_id is not None
            and self.external_run_id is None
        ):
            raise ValueError("external_job_id 必须绑定 external_run_id。")
        if (
            self.provider_head_sha is not None
            and self.provider_head_sha != self.commit_sha
        ):
            raise ValueError("provider_head_sha 必须等于 commit_sha。")
        if (
            self.status in {"running", "passed"}
            and self.external_run_id is None
        ):
            raise ValueError("running/passed 必须绑定 external_run_id。")

    def _validate_state_evidence(self) -> None:
        """验证五个 CI 状态允许的时间与不可变制品证据。"""

        success = (
            self.artifact_manifest_id,
            self.image_index_digest,
            self.platform_manifest_digest,
        )
        if self.status == "triggered":
            valid = self.started_at is None and self.finished_at is None
        elif self.status == "running":
            valid = self.started_at is not None and self.finished_at is None
        elif self.status == "passed":
            valid = (
                self.started_at is not None
                and self.finished_at is not None
                and self.provider_head_sha is not None
                and all(value is not None for value in success)
            )
        else:
            valid = self.finished_at is not None
        if self.status != "passed" and any(
            value is not None for value in success
        ):
            valid = False
        if not valid:
            raise ValueError("CIRun 状态与证据组合不一致。")

    def _validate_time_order(self) -> None:
        """验证创建、开始、完成和更新时间的单调顺序。"""

        if self.updated_at < self.created_at:
            raise ValueError("updated_at 不能早于 created_at。")
        if self.started_at is not None and self.started_at < self.created_at:
            raise ValueError("started_at 不能早于 created_at。")
        reference = self.started_at or self.created_at
        if self.finished_at is not None and self.finished_at < reference:
            raise ValueError("finished_at 时间顺序非法。")
