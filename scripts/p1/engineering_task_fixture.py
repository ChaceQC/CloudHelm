"""Protocol-only Task facts and physical staging for P1.2 engineering gates.

The workspace/build intent is always accepted through its real application. These
records satisfy the other Task completion checks only; they are never product or
human acceptance evidence.
"""

from __future__ import annotations

import hashlib
import importlib
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC

import rfc8785
from sqlalchemy import func, insert, select, update

from database.uow import UnitOfWork
from modules.collaboration.application import TaskApplication
from modules.collaboration.facts import load_task_control_facts, read_declaration
from modules.collaboration.records import contract_digest, read_registered_reference, reference_key, register_fact_source, register_reference
from modules.collaboration.tables import task_evidence_links, task_inputs, tasks, work_items
from modules.delivery.queries import read_build_execution
from modules.delivery.receipts import verify_build_content, verify_build_observation
from modules.identity.actors import AuthoritativeResource
from modules.identity.authentication import authenticate_current
from modules.identity.authorization import authorize_current
from modules.projects.tables import projects
from modules.workspaces.file_operations import WorkspaceFileService
from packages.contracts.p0.engineering_contracts import EngineeringRef, EvidenceRecord, InputSet, input_set_digest
from packages.contracts.p1.build_records import BuildArtifactLocator
from packages.contracts.p1.task_facts import (
    CandidateMetadata, EnvironmentMetadata, EvidenceMetadata, InputSetMetadata, RegisteredReference, TaskFactSource,
)
from scripts.p1.engineering_fixture import PROJECT, require
from scripts.p1.runtime_processes import RuntimeProcessError, WorkerProcess, _process

METHOD_REVISION = "p1-2-engineering-task-control-r1"
PROTOCOL_CLASSIFICATION = "protocol_validation_input"
BUILD_WORKSPACE_BYTES = 2 * 1024**3


@dataclass(frozen=True, slots=True)
class ProtocolCompletionFixture:
    task_id: str
    input_set_ref: EngineeringRef
    candidate_ref: EngineeringRef
    environment_ref: EngineeringRef
    evidence_refs: tuple[EngineeringRef, ...]
    classification: str = PROTOCOL_CLASSIFICATION


@contextmanager
def task_control_worker_running(fixture):
    """Run the real Task workflows while leaving the engineering queue unpolled."""
    with _process(fixture, "worker", "scripts.p1.check_engineering_task_control",
                  ["--task-control-worker"], capture_stdout=True) as process:
        worker = WorkerProcess(process, fixture.baseline.installation_id)
        worker.wait_ready()
        yield worker
        if process.poll() is not None:
            raise RuntimeProcessError("task_control_worker_exited_while_expected_running")
    if process.returncode != 0:
        raise RuntimeProcessError("task_control_worker_shutdown_returned_failure")


def task_application(probe):
    with UnitOfWork(probe.pools.control) as uow:
        actor = authenticate_current(uow, probe.token)
    return actor, TaskApplication(probe.pools.normal, probe.pools.control, probe.client)


class _ProtocolArchive:
    def __init__(self, uow, probe, task_id: str, method_ref: EngineeringRef):
        self.uow = uow
        self.actor = authenticate_current(uow, probe.token)
        revision = uow.connection.scalar(select(projects.c.revision).where(projects.c.project_id == PROJECT))
        require(revision is not None, "engineering_task_protocol_project_missing")
        resource = AuthoritativeResource(PROJECT, "project", PROJECT, revision=revision)
        self.management = authorize_current(uow, self.actor, resource, "project.manage")
        self.archive = authorize_current(uow, self.actor, resource, "fact.archive")
        self.source_id = "p12-task-protocol-" + task_id[:32]
        source = TaskFactSource(
            project_id=PROJECT, source_id=self.source_id, producer_domain="integration", authority="integration",
            principal=self.actor.principal, purpose="protocol_validation", method_ref=method_ref,
        )
        register_fact_source(uow.connection, source, authorization=self.management.envelope)

    @staticmethod
    def reference(metadata, name: str) -> EngineeringRef:
        kind = metadata.record_kind
        if kind == "evidence":
            object_id = metadata.evidence.evidence_id
        elif kind == "input_set":
            object_id = metadata.input_set.input_set_id
        else:
            object_id = name
        return EngineeringRef(kind=kind, object_id=object_id, revision=METHOD_REVISION,
                              authority="integration", digest=contract_digest(metadata),
                              digest_algorithm="sha256")

    def add(self, name: str, metadata) -> EngineeringRef:
        reference = self.reference(metadata, name)
        payload = rfc8785.dumps(metadata.model_dump(mode="json"))
        suffix = hashlib.sha256((name + payload.decode("utf-8")).encode("utf-8")).hexdigest()[:32]
        record = RegisteredReference(
            project_id=PROJECT, registration_id="p12-protocol-registration-" + suffix,
            source_id=self.source_id, source_record_id="p12-protocol-record-" + suffix,
            reference=reference, metadata=metadata,
            observed_at_utc=self.uow.connection.scalar(select(func.clock_timestamp())).astimezone(UTC),
        )
        register_reference(self.uow.connection, record, source_bytes=payload,
                           authorization=self.archive.envelope)
        return reference


