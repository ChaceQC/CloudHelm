"""Fixed P0 Task contract cases; no persistence, real execution or human acceptance."""

import json
import sys
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from packages.contracts.p0.decision_common import Contract
from packages.contracts.p0.engineering_contracts import EngineeringRef
from packages.contracts.p0.identity_contracts import (
    CommandEnvelope, CommandIntent, IdempotencyRecord, Principal, ResourceScope, request_digest,
)
from packages.contracts.p0.task_control_contracts import (
    CancellationIntent, CancellationTarget, CompletionBasis, CurrentTaskAccess,
    HumanTestCompletionFact, OperationClosureFact, P0TaskControlContracts, TaskCompletionReport,
    TaskControlCommand, TaskControlFacts, TaskControlRequest, cancellation_readiness,
    cancellation_route, check_ordinary_progress_closure, decide_completion,
)

FIXTURE_DIGEST = "sha256:" + "a" * 64  # Reference shape only, not attested content.
TASK_ID = "task-fixture"
HUMAN = Principal(kind="human", subject_id="human-fixture")
SCOPE = ResourceScope(project_id="project-fixture", resource_kind="task", resource_id=TASK_ID)


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise AssertionError(code)


def _reject(action: Callable[[], object], code: str) -> None:
    try:
        action()
    except ValueError as error:
        if code in str(error):
            return
        raise AssertionError(f"unexpected rejection: {code}") from error
    raise AssertionError(f"expected rejection: {code}")


def _change(value: Contract, **updates):
    return type(value).model_validate({**value.model_dump(), **updates})


def _ref(kind: str, name: str | None = None) -> EngineeringRef:
    return EngineeringRef(kind=kind, object_id=name or f"{kind}-fixture",
                          revision="b" * 40 if kind == "source" else "r1",
                          authority="synthetic-hub", digest=FIXTURE_DIGEST, digest_algorithm="sha256")


def _command(*, key: str = "key-fixture", command_id: str = "command-fixture", control: int = 5,
             action: str = "complete_task") -> TaskControlCommand:
    request = TaskControlRequest(action=action, expected_control_revision=control,
                                 expected_input_validity_revision=7 if action == "complete_task" else None,
                                 cancel_reason="user_requested" if action == "cancel_task" else None)
    intent = CommandIntent(request_schema_revision="p0-task-control-r1", caller=HUMAN, scope=SCOPE,
                           target=SCOPE, action="task.command" if action == "complete_task" else "task.cancel",
                           expected_resource_revision=3)
    envelope = CommandEnvelope(**intent.model_dump(), command_id=command_id, idempotency_key=key,
                               request_digest=request_digest(intent, request))
    return TaskControlCommand(envelope=envelope, request=request)


def _access(command: TaskControlCommand) -> CurrentTaskAccess:
    return CurrentTaskAccess(command_id=command.envelope.command_id, caller=HUMAN, scope=SCOPE,
                             task_id=TASK_ID, action=command.request.action,
                             authorization_decision_id="synthetic-current-decision", permission_revision=2,
                             command_allowed=True, report_read_allowed=True)


def _basis(human: HumanTestCompletionFact | None = None) -> CompletionBasis:
    return CompletionBasis(requirement_ref=_ref("requirement"), acceptance_assets_ref=_ref("acceptance_assets"),
                           final_candidate_ref=_ref("candidate"), integrated_source_ref=_ref("source"),
                           input_set_ref=_ref("input_set"), input_validity_revision=7,
                           required_check_ids=("fixed-acceptance",), required_evidence_refs=(_ref("evidence"),),
                           human_test=human or HumanTestCompletionFact(policy_ref=_ref("policy"), policy_current=True))


def _facts() -> TaskControlFacts:
    return TaskControlFacts(task_id=TASK_ID, state="active", version=3, control_revision=5,
                            input_validity_revision=7, basis=_basis(), input_current=True,
                            required_work_items_accepted=True, required_acceptance_satisfied=True,
                            evidence_current=True, required_waits_satisfied=True, operation_set_current=True)


def _report(command: TaskControlCommand) -> TaskCompletionReport:
    return TaskCompletionReport(report_id="report-fixture", task_id=TASK_ID, completion_command=command,
                                committed_version=4, committed_control_revision=6,
                                committed_at_utc="2026-10-14T00:00:00Z", basis=_basis())


def _intent() -> CancellationIntent:
    return CancellationIntent(command_id="cancel-command", cancel_requested_at="2026-10-14T00:01:00Z",
                              cancel_requested_by=HUMAN, cancel_reason="user_requested", control_revision=6)


