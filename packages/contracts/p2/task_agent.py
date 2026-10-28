"""Task-facing Agent intent and bounded, read-only runtime projections."""

from typing import Literal

from pydantic import Field, JsonValue

from packages.contracts.p0.decision_common import Contract, Identifier, Revision
from packages.contracts.p1.task_requests import BudgetAmount, StartTaskRequest


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


class TaskAgentView(Contract):
    task_id: Identifier
    sessions: tuple[dict[str, JsonValue], ...] = Field(max_length=8)
    truncated: bool


class TaskAgentDiff(Contract):
    workspace_id: Identifier | None
    work_item_id: Identifier
    files: tuple[dict[str, JsonValue], ...] = Field(max_length=16)
    truncated: bool
