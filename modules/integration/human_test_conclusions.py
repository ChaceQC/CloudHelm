"""Archive a human's decision using the existing controlled fact registry."""

import rfc8785
from sqlalchemy import update

from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.records import (
    contract_digest, read_fact_source, read_registered_reference, reference_key, register_human_test_reference,
)
from modules.collaboration.tables import task_inputs, task_wait_conditions
from modules.integration.candidates import _ref
from packages.contracts.p0.engineering_contracts import EvidenceRecord
from packages.contracts.p1.task_facts import (
    EnvironmentMetadata, EvidenceMetadata, HumanConclusionMetadata, MethodMetadata, RegisteredReference,
)
from packages.contracts.p2.human_tests import HUMAN_TEST_SCHEMA


def _archive(uow, task, source_id, authorization, identity, metadata, at):
    kind = "method" if isinstance(metadata, MethodMetadata) else "environment" if isinstance(metadata, EnvironmentMetadata) else "evidence"
    reference = _ref(kind, identity, HUMAN_TEST_SCHEMA, "integration", metadata)
    record = RegisteredReference(project_id=task["project_id"], registration_id=identity,
        source_id=source_id, source_record_id=identity, reference=reference,
        metadata=metadata, observed_at_utc=at)
    register_human_test_reference(uow.connection, record, source_bytes=rfc8785.dumps(metadata.model_dump(mode="json")),
                                  authorization=authorization.envelope)
    return reference


def archive_conclusion(uow, task, session, request, authorization, view, at):
    """Product producer and human authorization are separate, auditable principals."""
    proof = read_registered_reference(uow.connection, task["project_id"], view.evidence_ref)
    source = read_fact_source(uow.connection, task["project_id"], proof.source_id)
    if source.producer_domain != "integration" or source.authority != "integration" or source.purpose != "product":
        raise TaskBoundaryError("human_test_product_source_required")
    if session.environment_ref is None:
        if request.conclusion != "skipped":
            raise TaskBoundaryError("human_test_environment_evidence_required")
        environment_ref = _archive(uow, task, source.source_id, authorization, "human-not-run-" + session.session_id,
            EnvironmentMetadata(description="Human test was not deployed or run; this is a skip decision context.",
                                support_scope=("human_test_not_run",)), at)
        support_scope = ("human_test_not_run",)
    else:
        environment = read_registered_reference(uow.connection, task["project_id"], session.environment_ref)
        if environment.metadata.record_kind != "environment" or "human_test" not in environment.metadata.support_scope:
            raise TaskBoundaryError("human_test_environment_evidence_required")
        environment_ref, support_scope = session.environment_ref, ("human_test",)
    method = _archive(uow, task, source.source_id, authorization, "human-method-" + session.session_id,
        MethodMetadata(description="Explicit conclusion by the assigned human tester for the fixed human-test session."), at)
    result = {"passed": "passed", "changes_requested": "failed", "skipped": "not_run"}[request.conclusion]
    evidence = EvidenceMetadata(evidence=EvidenceRecord(evidence_id="human-evidence-" + session.session_id,
        subject_ref=session.candidate_ref, input_set_ref=session.final_input_set_ref, method_ref=method,
        environment_ref=environment_ref, result=result, observed_at=at, support_scope=support_scope),
        role="human_test", fact_digest=contract_digest(session))
    evidence_ref = _archive(uow, task, source.source_id, authorization, evidence.evidence.evidence_id, evidence, at)
    conclusion = HumanConclusionMetadata(session_id=session.session_id, policy_ref=session.policy_ref,
        input_set_ref=session.final_input_set_ref, conclusion=request.conclusion, concluded_by=session.tester,
        concluded_at_utc=at, evidence_ref=evidence_ref,
        authorization_decision_id=authorization.envelope.decision_id, skip_reason=request.skip_reason)
    conclusion_ref = _archive(uow, task, source.source_id, authorization,
                              "human-conclusion-" + session.session_id, conclusion, at)
    if task["state"] != "completed":
        uow.connection.execute(update(task_inputs).where(task_inputs.c.task_id == task["task_id"],
            task_inputs.c.input_validity_revision == task["input_validity_revision"]).values(
            human_conclusion_key=reference_key(task["project_id"], conclusion_ref)))
    if session.wait_condition_id is not None:
        values = {"state": "satisfied" if request.conclusion in {"passed", "skipped"} else "closed"}
        if values["state"] == "satisfied":
            values["conclusion_evidence_key"] = reference_key(task["project_id"], evidence_ref)
        uow.connection.execute(update(task_wait_conditions).where(
            task_wait_conditions.c.wait_condition_id == session.wait_condition_id,
            task_wait_conditions.c.state == "waiting").values(**values))
    return conclusion, conclusion_ref
