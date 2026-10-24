"""Task completion eligibility and cancellation ownership projections."""

from packages.contracts.p0.engineering_contracts import EngineeringRef
from packages.contracts.p0.identity_contracts import (
    CommandEnvelope, CommandIntent, Principal, ResourceScope, request_digest,
)
from packages.contracts.p0.task_control_contracts import (
    CancellationTarget, CompletionBasis, CurrentTaskAccess, HumanTestCompletionFact,
    TaskControlCommand, TaskControlFacts, TaskControlRequest, cancellation_route, decide_completion,
)

DIGEST = "sha256:" + "a" * 64


def _ref(kind: str, revision: str = "r1") -> EngineeringRef:
    return EngineeringRef(kind=kind, object_id=kind, revision=revision, authority="hub",
                          digest=DIGEST, digest_algorithm="sha256")


def run_checks() -> dict[str, bool]:
    person = Principal(kind="human", subject_id="person")
    scope = ResourceScope(project_id="project", resource_kind="task", resource_id="task")
    request = TaskControlRequest(action="complete_task", expected_control_revision=5,
                                 expected_input_validity_revision=7)
    intent = CommandIntent(request_schema_revision="p0-task-control-r1", caller=person, scope=scope,
                           target=scope, action="task.command", expected_resource_revision=3)
    envelope = CommandEnvelope(**intent.model_dump(), command_id="command", idempotency_key="key",
                               request_digest=request_digest(intent, request))
    command = TaskControlCommand(envelope=envelope, request=request)
    access = CurrentTaskAccess(
        command_id="command", caller=person, scope=scope, task_id="task", action="complete_task",
        authorization_decision_id="decision", permission_revision=2, command_allowed=True,
        report_read_allowed=True,
    )
    basis = CompletionBasis(
        requirement_ref=_ref("requirement"), acceptance_assets_ref=_ref("acceptance_assets"),
        final_candidate_ref=_ref("candidate"), integrated_source_ref=_ref("source", "a" * 40),
        input_set_ref=_ref("input_set"), input_validity_revision=7, required_check_ids=("acceptance",),
        required_evidence_refs=(_ref("evidence"),),
        human_test=HumanTestCompletionFact(policy_ref=_ref("policy"), policy_current=True),
    )
    facts = TaskControlFacts(
        task_id="task", state="active", version=3, control_revision=5, input_validity_revision=7,
        basis=basis, input_current=True, required_work_items_accepted=True,
        required_acceptance_satisfied=True, evidence_current=True, required_waits_satisfied=True,
        operation_set_current=True,
    )
    assert decide_completion(command, facts, access).outcome == "completion_eligible"
    stale = facts.model_copy(update={"input_current": False})
    assert decide_completion(command, stale, access).code == "input_not_current"

    shared = CancellationTarget(object_kind="operation", object_id="op", owner_kind="shared", owner_id="other")
    independent = CancellationTarget(object_kind="release", object_id="release", owner_kind="independent",
                                     owner_id="release-owner")
    assert cancellation_route("task", shared) == "detach_subscription"
    assert cancellation_route("task", independent) == "independent_control"
    return {"completion_requires_current_input": True, "cancellation_respects_independent_ownership": True}
