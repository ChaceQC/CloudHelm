"""P0 Task decision projections; no persistence, execution or human attestation."""

from typing import Literal

from pydantic import Field, StrictBool, model_validator

from packages.contracts.p0.decision_common import Contract, Identifier, Revision
from packages.contracts.p0.engineering_contracts import EngineeringRef, UtcTimestamp, expect_kind
from packages.contracts.p0.identity_contracts import (
    CommandEnvelope, IdempotencyRecord, Principal, ResourceScope, request_digest,
)

TaskState = Literal["draft", "active", "paused", "waiting_input", "completed", "failed", "cancelled"]
TaskAction = Literal["complete_task", "cancel_task"]


class TaskControlRequest(Contract):
    action: TaskAction
    expected_control_revision: Revision
    expected_input_validity_revision: Revision | None = None
    cancel_reason: Identifier | None = None

    @model_validator(mode="after")
    def check_action_fields(self):
        if self.action == "complete_task":
            if self.expected_input_validity_revision is None or self.cancel_reason is not None:
                raise ValueError("completion_request_fields_invalid")
        elif self.cancel_reason is None or self.expected_input_validity_revision is not None:
            raise ValueError("cancellation_request_fields_invalid")
        return self


class TaskControlCommand(Contract):
    envelope: CommandEnvelope
    request: TaskControlRequest

    @model_validator(mode="after")
    def check_binding(self):
        action = "task.command" if self.request.action == "complete_task" else "task.cancel"
        if self.envelope.target.resource_kind != "task" or self.envelope.action != action:
            raise ValueError("task_command_binding_mismatch")
        if self.envelope.request_schema_revision != "p0-task-control-r1":
            raise ValueError("task_request_schema_unsupported")
        if self.envelope.request_digest != request_digest(self.envelope, self.request):
            raise ValueError("request_digest_mismatch")
        return self


class CurrentTaskAccess(Contract):
    """Fresh identity-layer decision for this command; never client input."""

    command_id: Identifier
    caller: Principal
    scope: ResourceScope
    task_id: Identifier
    action: TaskAction
    authorization_decision_id: Identifier
    permission_revision: Revision
    command_allowed: StrictBool = False
    report_read_allowed: StrictBool = False


class HumanTestCompletionFact(Contract):
    policy_ref: EngineeringRef
    is_completion_gate: StrictBool = False
    policy_current: StrictBool = False
    skip_allowed: StrictBool = False
    session_id: Identifier | None = None
    conclusion: Literal["passed", "changes_requested", "skipped"] | None = None
    concluded_by: Principal | None = None
    concluded_at_utc: UtcTimestamp | None = None
    conclusion_evidence_ref: EngineeringRef | None = None
    authorized_human_conclusion: StrictBool = False
    applicable_to_final_input: StrictBool = False
    skip_reason: Identifier | None = None

    @model_validator(mode="after")
    def check_conclusion(self):
        expect_kind(self.policy_ref, "policy")
        fields = (self.concluded_by, self.concluded_at_utc, self.conclusion_evidence_ref)
        if self.conclusion is None:
            if any(value is not None for value in fields) or self.authorized_human_conclusion or self.skip_reason:
                raise ValueError("absent_human_conclusion_has_evidence")
        else:
            if self.session_id is None or any(value is None for value in fields):
                raise ValueError("human_conclusion_evidence_required")
            if self.concluded_by.kind != "human" or not self.authorized_human_conclusion:
                raise ValueError("authorized_human_conclusion_required")
            expect_kind(self.conclusion_evidence_ref, "evidence")
            if (self.conclusion == "skipped") != (self.skip_reason is not None):
                raise ValueError("human_skip_reason_required_only_for_skip")
        return self


