"""Build acceptance owns one short UoW; no Git, container or content I/O occurs here."""

from uuid import uuid4

from sqlalchemy import insert, select

from database.commands import CommandConflict, lock_and_get, save_result
from database.readiness import assert_schema_ready
from database.uow import UnitOfWork, require_transaction
from modules.collaboration.command_support import TaskCommandContext, lock_task_access, update_task
from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.guards import read_task, require_ordinary_progress, task_resource
from modules.collaboration.records import read_registered_reference, reference_key
from modules.collaboration.tables import task_inputs
from modules.delivery.errors import BuildBoundaryError
from modules.delivery.queries import build_operation_digest, build_view, read_build_intent
from modules.delivery.tables import build_runs
from modules.identity.actors import AuthoritativeResource, actor_for_command, validate_actor
from modules.identity.authorization import authorize_current
from modules.sync.events import append_event
from modules.workspaces.tables import workspace_candidates
from packages.contracts.p0.engineering_contracts import InputSet, input_set_digest
from packages.contracts.p0.identity_contracts import CommandEnvelope, CommandIntent, request_digest
from packages.contracts.p1.build_records import BuildFixedInputs, build_digest, build_input_references
from packages.contracts.p1.build_requests import BUILD_REQUEST_SCHEMA, BuildCommandResult, BuildHttpResult, RequestBuildRequest
from packages.contracts.p1.task_facts import InputSetMetadata
from packages.contracts.p1.workspace_git import CandidateSnapshot
from packages.contracts.p1.workspace_records import workspace_metadata_digest


def _candidate(connection, task, candidate_id):
    row = connection.execute(select(workspace_candidates).where(
        workspace_candidates.c.candidate_id == candidate_id,
        workspace_candidates.c.project_id == task["project_id"],
        workspace_candidates.c.task_id == task["task_id"],
    )).mappings().one_or_none()
    if row is None:
        raise BuildBoundaryError("build_candidate_not_found")
    try:
        snapshot = CandidateSnapshot.model_validate(row["snapshot_json"])
        if (snapshot.candidate_id != candidate_id or workspace_metadata_digest(snapshot) != row["snapshot_digest"]
                or any(getattr(snapshot.binding, key) != row[key] for key in (
                    "workspace_id", "project_id", "task_id", "work_item_id", "owner_user_id", "source_id",
                    "source_revision", "workspace_revision", "write_generation",
                )) or any(getattr(snapshot, key) != row[key] for key in (
                    "candidate_commit", "parent_commit", "freeze_operation_id", "storage_id",
                ))):
            raise ValueError
        return snapshot
    except ValueError:
        raise BuildBoundaryError("build_candidate_invalid") from None


def _fixed_inputs(connection, task, request):
    key = reference_key(task["project_id"], request.input_set_ref)
    current = connection.execute(select(task_inputs).where(
        task_inputs.c.task_id == task["task_id"],
        task_inputs.c.input_validity_revision == task["input_validity_revision"],
    )).mappings().one_or_none()
    if current is None or current["input_set_key"] != key:
        raise BuildBoundaryError("build_input_not_current")
    registered = read_registered_reference(connection, task["project_id"], request.input_set_ref)
    if not isinstance(registered.metadata, InputSetMetadata):
        raise BuildBoundaryError("build_registered_input_set_required")
    source = registered.metadata.input_set
    candidate = _candidate(connection, task, request.candidate_id)
    references = build_input_references(source, candidate, request.definition)
    digest = input_set_digest(references)
    try:
        fixed = BuildFixedInputs(
            source_input_set_ref=registered.reference, source_input_set=source, candidate=candidate,
            definition=request.definition, input_set=InputSet(
                input_set_id="build-inputs-" + digest[7:], references=references, set_digest=digest,
            ),
        )
    except ValueError:
        raise BuildBoundaryError("build_fixed_inputs_invalid", status_code=422) from None
    return fixed, key


def _result(context, outcome, code, **values):
    task = context.task
    return BuildCommandResult(
        command_id=context.envelope.command_id, project_id=task["project_id"], task_id=task["task_id"],
        version=task["version"], control_revision=task["control_revision"],
        input_validity_revision=task["input_validity_revision"], outcome=outcome, code=code, **values,
    )


def _accept(context, request):
    connection, task = context.uow.connection, context.task
    require_ordinary_progress(
        connection, task["task_id"], expected_version=request.expected_version,
        expected_control_revision=request.expected_control_revision,
        expected_input_validity_revision=request.expected_input_validity_revision,
    )
    fixed, key = _fixed_inputs(connection, task, request)
    build_run_id, operation_id = "build-" + context.envelope.command_id, "build-operation-" + context.envelope.command_id
    digest = build_digest(fixed)
    physical_digest = build_operation_digest(operation_id, build_run_id, digest)
    update_task(context)
    connection.execute(insert(build_runs).values(
        build_run_id=build_run_id, operation_id=operation_id, command_id=context.envelope.command_id,
        project_id=task["project_id"], task_id=task["task_id"], candidate_id=request.candidate_id,
        expected_task_version=request.expected_version, accepted_task_version=context.task["version"],
        control_revision=task["control_revision"], input_validity_revision=task["input_validity_revision"],
        input_set_key=key, request_json=request.model_dump(mode="json"),
        command_request_digest=context.envelope.request_digest, request_digest=physical_digest,
        fixed_inputs_json=fixed.model_dump(mode="json"), build_input_digest=digest,
        authorization_decision_id=context.authorization.envelope.decision_id,
    ))
    result = _result(context, "accepted", "build_awaiting_executor", build_run_id=build_run_id,
                     operation_id=operation_id, request_digest=physical_digest, build_input_digest=digest)
    append_event(connection, command_id=context.envelope.command_id, project_id=task["project_id"],
                 aggregate_kind="build", aggregate_id=build_run_id, aggregate_version=1,
                 event_type="build.request_accepted", schema_version="p1-build-request-event-r1", payload=result)
    return result


