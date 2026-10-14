"""Explicit synthetic P2-shaped records used only to test P1.1 Task control guards."""

from dataclasses import dataclass
from datetime import UTC

from sqlalchemy import func, insert, select, update

from database.uow import UnitOfWork
from modules.collaboration.records import reference_key
from modules.collaboration.tables import task_evidence_links, task_inputs, tasks, work_items
from packages.contracts.p0.engineering_contracts import EngineeringRef, EvidenceRecord, InputSet, input_set_digest
from packages.contracts.p1.task_facts import CandidateMetadata, EnvironmentMetadata, EvidenceMetadata, InputSetMetadata
from scripts.p1.task_fixture import FixtureSources
from scripts.p1.task_probe import PROJECT, require

SUPPORT_SCOPE = "p11-task-synthetic-control-only"


@dataclass(frozen=True, repr=False)
class CompletionFixture:
    task_id: str
    start_command_id: str
    input_ref: EngineeringRef
    candidate_ref: EngineeringRef
    environment_ref: EngineeringRef
    work_item_id: str


def _records(probe, started, item):
    with UnitOfWork(probe.pools.control) as uow:
        sources = FixtureSources(uow, PROJECT, probe.token)
        declaration = probe.declaration
        environment = sources.add("environment", EnvironmentMetadata(
            description="Isolated synthetic protocol environment; no real development validation.",
            support_scope=(SUPPORT_SCOPE,),
        ), domain="integration")
        refs = (declaration.requirement_ref, declaration.acceptance_assets_ref, declaration.source_ref,
                declaration.resource_scope_ref, declaration.human_test_policy_ref, sources.method_ref, environment)
        inputs = InputSet(input_set_id=sources.identity("input-" + started.task_id), references=refs, set_digest=input_set_digest(refs))
        input_ref = sources.add("input-" + started.task_id, InputSetMetadata(input_set=inputs), domain="integration")
        candidate = sources.add("candidate-" + started.task_id, CandidateMetadata(
            source_ref=declaration.source_ref, input_set_ref=input_ref,
        ), domain="integration")
        proofs = []
        for role in ("verification", "work_item_acceptance"):
            name = role + "-" + started.task_id
            evidence = EvidenceRecord(
                evidence_id=sources.identity(name), subject_ref=candidate, input_set_ref=input_ref,
                method_ref=sources.method_ref, environment_ref=environment, result="passed",
                observed_at=uow.connection.scalar(select(func.clock_timestamp())).astimezone(UTC), support_scope=(SUPPORT_SCOPE,),
            )
            metadata = EvidenceMetadata(
                evidence=evidence, role=role, check_ids=("p11-task-synthetic-required",),
                acceptance_assets_ref=declaration.acceptance_assets_ref,
                work_item_id=item["work_item_id"] if role == "work_item_acceptance" else None,
                work_item_revision=item["revision"] if role == "work_item_acceptance" else None,
            )
            proofs.append(sources.add(name, metadata, domain="integration"))
    return input_ref, candidate, environment, proofs


def stage_completion(probe, *, state="active") -> CompletionFixture:
    require(state in {"active", "waiting_input", "paused", "failed"}, "task_fixture_state_invalid")
    started = probe.start(probe.create("completion"))
    with UnitOfWork(probe.pools.control) as uow:
        item = dict(uow.connection.execute(select(work_items).where(work_items.c.task_id == started.task_id)).mappings().one())
    inputs, candidate, environment, proofs = _records(probe, started, item)
    # This is controlled future-state fixture input, never a product acceptance API.
    # Advancing both revisions fences the already queued original initial request.
    with UnitOfWork(probe.maintenance_engine) as uow:
        task = uow.connection.execute(select(tasks).where(tasks.c.task_id == started.task_id).with_for_update()).mappings().one()
        revision = task["input_validity_revision"] + 1
        uow.connection.execute(update(tasks).where(tasks.c.task_id == started.task_id).values(
            state=state, version=task["version"] + 1, input_validity_revision=revision, input_status="valid",
        ))
        input_key = reference_key(PROJECT, inputs)
        uow.connection.execute(insert(task_inputs).values(
            task_id=started.task_id, input_validity_revision=revision, input_set_key=input_key,
            source_key=reference_key(PROJECT, probe.declaration.source_ref), candidate_key=reference_key(PROJECT, candidate),
        ))
        for evidence in proofs:
            uow.connection.execute(insert(task_evidence_links).values(
                task_id=started.task_id, evidence_key=reference_key(PROJECT, evidence), input_validity_revision=revision,
                input_set_key=input_key, applicability="valid", rule_id="p11-synthetic-rule", rule_revision="fixture-r1",
                reason_code="synthetic_protocol_fixture",
            ))
        uow.connection.execute(update(work_items).where(work_items.c.work_item_id == item["work_item_id"]).values(
            state="accepted", accepted_input_set_key=input_key, acceptance_evidence_key=reference_key(PROJECT, proofs[1]),
        ))
    return CompletionFixture(started.task_id, started.command_id, inputs, candidate, environment, item["work_item_id"])
