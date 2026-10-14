"""Bounded Task query and durable command results for the P1 API."""

from typing import Literal

from pydantic import Field

from packages.contracts.p0.decision_common import Contract, Identifier, Revision
from packages.contracts.p0.engineering_contracts import EngineeringRef
from packages.contracts.p0.task_control_contracts import CancellationIntent, TaskState
from packages.contracts.p1.task_requests import TaskDeclaration

WorkItemState = Literal[
    "pending", "ready", "running", "blocked", "submitted", "accepted", "failed", "cancelled",
]


class TaskBlocker(Contract):
    code: Identifier
    object_kind: Identifier = "task"
    object_id: Identifier | None = None


class WorkItemView(Contract):
    work_item_id: Identifier
    revision: Revision
    state: WorkItemState
    required: bool
    goal: str = Field(min_length=1, max_length=4096)
    blocked_reason: Identifier | None = None
    accepted_input_set_ref: EngineeringRef | None = None


class TaskView(Contract):
    task_id: Identifier
    project_id: Identifier
    state: TaskState
    version: Revision
    control_revision: Revision
    input_validity_revision: Revision
    declaration: TaskDeclaration
    cancellation: CancellationIntent | None = None
    completion_report_id: Identifier | None = None
    input_status: Literal["valid", "needs_review", "superseded"]
    ordinary_progress_closed: bool
    work_items: tuple[WorkItemView, ...] = Field(default=(), max_length=128)
    blockers: tuple[TaskBlocker, ...] = Field(default=(), max_length=128)


class TaskCommandResult(Contract):
    """Persist exactly this result; replays do not replace it with a newer Task view."""

    command_id: Identifier
    task_id: Identifier
    outcome: Literal[
        "created", "started", "completed", "cancellation_requested", "cancelled",
        "already_completed", "already_cancelled", "reconciled", "rejected", "blocked",
        "input_invalidated", "impact_archived", "write_intent_registered",
        "reconciliation_requested",
    ]
    code: Identifier
    state: TaskState
    version: Revision
    control_revision: Revision
    input_validity_revision: Revision
    completion_report_id: Identifier | None = None
    original_command_id: Identifier | None = None
    workflow_id: Identifier | None = None
    control_purpose: Literal["completion", "cancellation"] | None = None
    operation_id: Identifier | None = None
    blockers: tuple[TaskBlocker, ...] = Field(default=(), max_length=128)


class TaskCreateRejection(Contract):
    """A rejected declaration has no Task identity, state or business version."""

    command_id: Identifier
    project_id: Identifier
    outcome: Literal["rejected"] = "rejected"
    code: Identifier
    blockers: tuple[TaskBlocker, ...] = Field(default=(), max_length=128)


class TaskHttpResult(Contract):
    status_code: Literal[200, 201, 202, 403, 404, 409, 422]
    body: TaskCommandResult | TaskCreateRejection