def accept_build(uow, actor, task_id, request, *, idempotency_key, enqueue_operation=None) -> BuildHttpResult:
    """Current auth precedes replay; enqueue failure rolls back the entire caller UoW."""
    require_transaction(uow.connection)
    validate_actor(actor)
    if type(request) is not RequestBuildRequest:
        raise BuildBoundaryError("build_request_invalid", status_code=422)
    try:
        request = RequestBuildRequest.model_validate(request.model_dump(mode="python"))
    except ValueError:
        raise BuildBoundaryError("build_request_invalid", status_code=422) from None
    task, authorization = lock_task_access(uow, actor, task_id, "operation.request")
    resource = task_resource(task)
    intent = CommandIntent(request_schema_revision=BUILD_REQUEST_SCHEMA, caller=actor.principal,
                           scope=resource.scope, target=resource.target_scope, action="operation.request",
                           expected_resource_revision=request.expected_version)
    envelope = CommandEnvelope(**intent.model_dump(), command_id=uuid4().hex,
                               idempotency_key=idempotency_key, request_digest=request_digest(intent, request))
    context = TaskCommandContext(uow, actor, task, authorization, envelope)
    try:
        existing = lock_and_get(uow.connection, envelope)
        if existing is not None:
            result = BuildCommandResult.model_validate(existing.result)
            if result.operation_id is not None:
                authorize_current(uow, actor, AuthoritativeResource(
                    task["project_id"], "operation", result.operation_id, task_id=task_id,
                ), "operation.query")
            return BuildHttpResult(status_code=existing.status_code, body=result)
        try:
            with uow.connection.begin_nested():
                result, status = _accept(context, request), 202
        except TaskBoundaryError as error:
            context.task = read_task(uow.connection, task_id, for_update=True)
            result, status = _result(context, "rejected", error.code), error.status_code
        if result.outcome == "accepted" and enqueue_operation is not None:
            enqueue_operation(uow, operation_id=result.operation_id, command_id=envelope.command_id,
                              build_id=result.build_run_id, advance_revision=result.version,
                              request_digest=envelope.request_digest)
        save_result(uow.connection, envelope, result, status_code=status, authorization=authorization.envelope)
        return BuildHttpResult(status_code=status, body=result)
    except CommandConflict as error:
        raise BuildBoundaryError(str(error)) from None


def resolve_build_operation_in_uow(uow, operation_id):
    """Before each new side effect; fixed input is separate from executor admission."""
    row, record = read_build_intent(uow.connection, operation_id)
    actor = actor_for_command(uow, row["command_id"])
    task, _ = lock_task_access(uow, actor, row["task_id"], "operation.request")
    authorize_current(uow, actor, AuthoritativeResource(
        row["project_id"], "operation", operation_id, task_id=row["task_id"],
    ), "operation.query")
    require_ordinary_progress(uow.connection, task["task_id"], expected_version=task["version"],
                              expected_control_revision=record.control_revision,
                              expected_input_validity_revision=record.input_validity_revision)
    current = uow.connection.execute(select(task_inputs.c.input_set_key).where(
        task_inputs.c.task_id == task["task_id"],
        task_inputs.c.input_validity_revision == task["input_validity_revision"],
    )).scalar_one_or_none()
    if current != row["input_set_key"]:
        raise BuildBoundaryError("build_input_not_current")
    assert_schema_ready(uow.connection)
    return record


class BuildApplication:
    def __init__(self, engine, control_engine, *, enqueue_operation=None):
        self.engine, self.control_engine, self.enqueue_operation = engine, control_engine, enqueue_operation

    def request(self, actor, task_id, request, *, idempotency_key):
        with UnitOfWork(self.engine) as uow:
            return accept_build(uow, actor, task_id, request, idempotency_key=idempotency_key,
                                enqueue_operation=self.enqueue_operation)

    def query(self, actor, task_id, operation_id):
        with UnitOfWork(self.control_engine) as uow:
            task, _ = lock_task_access(uow, actor, task_id, "resource.read")
            row, record = read_build_intent(uow.connection, operation_id)
            if row["task_id"] != task_id or row["project_id"] != task["project_id"]:
                raise BuildBoundaryError("build_not_found", status_code=404)
            authorize_current(uow, actor, AuthoritativeResource(
                task["project_id"], "operation", operation_id, task_id=task_id,
            ), "operation.query")
            return build_view(uow.connection, record)