class CompletionBasis(Contract):
    requirement_ref: EngineeringRef
    acceptance_assets_ref: EngineeringRef
    final_candidate_ref: EngineeringRef
    integrated_source_ref: EngineeringRef
    input_set_ref: EngineeringRef
    input_validity_revision: Revision
    required_check_ids: tuple[Identifier, ...] = Field(min_length=1, max_length=64)
    required_evidence_refs: tuple[EngineeringRef, ...] = Field(min_length=1, max_length=128)
    human_test: HumanTestCompletionFact

    @model_validator(mode="after")
    def check_references(self):
        for field, kind in (("requirement_ref", "requirement"), ("acceptance_assets_ref", "acceptance_assets"),
                            ("final_candidate_ref", "candidate"), ("integrated_source_ref", "source"),
                            ("input_set_ref", "input_set")):
            expect_kind(getattr(self, field), kind)
        for ref in self.required_evidence_refs:
            expect_kind(ref, "evidence")
        commit = self.integrated_source_ref.revision
        if len(commit) not in {40, 64} or any(char not in "0123456789abcdef" for char in commit):
            raise ValueError("full_integrated_commit_required")
        if len(set(self.required_check_ids)) != len(self.required_check_ids):
            raise ValueError("duplicate_required_check")
        return self


class TaskCompletionReport(Contract):
    report_id: Identifier
    task_id: Identifier
    completion_command: TaskControlCommand
    committed_version: Revision
    committed_control_revision: Revision
    committed_at_utc: UtcTimestamp
    basis: CompletionBasis

    @model_validator(mode="after")
    def check_committed_versions(self):
        command = self.completion_command
        if command.request.action != "complete_task" or command.envelope.target.resource_id != self.task_id:
            raise ValueError("completion_report_command_mismatch")
        if (self.committed_version != command.envelope.expected_resource_revision + 1
                or self.committed_control_revision != command.request.expected_control_revision + 1
                or self.basis.input_validity_revision != command.request.expected_input_validity_revision):
            raise ValueError("completion_report_revision_mismatch")
        if problem := _human_gate_problem(self.basis.human_test):
            raise ValueError(problem)
        return self


class OperationClosureFact(Contract):
    operation_ref: EngineeringRef
    owner_kind: Literal["task", "shared", "independent"]
    owner_id: Identifier
    affects_completion: StrictBool = False
    closure: Literal["closed_unstarted", "ended_reconciled", "safely_stopped", "running", "stop_requested", "unknown"] = "unknown"
    closure_evidence_ref: EngineeringRef | None = None
    effects_recorded: StrictBool = False

    @model_validator(mode="after")
    def check_references(self):
        expect_kind(self.operation_ref, "operation")
        if self.closure_evidence_ref is not None:
            expect_kind(self.closure_evidence_ref, "evidence")
        return self


class CancellationIntent(Contract):
    command_id: Identifier
    cancel_requested_at: UtcTimestamp
    cancel_requested_by: Principal
    cancel_reason: Identifier
    control_revision: Revision


class TaskControlFacts(Contract):
    """Complete, same-transaction domain/identity/execution projection, not Task storage."""

    task_id: Identifier
    state: TaskState
    version: Revision
    control_revision: Revision
    input_validity_revision: Revision
    completion_report: TaskCompletionReport | None = None
    cancellation: CancellationIntent | None = None
    basis: CompletionBasis | None = None
    input_current: StrictBool = False
    required_work_items_accepted: StrictBool = False
    required_acceptance_satisfied: StrictBool = False
    evidence_current: StrictBool = False
    required_waits_satisfied: StrictBool = False
    operation_set_current: StrictBool = False
    ordinary_progress_closed: StrictBool = False
    run_history_saved_and_fenced: StrictBool = False
    operations: tuple[OperationClosureFact, ...] = Field(default=(), max_length=128)
    unknown_model_usage_present: StrictBool = False

    @model_validator(mode="after")
    def check_snapshot(self):
        if self.completion_report is not None:
            if self.state != "completed" or self.completion_report.task_id != self.task_id:
                raise ValueError("completion_report_task_mismatch")
        if self.cancellation is not None and (self.cancellation.control_revision > self.control_revision or self.state == "completed"):
            raise ValueError("cancellation_snapshot_inconsistent")
        if len({op.operation_ref.object_id for op in self.operations}) != len(self.operations):
            raise ValueError("duplicate_operation_projection")
        return self


