"""Internal Task transitions; these schemas are not exposed by the P1 HTTP API."""

from typing import Literal

from pydantic import model_validator

from packages.contracts.p0.decision_common import Contract, Identifier, Revision
from packages.contracts.p0.engineering_contracts import EngineeringRef, expect_kind
from packages.contracts.p1.task_results import TaskCommandResult


class BindInitialTaskInputRequest(Contract):
    """Bind existing registered inputs; this grants no workspace or execution access."""

    expected_version: Revision
    expected_control_revision: Revision
    expected_input_validity_revision: Revision
    input_set_ref: EngineeringRef

    @model_validator(mode="after")
    def check_input_set(self):
        expect_kind(self.input_set_ref, "input_set")
        return self


class InvalidateTaskInputRequest(Contract):
    expected_version: Revision
    expected_control_revision: Revision
    expected_input_validity_revision: Revision
    change_ref: EngineeringRef
    reason: Identifier


class RegisterTaskWriteIntentRequest(Contract):
    expected_version: Revision
    expected_control_revision: Revision
    expected_input_validity_revision: Revision
    operation_ref: EngineeringRef

    @model_validator(mode="after")
    def check_operation(self):
        expect_kind(self.operation_ref, "operation")
        return self


class TaskAdvanceRequest(Contract):
    source_command_id: Identifier
    expected_version: Revision
    expected_control_revision: Revision
    expected_input_validity_revision: Revision
    purpose: Literal["initial", "completion", "cancellation"]


class TaskChangedEvent(Contract):
    result: TaskCommandResult
    source_command_id: Identifier | None = None
    change_ref: EngineeringRef | None = None
    operation_ref: EngineeringRef | None = None
    reason: Identifier | None = None


class TaskWorkflowRecord(Contract):
    invocation: TaskAdvanceRequest
    result: TaskCommandResult
    status_code: Literal[200, 409, 422]
