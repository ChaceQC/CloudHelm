"""P0 runtime boundaries and execution identity continuity; no scheduler."""

from typing import Literal

from pydantic import Field, model_validator

from packages.contracts.p0.decision_common import (
    Contract, Digest, Identifier, ProtocolRevision, Revision,
)
from packages.contracts.p0.engineering_contracts import EngineeringRef, expect_kind


class RuntimeInput(Contract):
    protocol_revision: ProtocolRevision = "p0-decisions-r1"
    task_id: Identifier
    session_id: Identifier
    run_id: Identifier
    expected_session_version: Revision
    expected_task_control_revision: Revision
    expected_input_validity_revision: Revision
    context_package: EngineeringRef
    input_set: EngineeringRef
    committed_history: EngineeringRef
    pending_messages: EngineeringRef | None = None
    deferred_results: EngineeringRef | None = None

    @model_validator(mode="after")
    def check_refs(self):
        for ref, kind in (
            (self.context_package, "context"), (self.input_set, "input_set"),
            (self.committed_history, "history"), (self.pending_messages, "messages"),
            (self.deferred_results, "deferred_results"),
        ):
            if ref is not None:
                expect_kind(ref, kind)
        return self


class TurnResult(Contract):
    protocol_revision: ProtocolRevision = "p0-decisions-r1"
    run_id: Identifier
    outcome: Literal["tool_requests", "waiting_condition", "submitted", "continue_required"]
    history_delta: EngineeringRef
    request_records: tuple[Identifier, ...] = Field(default=(), max_length=12)
    tool_request_refs: tuple[EngineeringRef, ...] = Field(default=(), max_length=8)
    wait_condition_refs: tuple[EngineeringRef, ...] = Field(default=(), max_length=8)
    delivery_refs: tuple[EngineeringRef, ...] = Field(default=(), max_length=8)
    reason_code: Identifier

    @model_validator(mode="after")
    def check_refs(self):
        expect_kind(self.history_delta, "history")
        if len(set(self.request_records)) != len(self.request_records):
            raise ValueError("DUPLICATE_MODEL_REQUEST")
        for refs, kind in (
            (self.tool_request_refs, "tool_request"),
            (self.wait_condition_refs, "wait_condition"), (self.delivery_refs, "delivery"),
        ):
            for ref in refs:
                expect_kind(ref, kind)
        required = {
            "tool_requests": self.tool_request_refs,
            "waiting_condition": self.wait_condition_refs,
            "submitted": self.delivery_refs,
        }
        if self.outcome in required and not required[self.outcome]:
            raise ValueError("TURN_OUTCOME_REFERENCE_REQUIRED")
        return self


class AcceptedReceipt(Contract):
    operation_id: Identifier
    request_digest: Digest
    status: Literal["accepted"] = "accepted"
    query_ref: EngineeringRef
    wait_ref: EngineeringRef

    @model_validator(mode="after")
    def check_operation(self):
        for ref in (self.query_ref, self.wait_ref):
            expect_kind(ref, "operation")
            if ref.object_id != self.operation_id:
                raise ValueError("RECEIPT_OPERATION_MISMATCH")
        return self


class OperationWait(Contract):
    session_id: Identifier
    from_run_id: Identifier
    expected_session_version: Revision
    wait_condition_ref: EngineeringRef
    operation_ids: tuple[Identifier, ...] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def check_wait(self):
        expect_kind(self.wait_condition_ref, "wait_condition")
        if len(set(self.operation_ids)) != len(self.operation_ids):
            raise ValueError("DUPLICATE_WAIT_OPERATION")
        return self


class WorkflowBinding(Contract):
    business_kind: Literal["task", "session", "agent_run", "operation", "build_run", "deployment"]
    business_id: Identifier
    process_type: Identifier
    advance_revision: Revision
    workflow_id: Identifier


class RunContinuity(Contract):
    session_id: Identifier
    run_id: Identifier
    workflow_id: Identifier
    trigger: Literal["initial", "crash_recovery", "wait_continuation"]
    prior_session_id: Identifier | None = None
    prior_run_id: Identifier | None = None
    prior_workflow_id: Identifier | None = None

    @model_validator(mode="after")
    def check_identity(self):
        prior = (self.prior_session_id, self.prior_run_id, self.prior_workflow_id)
        if self.trigger == "initial":
            if any(value is not None for value in prior):
                raise ValueError("INITIAL_RUN_HAS_PREDECESSOR")
        else:
            if any(value is None for value in prior) or self.prior_session_id != self.session_id:
                raise ValueError("SESSION_CONTINUITY_REQUIRED")
            unchanged = (self.run_id == self.prior_run_id, self.workflow_id == self.prior_workflow_id)
            expected = self.trigger == "crash_recovery"
            if unchanged != (expected, expected):
                raise ValueError("RUN_CONTINUITY_MISMATCH")
        return self


class P0CoreContracts(Contract):
    runtime_input: RuntimeInput
    turn_result: TurnResult
    accepted_receipt: AcceptedReceipt
    operation_wait: OperationWait
    workflow_binding: WorkflowBinding
    run_continuity: RunContinuity
