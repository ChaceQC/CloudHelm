"""Synthetic operation metadata/closure receipts; no executor or process is simulated."""

import hashlib
from datetime import UTC

from sqlalchemy import func, select

from database.uow import UnitOfWork
from modules.collaboration.operation_facts import register_operation_observation
from modules.collaboration.records import read_registered_reference
from packages.contracts.p0.engineering_contracts import EngineeringRef, EvidenceRecord
from packages.contracts.p1.task_facts import (
    EvidenceMetadata, OperationIntentMetadata, OperationObservation, SourceMetadata,
    operation_assertion_digest, operation_scope_digest,
)
from packages.contracts.p1.task_internal import RegisterTaskWriteIntentRequest
from scripts.p1.task_completion_fixture import SUPPORT_SCOPE
from scripts.p1.task_fixture import FixtureSources
from scripts.p1.task_probe import PROJECT, require


def operation_reference(probe, seeded, *, label="write"):
    with UnitOfWork(probe.pools.control) as uow:
        sources = FixtureSources(uow, PROJECT, probe.token)
        metadata = OperationIntentMetadata(
            owner_kind="task", owner_id=seeded.task_id,
            request_digest="sha256:" + hashlib.sha256(("synthetic-intent-" + seeded.task_id + label).encode()).hexdigest(),
            attempt_id=sources.identity("attempt-" + seeded.task_id), step_ids=("p11-synthetic-step",),
            executor_id=sources.identity("executor"), executor_generation=1, input_set_ref=seeded.input_ref,
        )
        return sources.add("operation-" + seeded.task_id + "-" + label, metadata, domain="execution")


def write_request(probe, seeded, reference):
    task = probe.row(seeded.task_id)
    return RegisterTaskWriteIntentRequest(
        expected_version=task["version"], expected_control_revision=task["control_revision"],
        expected_input_validity_revision=task["input_validity_revision"], operation_ref=reference,
    )


def register_unknown_write(probe, seeded):
    reference = operation_reference(probe, seeded)
    reply = probe.app.register_write_intent(probe.actor(), seeded.task_id, write_request(probe, seeded, reference),
                                            idempotency_key=probe.key("register-write"))
    require(reply.status_code == 200 and reply.body.outcome == "write_intent_registered", "task_write_registration_failed")
    return reference


def close_unstarted(probe, seeded, operation_ref):
    task = probe.row(seeded.task_id)
    with UnitOfWork(probe.pools.control) as uow:
        sources = FixtureSources(uow, PROJECT, probe.token)
        intent = read_registered_reference(uow.connection, PROJECT, operation_ref).metadata
        name = "closure-" + seeded.task_id
        # The temporary reference is never registered. The assertion digest
        # deliberately excludes its evidence refs, then the actual proof is bound.
        temporary = EngineeringRef(kind="evidence", object_id=sources.identity(name), revision="fixture-r1",
                                   digest="sha256:" + "0" * 64, digest_algorithm="sha256")
        receipt = OperationObservation(
            observation_id=sources.identity("observation-" + seeded.task_id), project_id=PROJECT,
            task_id=seeded.task_id, source_id=sources._source("execution"),
            source_record_id=sources.identity("record-" + name), operation_ref=operation_ref,
            attempt_id=intent.attempt_id, step_ids=intent.step_ids, executor_id=intent.executor_id,
            executor_generation=intent.executor_generation, control_revision=task["control_revision"],
            input_set_ref=seeded.input_ref, resulting_input_set_ref=seeded.input_ref,
            effect_scope_digest=operation_scope_digest(operation_ref, intent.attempt_id, intent.step_ids,
                                                       intent.executor_id, intent.executor_generation, intent.input_set_ref),
            closure="closed_unstarted", effects_recorded=True, evidence_ref=temporary,
            observed_at_utc=uow.connection.scalar(select(func.clock_timestamp())).astimezone(UTC),
        )
        evidence = EvidenceRecord(
            evidence_id=temporary.object_id, subject_ref=operation_ref, input_set_ref=seeded.input_ref,
            method_ref=sources.method_ref, environment_ref=seeded.environment_ref, result="passed",
            observed_at=receipt.observed_at_utc, support_scope=(SUPPORT_SCOPE,),
        )
        reference = sources.add(name, EvidenceMetadata(evidence=evidence, role="operation_closure",
                                                       fact_digest=operation_assertion_digest(receipt)), domain="execution")
        receipt = OperationObservation.model_validate({**receipt.model_dump(), "evidence_ref": reference})
        register_operation_observation(uow.connection, receipt, authorization=sources.archive.envelope)
        return receipt


def redeliver_closure(probe, receipt):
    with UnitOfWork(probe.pools.control) as uow:
        sources = FixtureSources(uow, PROJECT, probe.token)
        register_operation_observation(uow.connection, receipt, authorization=sources.archive.envelope)


def changed_source(probe):
    with UnitOfWork(probe.pools.control) as uow:
        sources = FixtureSources(uow, PROJECT, probe.token)
        return sources.add("changed-source", SourceMetadata(commit="2" * 40), domain="projects")
