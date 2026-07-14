"""M6 本地等价 PullRequestRecord ORM 模型。"""

from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from cloudhelm_platform_api.db.base import (
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class PullRequestRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """本地 branch、commit 和门禁产物组成的等价 PR 记录。"""

    __tablename__ = "pull_request_records"
    __table_args__ = (
        CheckConstraint(
            "provider IN ('local', 'github', 'gitea')",
            name="ck_pull_request_records_provider",
        ),
        CheckConstraint(
            "status IN ('open', 'superseded', 'closed')",
            name="ck_pull_request_records_status",
        ),
        CheckConstraint(
            "base_branch <> head_branch",
            name="ck_pull_request_records_distinct_branches",
        ),
        CheckConstraint(
            "base_commit_sha ~ '^[0-9a-f]{40}([0-9a-f]{24})?$'",
            name="ck_pull_request_records_base_commit_sha",
        ),
        CheckConstraint(
            "commit_sha ~ '^[0-9a-f]{40}([0-9a-f]{24})?$'",
            name="ck_pull_request_records_commit_sha",
        ),
        CheckConstraint(
            "jsonb_typeof(changed_files_json) = 'array'",
            name="ck_pull_request_records_changed_files_array",
        ),
        CheckConstraint(
            "jsonb_typeof(diff_stat_json) = 'object'",
            name="ck_pull_request_records_diff_stat_object",
        ),
        CheckConstraint(
            "provider <> 'local' OR url IS NULL",
            name="ck_pull_request_records_local_url",
        ),
        UniqueConstraint(
            "task_id",
            "commit_sha",
            name="uq_pull_request_records_task_commit",
        ),
        UniqueConstraint(
            "task_id",
            "idempotency_key",
            name="uq_pull_request_records_task_idempotency",
        ),
        Index(
            "ix_pull_request_records_task_status_created",
            "task_id",
            "status",
            "created_at",
        ),
        Index(
            "ix_pull_request_records_project_created",
            "project_id",
            "created_at",
        ),
    )

    task_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属任务 ID。",
    )
    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属项目 ID。",
    )
    development_plan_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("development_plans.id", ondelete="RESTRICT"),
        nullable=False,
        comment="本地开发闭环使用的已批准 DevelopmentPlan。",
    )
    created_by_agent_run_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        comment="完成 commit 或 PR record 的 AgentRun。",
    )
    branch_tool_call_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tool_calls.id", ondelete="SET NULL"),
        comment="创建本地分支的 ToolCall。",
    )
    commit_tool_call_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tool_calls.id", ondelete="SET NULL"),
        comment="创建本地提交的 ToolCall。",
    )
    provider: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="local",
        comment="PR 提供方；M6 使用 local。",
    )
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="open",
        comment="PR record 状态。",
    )
    title: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="本地等价 PR 标题。",
    )
    summary: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="本地等价 PR 摘要。",
    )
    base_branch: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="基准分支。",
    )
    head_branch: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="开发分支。",
    )
    base_commit_sha: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="基准提交 SHA。",
    )
    commit_sha: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="M6 最终本地提交 SHA。",
    )
    changed_files_json: Mapped[list[Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment="真实 changed files 数组。",
    )
    diff_stat_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="真实 diff stat 结构。",
    )
    diff_artifact_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("artifacts.id", ondelete="RESTRICT"),
        nullable=False,
        comment="patch/diff Artifact。",
    )
    test_artifact_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("artifacts.id", ondelete="RESTRICT"),
        nullable=False,
        comment="通过的 TestReport Artifact。",
    )
    review_artifact_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("artifacts.id", ondelete="RESTRICT"),
        nullable=False,
        comment="通过的 ReviewReport Artifact。",
    )
    security_artifact_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("artifacts.id", ondelete="RESTRICT"),
        nullable=False,
        comment="非阻断 SecurityReport Artifact。",
    )
    url: Mapped[str | None] = mapped_column(
        Text,
        comment="真实远端 PR URL；local provider 必须为空。",
    )
    idempotency_key: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="任务内 PR record 幂等键。",
    )