def _completion_order_checks() -> dict[str, bool]:
    command = _command()
    report = _report(command)
    completed = _change(_facts(), state="completed", version=4, control_revision=6,
                        completion_report=report, ordinary_progress_closed=True,
                        basis=None, input_current=False, required_acceptance_satisfied=False)
    record = IdempotencyRecord(caller=HUMAN, scope=SCOPE, idempotency_key=command.envelope.idempotency_key,
                               command_id=command.envelope.command_id, request_digest=command.envelope.request_digest,
                               report_id=report.report_id, result_ref="persisted-original-result")
    replay = decide_completion(command, completed, _access(command), record)
    _require(replay.outcome == "replay" and replay.report == report
             and replay.original_result_ref == record.result_ref, "same-key-replay-must-not-revalidate")
    denied = decide_completion(command, completed, _change(_access(command), command_allowed=False), record)
    _require(denied.code == "permission_denied" and denied.report is None, "revoked-access-leaked-report")
    denied_read = decide_completion(command, completed, _change(_access(command), report_read_allowed=False), record)
    _require(denied_read.code == "permission_denied", "report-access-must-be-current")
    changed = _command(control=4)
    _require(decide_completion(changed, completed, _access(changed), record).code == "idempotency_digest_conflict",
             "digest-conflict-must-precede-completed")
    new_key = _command(key="new-key", command_id="new-command")
    fixed = decide_completion(new_key, completed, _access(new_key))
    _require(fixed.outcome == "already_completed" and fixed.report == report, "new-key-must-return-original-report")
    legacy = _change(completed, completion_report=None)
    _require(decide_completion(new_key, legacy, _access(new_key)).code == "legacy_completion_report_missing",
             "legacy-report-must-not-be-invented")
    rejected_record = _change(record, report_id=None, result_ref="persisted-original-rejection")
    old_rejection = decide_completion(command, completed, _access(command), rejected_record)
    _require(old_rejection.outcome == "replay" and old_rejection.report is None
             and old_rejection.original_result_ref == rejected_record.result_ref, "rejection-replay-must-stay-original")
    _reject(lambda: _change(report, committed_version=5), "completion_report_revision_mismatch")
    _reject(lambda: setattr(report, "committed_version", 5), "frozen_instance")
    return {"access_before_replay": True, "same_key_original_result_before_versions": True,
            "different_digest_rejected_before_completed": True, "new_key_completed_returns_fixed_report": True,
            "legacy_missing_report_not_fabricated": True, "report_immutable_and_one_revision_step": True}


def _completion_gate_checks() -> dict[str, bool]:
    command, facts = _command(), _facts()
    access = _access(command)
    for state in ("active", "waiting_input"):
        _require(decide_completion(command, _change(facts, state=state), access).outcome == "completion_eligible",
                 "eligible-source-rejected")
    for state in ("draft", "paused", "failed", "cancelled"):
        _require(decide_completion(command, _change(facts, state=state), access).code == "completion_source_not_allowed",
                 "forbidden-source-accepted")
    for updates, code in (({"version": 4}, "resource_revision_conflict"),
                          ({"control_revision": 6}, "control_revision_conflict"),
                          ({"input_validity_revision": 8}, "input_validity_revision_conflict"),
                          ({"input_current": False}, "input_not_current"),
                          ({"evidence_current": False}, "evidence_not_applicable"),
                          ({"state": "waiting_input", "required_waits_satisfied": False}, "required_waits_unresolved")):
        _require(decide_completion(command, _change(facts, **updates), access).code == code, code)
    operation = OperationClosureFact(operation_ref=_ref("operation"), owner_kind="task", owner_id=TASK_ID,
                                     affects_completion=True)
    for updates in ({}, {"closure": "running"}, {"closure": "stop_requested"}, {"closure": "closed_unstarted"},
                    {"closure": "safely_stopped", "closure_evidence_ref": _ref("evidence")}):
        pending = _change(facts, operations=(_change(operation, **updates),))
        decision = decide_completion(command, pending, access)
        _require(decision.code == "writes_unsettled" and decision.blocking_operation_ids == (operation.operation_ref.object_id,),
                 "unsettled-write-or-missing-proof-accepted")
    closed = _change(operation, closure="closed_unstarted", closure_evidence_ref=_ref("evidence"), effects_recorded=True)
    _require(decide_completion(command, _change(facts, operations=(closed,)), access).outcome == "completion_eligible",
             "confirmed-closure-rejected")
    shared = _change(operation, owner_kind="shared", owner_id="shared-owner")
    _require(decide_completion(command, _change(facts, operations=(shared,)), access).code == "writes_unsettled",
             "relevant-shared-write-must-still-block-completion")
    costs = _change(facts, unknown_model_usage_present=True)
    _require(decide_completion(command, costs, access).outcome == "completion_eligible", "cost-unknown-is-not-write-unknown")
    cancelled = _change(facts, cancellation=_intent(), control_revision=6)
    _require(decide_completion(command, cancelled, access).code == "task_progress_closed", "cancel-intent-must-close-completion")
    for closed_facts in (cancelled, _change(facts, state="completed"), _change(facts, state="cancelled")):
        _reject(lambda value=closed_facts: check_ordinary_progress_closure(value, 5), "task_progress_closed")
    return {"completion_sources_enforced": True, "current_versions_inputs_and_waits_enforced": True,
            "unknown_stop_request_and_missing_closure_proof_block_writes": True,
            "relevant_shared_write_blocks_without_stop_authority": True,
            "unknown_model_usage_is_separate": True, "completed_or_cancel_requested_closes_ordinary_progress": True}