def _insert_evidence(probe, task_id: str, fixture: ProtocolCompletionFixture, *, work_item=None, label: str):
    """Register one passed protocol record and its current-input applicability link."""
    with UnitOfWork(probe.pools.control) as uow:
        task = uow.connection.execute(select(tasks).where(tasks.c.task_id == task_id)).mappings().one()
        row = uow.connection.execute(select(task_inputs).where(
            task_inputs.c.task_id == task_id,
            task_inputs.c.input_validity_revision == task["input_validity_revision"],
        )).mappings().one()
        read_registered_reference(uow.connection, PROJECT, fixture.input_set_ref)
        acceptance = read_registered_reference(uow.connection, PROJECT,
                                               read_declaration(uow.connection, task).acceptance_assets_ref)
        checks = acceptance.metadata.required_check_ids
        method_ref = acceptance.metadata.method_ref
        evidence_id = "p12-protocol-evidence-" + hashlib.sha256(
            f"{task_id}:{label}:{work_item['work_item_id'] if work_item else 'verification'}:{work_item['revision'] if work_item else 0}".encode("utf-8")
        ).hexdigest()[:32]
        evidence = EvidenceRecord(
            evidence_id=evidence_id, subject_ref=fixture.candidate_ref, input_set_ref=fixture.input_set_ref,
            method_ref=method_ref, environment_ref=fixture.environment_ref, result="passed",
            observed_at=uow.connection.scalar(select(func.clock_timestamp())).astimezone(UTC),
            support_scope=("p1-2-task-control-protocol-only",),
        )
        metadata = EvidenceMetadata(
            evidence=evidence, role="work_item_acceptance" if work_item else "verification",
            check_ids=checks, acceptance_assets_ref=acceptance.reference,
            work_item_id=work_item["work_item_id"] if work_item else None,
            work_item_revision=work_item["revision"] if work_item else None,
        )
        archive = _ProtocolArchive(uow, probe, task_id, method_ref)
        reference = archive.add("evidence-" + evidence_id, metadata)
        uow.connection.execute(insert(task_evidence_links).values(
            task_id=task_id, evidence_key=reference_key(PROJECT, reference),
            input_validity_revision=task["input_validity_revision"],
            input_set_key=row["input_set_key"], applicability="valid",
            rule_id=METHOD_REVISION, rule_revision=METHOD_REVISION,
            reason_code=PROTOCOL_CLASSIFICATION,
        ))
        return reference


def _accept_required_work_items(probe, task_id: str, fixture: ProtocolCompletionFixture, *, label: str):
    with UnitOfWork(probe.pools.control) as uow:
        rows = uow.connection.execute(select(work_items).where(
            work_items.c.task_id == task_id, work_items.c.required.is_(True),
        ).order_by(work_items.c.work_item_id)).mappings().all()
        revision = uow.connection.scalar(select(tasks.c.input_validity_revision).where(tasks.c.task_id == task_id))
        input_key = reference_key(PROJECT, fixture.input_set_ref)
        current = uow.connection.scalar(select(task_inputs.c.input_set_key).where(
            task_inputs.c.task_id == task_id, task_inputs.c.input_validity_revision == revision,
        ))
    require(bool(rows) and current == input_key, "engineering_task_protocol_input_not_current")
    acceptance_refs = []
    for row in rows:
        reference = _insert_evidence(probe, task_id, fixture, work_item=row, label=label)
        acceptance_refs.append((row["work_item_id"], reference))
    with UnitOfWork(probe.maintenance_engine) as uow:
        for work_item_id, reference in acceptance_refs:
            uow.connection.execute(update(work_items).where(
                work_items.c.task_id == task_id, work_items.c.work_item_id == work_item_id,
            ).values(state="accepted", accepted_input_set_key=input_key,
                     acceptance_evidence_key=reference_key(PROJECT, reference)))
    return acceptance_refs