class TaskControlDecision(Contract):
    outcome: Literal["replay", "already_completed", "completion_eligible", "cancellation_eligible", "already_cancelled", "rejected", "blocked"]
    code: Identifier
    original_command_id: Identifier | None = None
    original_result_ref: Identifier | None = None
    report: TaskCompletionReport | None = None
    blocking_operation_ids: tuple[Identifier, ...] = Field(default=(), max_length=128)


class CancellationTarget(Contract):
    object_kind: Literal["task", "work_item", "session", "run", "operation", "result", "wait_condition", "reservation", "human_test", "release", "deployment", "incident", "cleanup"]
    object_id: Identifier
    owner_kind: Literal["task", "shared", "independent"]
    owner_id: Identifier

    @model_validator(mode="after")
    def check_ownership_shape(self):
        if self.object_kind in {"human_test", "release", "deployment", "incident", "cleanup"} and self.owner_kind != "independent":
            raise ValueError("independent_lifecycle_required")
        if self.owner_kind == "shared" and self.object_kind not in {"operation", "result"}:
            raise ValueError("shared_reference_kind_invalid")
        return self


class P0TaskControlContracts(Contract):
    command: TaskControlCommand
    current_access: CurrentTaskAccess
    facts: TaskControlFacts
    report: TaskCompletionReport
    decision: TaskControlDecision
    cancellation_target: CancellationTarget


def _refuse(code: str, *, blocked: bool = False, operations: tuple[str, ...] = ()) -> TaskControlDecision:
    return TaskControlDecision(outcome="blocked" if blocked else "rejected", code=code,
                               blocking_operation_ids=operations)


def _human_gate_problem(human: HumanTestCompletionFact) -> str | None:
    if not human.policy_current:
        return "human_test_not_current"
    if not human.is_completion_gate:
        return None
    if not human.applicable_to_final_input:
        return "human_test_not_current"
    if human.conclusion == "skipped" and not human.skip_allowed:
        return "human_skip_not_authorized_by_policy"
    if human.conclusion not in {"passed", "skipped"}:
        return "human_test_gate_unresolved"
    return None


def _settled(operation: OperationClosureFact) -> bool:
    return (operation.closure in {"closed_unstarted", "ended_reconciled", "safely_stopped"}
            and operation.closure_evidence_ref is not None and operation.effects_recorded)


def _prior_result(command: TaskControlCommand, facts: TaskControlFacts,
                  existing: IdempotencyRecord | None) -> TaskControlDecision | None:
    envelope = command.envelope
    report = facts.completion_report
    if existing is not None:
        if any(getattr(envelope, key) != getattr(existing, key) for key in ("caller", "scope", "idempotency_key")):
            return _refuse("idempotency_scope_mismatch")
        if envelope.request_digest != existing.request_digest:
            return _refuse("idempotency_digest_conflict")
        if existing.result_ref is None:
            return _refuse("idempotency_result_missing", blocked=True)
        if existing.report_id is not None and (report is None or report.report_id != existing.report_id):
            return _refuse("legacy_completion_report_missing", blocked=True)
        return TaskControlDecision(outcome="replay", code="original_command_result",
                                   original_command_id=existing.command_id, original_result_ref=existing.result_ref,
                                   report=report if existing.report_id is not None else None)
    if facts.state == "completed":
        if report is None:
            return _refuse("legacy_completion_report_missing", blocked=True)
        return TaskControlDecision(outcome="already_completed", code="task_already_completed",
                                   original_command_id=report.completion_command.envelope.command_id, report=report)
    return None