def _human_and_cancel_checks() -> dict[str, bool]:
    command, facts = _command(), _facts()
    passed = HumanTestCompletionFact(policy_ref=_ref("policy"), is_completion_gate=True, policy_current=True,
                                     session_id="human-round-1", conclusion="passed", concluded_by=HUMAN,
                                     concluded_at_utc="2026-10-14T00:00:00Z", conclusion_evidence_ref=_ref("evidence"),
                                     authorized_human_conclusion=True, applicable_to_final_input=True)
    skipped = _change(passed, conclusion="skipped", skip_allowed=True, skip_reason="human_explicit_skip")
    for conclusion in (passed, skipped):
        projected = _change(facts, basis=_basis(conclusion))
        _require(decide_completion(command, projected, _access(command)).outcome == "completion_eligible",
                 "lawful-human-conclusion-rejected")
    skipped_report = _change(_report(command), basis=_basis(skipped))
    _require(skipped_report.basis.human_test.conclusion == "skipped", "skip-was-converted-to-passed")
    forbidden = _change(facts, basis=_basis(_change(skipped, skip_allowed=False)))
    _require(decide_completion(command, forbidden, _access(command)).code == "human_skip_not_authorized_by_policy",
             "policy-forbidden-skip-accepted")
    stale_optional = _change(facts, basis=_basis(_change(facts.basis.human_test, policy_current=False)))
    _require(decide_completion(command, stale_optional, _access(command)).code == "human_test_not_current",
             "stale-policy-cannot-remove-human-gate")
    no_conclusion = HumanTestCompletionFact(policy_ref=_ref("policy"), is_completion_gate=True,
                                            policy_current=True, applicable_to_final_input=True)
    _require(decide_completion(command, _change(facts, basis=_basis(no_conclusion)), _access(command)).code
             == "human_test_gate_unresolved", "closed-wait-was-converted-to-passed")
    agent = Principal(kind="agent", subject_id="agent-fixture", delegator_id=HUMAN.subject_id)
    _reject(lambda: _change(passed, concluded_by=agent), "authorized_human_conclusion_required")
    cancelling = _change(facts, cancellation=_intent(), control_revision=6, ordinary_progress_closed=True,
                         run_history_saved_and_fenced=True, unknown_model_usage_present=True)
    unknown = OperationClosureFact(operation_ref=_ref("operation"), owner_kind="task", owner_id=TASK_ID)
    _require(cancellation_readiness(_change(cancelling, operations=(unknown,))).code
             == "cancellation_physical_execution_unsettled", "owned-physical-unknown-cancelled")
    shared = _change(unknown, owner_kind="shared", owner_id="shared-owner")
    _require(cancellation_readiness(_change(cancelling, operations=(shared,))).outcome == "cancellation_eligible",
             "shared-execution-or-unknown-cost-blocked-unrelated-cancellation")
    _require(cancellation_readiness(_change(cancelling, run_history_saved_and_fenced=False)).code
             == "cancel_progress_not_fenced", "unfenced-run-cancelled")
    for kind in ("human_test", "release", "deployment", "incident", "cleanup"):
        target = CancellationTarget(object_kind=kind, object_id=f"{kind}-fixture", owner_kind="independent", owner_id="other")
        _require(cancellation_route(TASK_ID, target) == "independent_control", "independent-object-cancellation-propagated")
    for kind, owner, owner_id, route in (("operation", "task", TASK_ID, "stop_or_reconcile"),
                                        ("operation", "shared", "other", "detach_subscription"),
                                        ("work_item", "task", "other-task", "no_propagation"),
                                        ("wait_condition", "task", TASK_ID, "close_continuation"),
                                        ("reservation", "task", TASK_ID, "retain_until_physical_release")):
        target = CancellationTarget(object_kind=kind, object_id=f"{kind}-fixture", owner_kind=owner, owner_id=owner_id)
        _require(cancellation_route(TASK_ID, target) == route, "cancellation-ownership-route-mismatch")
    _reject(lambda: CancellationTarget(object_kind="work_item", object_id="work", owner_kind="shared", owner_id="other"),
            "shared_reference_kind_invalid")
    _require(_command(action="cancel_task").request.cancel_reason == "user_requested", "cancel-command-shape-invalid")
    return {"human_pass_and_authorized_skip_distinct": True, "wait_closure_does_not_supply_human_conclusion": True,
            "agent_cannot_supply_human_conclusion": True, "cancellation_waits_for_owned_physical_facts": True,
            "cancellation_preserves_shared_independent_and_resource_boundaries": True}


def run_checks() -> dict[str, bool]:
    checks = {**_completion_order_checks(), **_completion_gate_checks(), **_human_and_cancel_checks()}
    _require("TaskCompletionReport" in P0TaskControlContracts.model_json_schema()["$defs"], "schema-wrapper-missing")
    return {**checks, "aggregate_schema_exportable": True}


if __name__ == "__main__":
    print(json.dumps({"check": "p0.3-task-control-contracts", "scope": "types-and-pure-decisions-only",
                      "checks": run_checks()}, ensure_ascii=False, sort_keys=True))