def stage_protocol_completion(probe, task_id: str, *, label: str) -> ProtocolCompletionFixture:
    """Make all ordinary completion facts current on a separately labeled protocol InputSet."""
    with UnitOfWork(probe.pools.control) as uow:
        task = uow.connection.execute(select(tasks).where(tasks.c.task_id == task_id)).mappings().one()
        declaration = read_declaration(uow.connection, task)
        row = uow.connection.execute(select(task_inputs).where(
            task_inputs.c.task_id == task_id,
            task_inputs.c.input_validity_revision == task["input_validity_revision"],
        )).mappings().one()
        original = read_registered_reference(uow.connection, PROJECT, row["input_set_key"])
        source = read_registered_reference(uow.connection, PROJECT, row["source_key"])
        acceptance = read_registered_reference(uow.connection, PROJECT, declaration.acceptance_assets_ref)
        method_ref = acceptance.metadata.method_ref
        archive = _ProtocolArchive(uow, probe, task_id, method_ref)
        environment_metadata = EnvironmentMetadata(
            description="Fixed synthetic protocol environment; not product development evidence.",
            support_scope=("p1-2-task-control-protocol-only",),
        )
        environment_ref = archive.add("environment-" + label, environment_metadata)
        input_set = InputSet(
            input_set_id="p12-task-input-" + hashlib.sha256((task_id + label).encode("utf-8")).hexdigest()[:32],
            references=(*original.metadata.input_set.references, environment_ref),
            set_digest=input_set_digest((*original.metadata.input_set.references, environment_ref)),
        )
        input_set_metadata = InputSetMetadata(input_set=input_set)
        input_ref = archive.add("input-set-" + label, input_set_metadata)
        candidate_metadata = CandidateMetadata(source_ref=source.reference, input_set_ref=input_ref)
        candidate_ref = archive.add("candidate-" + label, candidate_metadata)
    with UnitOfWork(probe.maintenance_engine) as uow:
        task = uow.connection.execute(select(tasks).where(
            tasks.c.task_id == task_id,
        ).with_for_update()).mappings().one()
        previous = uow.connection.execute(select(task_inputs).where(
            task_inputs.c.task_id == task_id,
            task_inputs.c.input_validity_revision == task["input_validity_revision"],
        )).mappings().one()
        revision = task["input_validity_revision"] + 1
        uow.connection.execute(update(tasks).where(tasks.c.task_id == task_id).values(
            version=task["version"] + 1, input_validity_revision=revision, input_status="valid",
        ))
        uow.connection.execute(insert(task_inputs).values(
            task_id=task_id, input_validity_revision=revision,
            input_set_key=reference_key(PROJECT, input_ref), source_key=previous["source_key"],
            candidate_key=reference_key(PROJECT, candidate_ref),
            human_conclusion_key=previous["human_conclusion_key"],
        ))
    fixture = ProtocolCompletionFixture(task_id, input_ref, candidate_ref, environment_ref, ())
    verification = _insert_evidence(probe, task_id, fixture, label=label)
    accepted = _accept_required_work_items(probe, task_id, fixture, label=label)
    return ProtocolCompletionFixture(task_id, input_ref, candidate_ref, environment_ref,
                                     (verification, *(reference for _, reference in accepted)))


def refresh_protocol_work_items(probe, fixture: ProtocolCompletionFixture, *, label: str):
    """Rebind work-item evidence to actual current revisions before completion."""
    return _accept_required_work_items(probe, fixture.task_id, fixture, label=label)


def control_facts(probe, task_id: str):
    with UnitOfWork(probe.pools.control) as uow:
        return load_task_control_facts(uow.connection, task_id)


def apply_workspace_operation_without_hub_receipt(runtime, operation_id: str):
    """Use the real WorkspaceFileService; leave only Hub receipt registration pending."""
    with runtime.registry.admit(128 * 1024**2) as storage:
        intent = runtime._intent(operation_id)
        with runtime._git(storage, intent.result.binding.project_id) as git:
            service = WorkspaceFileService(
                storage.workspace_root, git, runtime.workspaces.resolve_mutation_operation,
            )
            try:
                receipt = service.apply(operation_id)
            finally:
                service.close()
    require(receipt.operation_id == operation_id and receipt.outcome == "applied",
            "engineering_workspace_physical_receipt_unsettled")
    return {"operation_id": operation_id, "physical_outcome": receipt.outcome,
            "hub_receipt_registered": False}


