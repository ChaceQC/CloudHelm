"""Task-facing Agent intent and bounded, read-only runtime projections."""

from typing import Annotated, Literal

from pydantic import Field, JsonValue

from packages.contracts.p0.decision_common import Contract, Identifier, Revision
from packages.contracts.p0.engineering_contracts import EngineeringRef, UtcTimestamp
from packages.contracts.p0.task_control_contracts import TaskState
from packages.contracts.p1.task_requests import BudgetAmount, PublicGoal, StartTaskRequest
from packages.contracts.p1.task_results import WorkItemState

from .work_item_capabilities import WorkItemCapabilities


TaskAgentAmount = Annotated[
    str, Field(pattern=r"^(0|[1-9][0-9]{0,15})(\.[0-9]{1,12})?$", max_length=29),
]
# Aggregate up to 8 sessions x 8 runs x 12 requests at storage precision.
TaskAgentTotalAmount = Annotated[
    str, Field(pattern=r"^(0|[1-9][0-9]{0,18})(\.[0-9]{1,12})?$", max_length=32),
]


class StartTaskAgentRequest(StartTaskRequest):
    work_item_id: Identifier
    session_id: Identifier | None = None
    expected_session_version: Revision = 0
    max_requests: int = Field(default=3, strict=True, ge=1, le=12)
    max_duration_seconds: int = Field(default=60, strict=True, ge=1, le=86400)
    max_output_tokens: int = Field(default=4096, strict=True, ge=1, le=128000)
    per_request_cost_upper_bound: BudgetAmount | None = None


class TaskAgentCommandResult(Contract):
    command_id: Identifier
    task_id: Identifier
    code: Identifier
    state: Literal["queued", "rejected"]
    session_id: Identifier | None = None
    run_id: Identifier | None = None
    workflow_id: Identifier | None = None


class TaskAgentDiff(Contract):
    workspace_id: Identifier | None
    work_item_id: Identifier
    files: tuple[dict[str, JsonValue], ...] = Field(max_length=16)
    truncated: bool


class TaskAgentWorkItemSummary(Contract):
    work_item_id: Identifier
    revision: Revision
    state: WorkItemState
    required: bool
    goal: PublicGoal
    owner_session_id: Identifier | None
    blocked_reason: Identifier | None
    capabilities: WorkItemCapabilities


class TaskAgentPolicySummary(Contract):
    """Public limits from the latest Run policy, without model configuration."""

    role: Literal["coordinator", "developer", "verifier", "reviewer", "operator"]
    max_requests: int = Field(strict=True, ge=1, le=12)
    max_duration_seconds: int = Field(strict=True, ge=1, le=86400)
    max_output_tokens: int = Field(strict=True, ge=1, le=1000000)
    per_request_cost_upper_bound: TaskAgentAmount


class TaskAgentRunSummary(Contract):
    run_id: Identifier
    work_item_id: Identifier
    work_item_revision: Revision
    state: Literal["queued", "running", "succeeded", "failed", "interrupted"]
    request_count: int = Field(strict=True, ge=0, le=12)
    reserved_cost: TaskAgentAmount
    created_at: UtcTimestamp
    started_at: UtcTimestamp | None
    deadline_at: UtcTimestamp | None
    tool_protocol_revision: Literal["dispatch-r1", "named-r1", "named-r2"]
    reason_code: Identifier | None


class TaskAgentSessionSummary(Contract):
    session_id: Identifier
    version: Revision
    state: Literal["idle", "queued", "running", "paused", "failed", "completed"]
    work_item_id: Identifier | None
    policy: TaskAgentPolicySummary | None
    runs: tuple[TaskAgentRunSummary, ...] = Field(max_length=8)


class TaskAgentWait(Contract):
    wait_condition_id: Identifier
    from_run_id: Identifier
    tool_call_id: Identifier
    operation_id: Identifier
    state: Literal["waiting", "satisfied", "closed"]
    continuation_run_id: Identifier | None
    required_for_completion: bool


class TaskAgentFeeSummary(Contract):
    """Latest usage calculations for the listed Runs, excluding supplier bills."""

    scope: Literal["listed_runs"]
    currency: Literal["USD", "CNY"]
    known_calculated_cost: TaskAgentTotalAmount | None = Field(
        description="Sum of known calculated amounts; null when none are known.",
    )
    unknown_request_count: int = Field(strict=True, ge=0, le=768)
    unknown_reserved_cost: TaskAgentTotalAmount = Field(
        description="Total reserved cost for requests whose calculated cost is unknown.",
    )


class TaskAgentSummary(Contract):
    """Current Task facts, visible WorkItems, and bounded Agent activity."""

    task_id: Identifier
    project_id: Identifier
    state: TaskState
    version: Revision
    control_revision: Revision
    input_validity_revision: Revision
    input_status: Literal["valid", "needs_review", "superseded"]
    ordinary_progress_closed: bool
    work_items: tuple[TaskAgentWorkItemSummary, ...] = Field(max_length=32)
    sessions: tuple[TaskAgentSessionSummary, ...] = Field(max_length=8)
    waits: tuple[TaskAgentWait, ...] = Field(max_length=8)
    fees: TaskAgentFeeSummary
    truncated: bool


class TaskAgentToolEvent(Contract):
    kind: Literal["call", "return", "retry"]
    tool_call_id: Identifier
    tool_name: Identifier
    call_run_id: Identifier = Field(description="Run containing the original tool call.")
    operation_id: Identifier | None
    summary: Annotated[str, Field(max_length=512)] | None = Field(
        description="Redacted display text, without tool arguments or raw tool results.",
    )


class TaskAgentRequestSummary(Contract):
    request_record_id: Identifier
    state: Literal["observed", "unknown"] = Field(
        description="Whether a supplier observation exists; calculated cost may still be unknown.",
    )
    reserved_cost: TaskAgentAmount
    calculated_cost: TaskAgentAmount | None
    billed_amount: TaskAgentAmount | None
    billed_currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")] | None
    observation_revision: Annotated[Revision, Field(ge=1)] | None
    reconciliation_evidence_ref: Identifier | None


class TaskAgentRunDetail(TaskAgentRunSummary):
    """One Run's registered references and bounded display timeline."""

    task_id: Identifier
    session_id: Identifier
    outcome: Literal["tool_requests", "waiting_condition", "submitted", "continue_required"] | None
    input_set_ref: EngineeringRef
    tool_timeline: tuple[TaskAgentToolEvent, ...] = Field(max_length=16)
    requests: tuple[TaskAgentRequestSummary, ...] = Field(max_length=12)
    waits: tuple[TaskAgentWait, ...] = Field(max_length=8)
    operation_ids: tuple[Identifier, ...] = Field(max_length=24)
    evidence_refs: tuple[EngineeringRef, ...] = Field(
        max_length=8, description="Registered delivery references from the Run's turn result.",
    )
    verification_report_id: Identifier | None
    truncated: bool
