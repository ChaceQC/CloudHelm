"""M7 durable WorkflowJob 的严格消息、payload 与 result 契约。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

Sha256 = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
CandidateStatus = Literal[
    "pending_approval",
    "approved",
    "rejected",
    "published",
    "stale",
    "cancelled",
]
ApprovalStatus = Literal[
    "pending",
    "approved",
    "rejected",
    "expired",
    "cancelled",
]


class StrictWorkflowModel(BaseModel):
    """拒绝额外字段，并对跨进程 UUID 使用唯一 canonical 文本形式。"""

    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="before")
    @classmethod
    def validate_canonical_uuid_fields(
        cls,
        value: object,
        info,
    ) -> object:
        """拒绝大写、无短横线或带空白的 UUID broker/payload 文本。"""

        if not info.field_name.endswith("_id") or isinstance(value, UUID):
            return value
        if not isinstance(value, str):
            return value
        try:
            canonical = str(UUID(value))
        except ValueError:
            return value
        if value != canonical:
            raise ValueError("UUID 必须使用小写、带短横线的 canonical 形式。")
        return value


class WorkflowJobBrokerMessage(StrictWorkflowModel):
    """Celery 业务消息；broker 永远只携带 PostgreSQL job ID。"""

    workflow_job_id: UUID


class ReleaseCandidateReconcilePayload(StrictWorkflowModel):
    """`release_candidate_reconcile` 的不可扩展输入。"""

    schema_version: Literal[
        "m7.release-candidate-reconcile.payload.v1"
    ]
    candidate_id: UUID
    approval_id: UUID
    expected_candidate_request_hash: Sha256
    expected_binding_snapshot_sha256: Sha256
    expected_pull_request_record_id: UUID


class ReleaseCandidateReconcileResult(StrictWorkflowModel):
    """候选发布纯数据库 reconcile 的可审计终态结果。"""

    schema_version: Literal[
        "m7.release-candidate-reconcile.result.v1"
    ] = "m7.release-candidate-reconcile.result.v1"
    outcome: Literal["valid", "stale", "terminal_noop"]
    candidate_status: CandidateStatus
    approval_status: ApprovalStatus
    pull_request_record_id: UUID
    binding_snapshot_sha256: Sha256
    checked_at: datetime

    @field_validator("checked_at")
    @classmethod
    def validate_utc_checked_at(cls, value: datetime) -> datetime:
        """要求 result 使用带时区且 UTC offset 为零的数据库时间。"""

        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("checked_at 必须是 UTC date-time。")
        return value

    @model_validator(mode="after")
    def validate_outcome_status_pair(
        self,
    ) -> "ReleaseCandidateReconcileResult":
        """避免 outcome 与 Candidate/Approval 历史组合相互矛盾。"""

        pair = (self.candidate_status, self.approval_status)
        valid_pairs = {
            ("pending_approval", "pending"),
            ("approved", "approved"),
        }
        stale_pairs = {
            ("stale", "expired"),
            ("stale", "approved"),
            ("stale", "cancelled"),
        }
        terminal_pairs = {
            ("rejected", "rejected"),
            ("published", "approved"),
            ("stale", "expired"),
            ("stale", "approved"),
            ("stale", "cancelled"),
            ("cancelled", "expired"),
            ("cancelled", "approved"),
            ("cancelled", "cancelled"),
        }
        allowed = {
            "valid": valid_pairs,
            "stale": stale_pairs,
            "terminal_noop": terminal_pairs,
        }[self.outcome]
        if pair not in allowed:
            raise ValueError("outcome 与 Candidate/Approval 状态组合不一致。")
        return self


class WorkflowJobEventPayload(StrictWorkflowModel):
    """Workflow Engine 生命周期事件的公共低敏字段。"""

    workflow_job_id: UUID
    job_type: Literal["release_candidate_reconcile"]
    resource_type: Literal["release_candidate"]
    resource_id: UUID
    status: Literal[
        "pending",
        "claimed",
        "running",
        "succeeded",
        "failed",
        "cancel_requested",
        "cancelled",
        "recovery_required",
    ]
    attempt: int = Field(ge=0)
    max_attempts: int = Field(ge=1)
    error_code: str | None = Field(default=None, max_length=160)
