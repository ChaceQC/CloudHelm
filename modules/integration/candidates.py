"""Fix exact producer facts for one verification round; no acceptance is performed."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select

from database.commands import lock_and_get, save_result
from database.uow import UnitOfWork
from modules.collaboration.command_support import TaskCommandContext, lock_task_access, update_task
from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.guards import read_task, require_ordinary_progress, task_resource
from modules.collaboration.records import read_registered_reference, reference_key
from modules.collaboration.tables import task_inputs
from modules.delivery.queries import build_view, read_build_intent
from modules.identity.actors import AuthoritativeResource
from modules.identity.authorization import authorize_current
from modules.sync.events import append_event
from modules.sync.tables import event_log
from modules.workspaces.operations import read_workspace_operation
from modules.workspaces.receipts import read_workspace_registration
from packages.contracts.p0.engineering_contracts import EngineeringRef, EvidenceApplicability, InputSet, input_set_digest
from packages.contracts.p0.identity_contracts import CommandEnvelope, CommandIntent, request_digest
from packages.contracts.p1.build_records import build_digest
from packages.contracts.p1.task_facts import EnvironmentMetadata
from packages.contracts.p1.workspace_candidates import CandidateFreezeReceipt
from packages.contracts.p2.candidates import (
    CANDIDATE_SCHEMA, CandidateEvidenceLink, FixCandidateCommandResult, FixCandidateHttpResult,
    FixCandidateRequest, FixedCandidateRecord, FixedCandidateView,
)


def _ref(kind, object_id, revision, authority, value):
    return EngineeringRef(kind=kind, object_id=object_id, revision=revision, authority=authority,
                          digest=build_digest(value), digest_algorithm="sha256")


def _operation_access(uow, actor, task, operation_id):
    authorize_current(uow, actor, AuthoritativeResource(
        task["project_id"], "operation", operation_id, task_id=task["task_id"],
    ), "operation.query")


def _current_input(connection, task):
    return connection.scalar(select(task_inputs.c.input_set_key).where(
        task_inputs.c.task_id == task["task_id"],
        task_inputs.c.input_validity_revision == task["input_validity_revision"],
    ))


def _fix(context, request):
    uow, task = context.uow, context.task
    require_ordinary_progress(
        uow.connection, task["task_id"], expected_version=request.expected_version,
        expected_control_revision=request.expected_control_revision,
        expected_input_validity_revision=request.expected_input_validity_revision,
    )
    row, build = read_build_intent(uow.connection, request.build_operation_id)
    if build.task_id != task["task_id"] or build.project_id != task["project_id"]:
        raise TaskBoundaryError("candidate_build_not_found", status_code=404)
    _operation_access(uow, context.actor, task, build.operation_id)
    if (build.control_revision != task["control_revision"]
            or build.input_validity_revision != task["input_validity_revision"]
            or row["input_set_key"] != _current_input(uow.connection, task)):
        raise TaskBoundaryError("candidate_build_input_stale")
    view = build_view(uow.connection, build)
    if (view.state != "succeeded" or not view.content.applicable or not view.execution.applicable):
        raise TaskBoundaryError("candidate_build_evidence_unavailable")
    snapshot = build.fixed_inputs.candidate
    intent, _ = read_workspace_operation(uow.connection, snapshot.freeze_operation_id)
    _operation_access(uow, context.actor, task, snapshot.freeze_operation_id)
    source = read_workspace_registration(uow.connection, intent)
    if (source is None or not source.applicable or type(source.receipt) is not CandidateFreezeReceipt
            or source.receipt.snapshot != snapshot
            or intent.result.input_set_ref != build.fixed_inputs.source_input_set_ref
            or intent.request.expected_control_revision != task["control_revision"]
            or intent.request.expected_input_validity_revision != task["input_validity_revision"]):
        raise TaskBoundaryError("candidate_source_evidence_unavailable")
    environment = read_registered_reference(uow.connection, task["project_id"], request.environment_ref)
    if not isinstance(environment.metadata, EnvironmentMetadata):
        raise TaskBoundaryError("candidate_registered_environment_required")
    source_ref = next(ref for ref in build.fixed_inputs.input_set.references
                      if ref.kind == "candidate" and ref.object_id == snapshot.candidate_id)
    build_ref = _ref("build", build.build_run_id, "1", "delivery", build)
    references = (*build.fixed_inputs.input_set.references, build_ref, view.execution.observation.method_ref,
                  *(item.content_ref for item in view.content.artifacts), environment.reference)
    references = tuple({ref.model_dump_json(): ref for ref in references}.values())
    digest = input_set_digest(references)
    try:
        inputs = InputSet(input_set_id="candidate-inputs-" + digest[7:], references=references, set_digest=digest)
    except ValueError:
        raise TaskBoundaryError("candidate_input_set_invalid", status_code=422) from None
    evidence = tuple(CandidateEvidenceLink(
        scope=scope, evidence_ref=_ref("evidence", scope + "-" + build_digest(fact)[7:],
                                      "1", authority, fact), subject_ref=subject,
    ) for scope, subject, authority, fact in (
        ("source_snapshot", source_ref, "workspaces", source),
        ("build_execution", build_ref, "delivery", view.execution),
        ("artifact_content", build_ref, "delivery", view.content),
    ))
    update_task(context)
    record = FixedCandidateRecord(
        candidate_id="fixed-candidate-" + context.envelope.command_id, command_id=context.envelope.command_id,
        project_id=task["project_id"], task_id=task["task_id"], task_version=context.task["version"],
        control_revision=task["control_revision"], input_validity_revision=task["input_validity_revision"],
        source_input_set_ref=build.fixed_inputs.source_input_set_ref, build_operation_id=build.operation_id,
        input_set=inputs, environment_ref=environment.reference, evidence=evidence, created_at=datetime.now(UTC),
    )
    append_event(uow.connection, command_id=record.command_id, project_id=record.project_id,
                 aggregate_kind="candidate", aggregate_id=record.candidate_id, aggregate_version=1,
                 event_id=record.candidate_id, event_type="candidate.fixed", schema_version=CANDIDATE_SCHEMA,
                 payload=record)
    return record


def _read(connection, task, candidate_id):
    event = connection.execute(select(event_log).where(
        event_log.c.event_id == candidate_id, event_log.c.project_id == task["project_id"],
        event_log.c.event_type == "candidate.fixed",
    )).mappings().one_or_none()
    if event is None:
        raise TaskBoundaryError("fixed_candidate_not_found", status_code=404)
    record = FixedCandidateRecord.model_validate(event["payload"])
    if (record.task_id != task["task_id"] or record.project_id != task["project_id"]
            or record.candidate_id != candidate_id or event["command_id"] != record.command_id
            or event["aggregate_kind"] != "candidate" or event["aggregate_id"] != candidate_id
            or event["aggregate_version"] != 1 or event["schema_version"] != CANDIDATE_SCHEMA):
        raise TaskBoundaryError("fixed_candidate_not_found", status_code=404)
    return record


class FixedCandidateApplication:
    def __init__(self, engine, control_engine):
        self.engine, self.control_engine = engine, control_engine

    def fix(self, actor, task_id, request: FixCandidateRequest, *, idempotency_key):
        with UnitOfWork(self.engine) as uow:
            task, authorization = lock_task_access(uow, actor, task_id, "candidate.submit")
            resource = task_resource(task)
            intent = CommandIntent(
                request_schema_revision=CANDIDATE_SCHEMA, caller=actor.principal, scope=resource.scope,
                target=resource.target_scope, action="candidate.submit", expected_resource_revision=request.expected_version,
            )
            envelope = CommandEnvelope(**intent.model_dump(), command_id=uuid4().hex, idempotency_key=idempotency_key,
                                       request_digest=request_digest(intent, request))
            existing = lock_and_get(uow.connection, envelope)
            if existing is not None:
                result = FixCandidateCommandResult.model_validate(existing.result)
                if result.candidate_id is not None:
                    record = _read(uow.connection, task, result.candidate_id)
                    _operation_access(uow, actor, task, record.build_operation_id)
                return FixCandidateHttpResult(status_code=existing.status_code, body=result)
            context = TaskCommandContext(uow, actor, task, authorization, envelope)
            candidate_id = None
            try:
                with uow.connection.begin_nested():
                    record = _fix(context, request)
                    candidate_id, outcome, code, status = record.candidate_id, "fixed", "candidate_fixed", 201
            except TaskBoundaryError as error:
                if error.status_code not in {409, 422}:
                    raise
                context.task = read_task(uow.connection, task_id, for_update=True)
                outcome, code, status = "rejected", error.code, error.status_code
            result = FixCandidateCommandResult(
                command_id=envelope.command_id, project_id=task["project_id"], task_id=task_id,
                version=context.task["version"], control_revision=context.task["control_revision"],
                input_validity_revision=context.task["input_validity_revision"], outcome=outcome, code=code,
                candidate_id=candidate_id,
            )
            save_result(uow.connection, envelope, result, status_code=status, authorization=authorization.envelope)
            return FixCandidateHttpResult(status_code=status, body=result)

    def query(self, actor, task_id, candidate_id):
        with UnitOfWork(self.control_engine) as uow:
            task, _ = lock_task_access(uow, actor, task_id, "resource.read")
            record = _read(uow.connection, task, candidate_id)
            _operation_access(uow, actor, task, record.build_operation_id)
            current = (task["state"] == "active" and not task["ordinary_progress_closed"]
                       and task["cancel_requested_at"] is None and task["input_status"] == "valid"
                       and task["control_revision"] == record.control_revision
                       and task["input_validity_revision"] == record.input_validity_revision
                       and _current_input(uow.connection, task) == reference_key(
                           task["project_id"], record.source_input_set_ref))
            candidate_ref = _ref("candidate", candidate_id, CANDIDATE_SCHEMA, "integration", record)
            input_ref = _ref("input_set", record.input_set.input_set_id, CANDIDATE_SCHEMA,
                             "integration", record.input_set)
            applicability = tuple(EvidenceApplicability(
                evidence_ref=item.evidence_ref, consumer_ref=candidate_ref, input_set_ref=input_ref,
                input_validity_revision=task["input_validity_revision"], status="valid" if current else "needs_review",
                rule_id="fixed-candidate-" + item.scope, rule_version=CANDIDATE_SCHEMA,
                reason_code="exact_fixed_inputs" if current else "task_inputs_or_control_changed",
            ) for item in record.evidence)
            return FixedCandidateView(record=record, applicability=applicability)