def decide_completion(command: TaskControlCommand, facts: TaskControlFacts, access: CurrentTaskAccess,
                      existing: IdempotencyRecord | None = None) -> TaskControlDecision:
    """Order current access, persisted dedupe and fixed completion before new-transition gates."""
    envelope, request = command.envelope, command.request
    if request.action != "complete_task":
        raise ValueError("completion_command_required")
    if (access.command_id != envelope.command_id or access.caller != envelope.caller
            or access.scope != envelope.scope or access.action != request.action
            or access.task_id != envelope.target.resource_id or facts.task_id != access.task_id):
        return _refuse("authorization_binding_mismatch")
    if not access.command_allowed or not access.report_read_allowed:
        return _refuse("permission_denied")
    if prior := _prior_result(command, facts, existing):
        return prior
    if facts.state not in {"active", "waiting_input"}:
        return _refuse("completion_source_not_allowed")
    if facts.cancellation is not None or facts.ordinary_progress_closed:
        return _refuse("task_progress_closed")
    for actual, expected, code in (
        (facts.version, envelope.expected_resource_revision, "resource_revision_conflict"),
        (facts.control_revision, request.expected_control_revision, "control_revision_conflict"),
        (facts.input_validity_revision, request.expected_input_validity_revision, "input_validity_revision_conflict"),
    ):
        if actual != expected:
            return _refuse(code)
    if max(facts.version, facts.control_revision) == 9007199254740991:
        return _refuse("revision_exhausted")
    if facts.basis is None or facts.basis.input_validity_revision != facts.input_validity_revision or not facts.input_current:
        return _refuse("input_not_current", blocked=True)
    for satisfied, code in (
        (facts.required_work_items_accepted, "required_work_items_unaccepted"),
        (facts.required_acceptance_satisfied, "required_acceptance_unsatisfied"),
        (facts.evidence_current, "evidence_not_applicable"),
        (facts.required_waits_satisfied, "required_waits_unresolved"),
        (facts.operation_set_current, "operation_set_not_current"),
    ):
        if not satisfied:
            return _refuse(code, blocked=True)
    if problem := _human_gate_problem(facts.basis.human_test):
        return _refuse(problem, blocked=True)
    unsettled = tuple(op.operation_ref.object_id for op in facts.operations if op.affects_completion and not _settled(op))
    if unsettled:
        return _refuse("writes_unsettled", blocked=True, operations=unsettled)
    return TaskControlDecision(outcome="completion_eligible", code="ready_for_atomic_completion")


def check_ordinary_progress_closure(facts: TaskControlFacts, expected_control_revision: int) -> None:
    """Closure guard only; per-action source, authorization, input and resource gates still apply."""
    if facts.state in {"completed", "cancelled"} or facts.cancellation is not None or facts.ordinary_progress_closed:
        raise ValueError("task_progress_closed")
    if facts.control_revision != expected_control_revision:
        raise ValueError("control_revision_conflict")
    if facts.state == "paused":
        raise ValueError("task_paused")


def cancellation_readiness(facts: TaskControlFacts) -> TaskControlDecision:
    """Project terminal prerequisites without requesting cancellation or releasing resources."""
    if facts.state == "completed":
        return _refuse("completion_already_fixed")
    if facts.state == "cancelled":
        return TaskControlDecision(outcome="already_cancelled", code="existing_cancellation_history")
    if facts.cancellation is None:
        return _refuse("cancel_intent_missing", blocked=True)
    if not facts.ordinary_progress_closed or not facts.run_history_saved_and_fenced:
        return _refuse("cancel_progress_not_fenced", blocked=True)
    if not facts.operation_set_current:
        return _refuse("operation_set_not_current", blocked=True)
    unsettled = tuple(op.operation_ref.object_id for op in facts.operations
                      if op.owner_kind == "task" and op.owner_id == facts.task_id and not _settled(op))
    if unsettled:
        return _refuse("cancellation_physical_execution_unsettled", blocked=True, operations=unsettled)
    return TaskControlDecision(outcome="cancellation_eligible", code="ready_for_cancelled_transaction")


def cancellation_route(task_id: str, target: CancellationTarget) -> str:
    """Route trusted ownership facts; this grants no stop or independent-object permission."""
    if target.owner_kind == "independent":
        return "independent_control"
    if target.owner_kind == "shared":
        return "detach_subscription"
    if target.owner_id != task_id:
        return "no_propagation"
    return {"task": "close_progress", "work_item": "close_progress", "session": "close_progress",
            "run": "stop_or_reconcile", "operation": "stop_or_reconcile", "result": "archive_only",
            "wait_condition": "close_continuation", "reservation": "retain_until_physical_release"}[target.object_kind]