def execute_build_without_hub_receipt(runtime, operation_id: str):
    """Run and verify the real fixed-reference Runner journal without archiving it yet."""
    build_module = importlib.import_module("services.hub-worker.engineering_build")
    runner_module = importlib.import_module("services.dev-runner.engineering_build_runner")
    from modules.workspaces.safe_paths import WorkspaceFileError

    with runtime.registry.admit(BUILD_WORKSPACE_BYTES) as storage:
        record = build_module._record(runtime, operation_id, reconciliation=True)

        def gate():
            storage.observe()
            if build_module._record(runtime, operation_id, reconciliation=False) != record:
                raise WorkspaceFileError("build_operation_binding_changed")

        runner = runner_module.ControlledBuildRunner(storage, record, gate)
        try:
            if not runner.exists():
                gate()
                runner.execute(build_module._candidate_bytes(runtime, storage, record))
            with UnitOfWork(runtime.control_engine) as uow:
                previous = read_build_execution(uow.connection, record)
            runner.previous_observation_id = None if previous is None else previous.observation.observation_id
            physical = verify_build_observation(operation_id, runner)
            observation = physical.observation
            if len(observation.artifacts) == 3:
                verify_build_content(record, runner.store, tuple(
                    BuildArtifactLocator(role=item.role, storage_id=item.storage_id)
                    for item in observation.artifacts
                ))
        finally:
            runner.close()
    require(observation.closure in {"closed_unstarted", "ended_reconciled", "safely_stopped"},
            "engineering_build_physical_result_unsettled")
    return {"operation_id": operation_id, "physical_closure": observation.closure,
            "exit_code": observation.exit_code, "artifact_count": len(observation.artifacts),
            "hub_receipt_registered": False}


def close_build_unstarted_after_cancel(runtime, operation_id: str, cancel):
    """Pause after one real admission check, then prove cancellation fences Runner start."""
    build_module = importlib.import_module("services.hub-worker.engineering_build")
    runner_module = importlib.import_module("services.dev-runner.engineering_build_runner")
    from modules.workspaces.safe_paths import WorkspaceFileError

    with runtime.registry.admit(BUILD_WORKSPACE_BYTES) as storage:
        record = build_module._record(runtime, operation_id, reconciliation=True)

        def real_gate():
            storage.observe()
            if build_module._record(runtime, operation_id, reconciliation=False) != record:
                raise WorkspaceFileError("build_operation_binding_changed")

        entered, release = threading.Event(), threading.Event()
        calls = 0

        def gate():
            nonlocal calls
            calls += 1
            real_gate()
            if calls == 1:
                entered.set()
                if not release.wait(30):
                    raise WorkspaceFileError("engineering_task_control_gate_timeout")

        runner = runner_module.ControlledBuildRunner(storage, record, gate)
        failure = []

        def attempt_start():
            try:
                runner.execute(build_module._candidate_bytes(runtime, storage, record))
            except Exception as error:
                failure.append(type(error).__name__)

        thread = threading.Thread(target=attempt_start, name="p12-build-control-gate", daemon=True)
        thread.start()
        try:
            require(entered.wait(30), "engineering_build_start_gate_not_reached")
            cancel_result = cancel()
            require(cancel_result.status_code == 202 and cancel_result.body.outcome == "cancellation_requested",
                    "engineering_task_cancel_not_accepted_at_build_gate")
        finally:
            release.set()
            thread.join(30)
        try:
            require(not thread.is_alive() and not failure, "engineering_build_closed_unstarted_unconfirmed")
            with UnitOfWork(runtime.control_engine) as uow:
                previous = read_build_execution(uow.connection, record)
            runner.previous_observation_id = None if previous is None else previous.observation.observation_id
            verified = verify_build_observation(operation_id, runner)
            observation = verified.observation
        finally:
            runner.close()
    require(observation.closure == "closed_unstarted" and observation.exit_code is None
            and not observation.artifacts, "engineering_build_unstarted_receipt_not_physical")
    return cancel_result, {"operation_id": operation_id, "physical_closure": observation.closure,
                           "exit_code": observation.exit_code, "artifact_count": len(observation.artifacts),
                           "hub_receipt_registered": False,
                           "barrier": "real_admission_passed_then_task_cancel_fenced_next_side_effect"}
