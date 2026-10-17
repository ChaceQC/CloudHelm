"""Authenticated source intents; physical Git runs after the accepting transaction."""

from uuid import uuid4

from sqlalchemy import insert, select, update

from database.commands import lock_and_get, save_result
from database.readiness import assert_schema_ready
from database.uow import UnitOfWork
from modules.identity.actors import AuthenticatedActor, AuthoritativeResource, validate_actor
from modules.identity.authorization import authorize_current
from modules.identity.errors import IdentityError
from modules.projects.source_import_tables import project_source_imports
from modules.projects.source_operations import (
    SOURCE_IMPORT_SCHEMA, SourceImportError, import_view, read_import_intent, resolve_import_operation_in_uow,
)
from modules.projects.source_tables import project_git_sources
from modules.projects.source_receipts import read_source_registration, register_published_import, verify_published_import
from modules.projects.tables import projects
from modules.sync.events import append_event
from modules.workspaces.source_import import ReferenceImportSpec, ReferenceSourceImporter, reference_import_digest
from packages.contracts.p0.identity_contracts import CommandEnvelope, CommandIntent, request_digest
from packages.contracts.p1.source_requests import (
    ImportReferenceSourceRequest, SourceImportCommandResult, SourceImportHttpResult, SourceImportView,
)
from packages.contracts.p1.source_records import SourceImportRegistration
from packages.contracts.p1.workspace_git import RegisteredGitSource

MAX_REVISION = 9007199254740991


def current_project_access(uow, actor, project_id):
    validate_actor(actor)
    if not isinstance(actor, AuthenticatedActor):
        raise IdentityError("authentication_failed")
    resource = AuthoritativeResource(project_id, "project", project_id)
    decision = authorize_current(uow, actor, resource, "project.manage")
    authorize_current(uow, actor, resource, "resource.read")
    return resource, decision


def accept_reference_import(uow, actor, project_id, request, *, idempotency_key, enqueue_operation=None):
    """Participate in the caller's UoW; current permission precedes durable replay."""
    if type(request) is not ImportReferenceSourceRequest:
        raise SourceImportError("source_import_request_invalid")
    try:
        request = ImportReferenceSourceRequest.model_validate(request.model_dump(mode="python"))
    except ValueError:
        raise SourceImportError("source_import_request_invalid") from None
    resource, authorization = current_project_access(uow, actor, project_id)
    project = uow.connection.execute(select(projects).where(
        projects.c.project_id == project_id,
    ).with_for_update()).mappings().one()
    intent = CommandIntent(
        request_schema_revision=SOURCE_IMPORT_SCHEMA, caller=actor.principal,
        scope=resource.scope, target=resource.target_scope, action="project.manage",
        expected_resource_revision=request.expected_project_revision,
    )
    envelope = CommandEnvelope(**intent.model_dump(), command_id=uuid4().hex,
                               idempotency_key=idempotency_key, request_digest=request_digest(intent, request))
    existing = lock_and_get(uow.connection, envelope)
    if existing is not None:
        return SourceImportHttpResult(status_code=existing.status_code,
                                      body=SourceImportCommandResult.model_validate(existing.result))
    code = None
    if project["revision"] != request.expected_project_revision:
        code = "resource_revision_conflict"
    elif project["revision"] >= MAX_REVISION:
        code = "revision_limit_reached"
    elif uow.connection.scalar(select(project_git_sources.c.project_id).where(
        project_git_sources.c.project_id == project_id,
    )) is not None:
        code = "project_source_already_registered"
    elif uow.connection.scalar(select(project_source_imports.c.operation_id).where(
        project_source_imports.c.project_id == project_id,
    )) is not None:
        code = "project_source_import_already_requested"
    if code is not None:
        result = SourceImportCommandResult(command_id=envelope.command_id, project_id=project_id,
                                           project_revision=project["revision"], outcome="rejected", code=code)
        status = 409
    else:
        assert_schema_ready(uow.connection)
        source = RegisteredGitSource(
            project_id=project_id, source_id="source-" + envelope.command_id, source_revision=1,
            kind="managed_bare", target_branch="refs/heads/main", source_prefix="",
            object_format="sha1", access_mode="read_write",
        )
        spec = ReferenceImportSpec(source=source, reference_revision=request.reference_revision)
        digest, revision = reference_import_digest(spec), project["revision"] + 1
        operation_id = "source-import-" + envelope.command_id
        uow.connection.execute(insert(project_source_imports).values(
            operation_id=operation_id, project_id=project_id, source_id=source.source_id,
            command_id=envelope.command_id, authorization_decision_id=authorization.envelope.decision_id,
            expected_project_revision=request.expected_project_revision, accepted_project_revision=revision,
            request_json=request.model_dump(mode="json"), command_request_digest=envelope.request_digest,
            spec_json=spec.model_dump(mode="json"), request_digest=digest,
        ))
        uow.connection.execute(update(projects).where(
            projects.c.project_id == project_id, projects.c.revision == project["revision"],
        ).values(revision=revision))
        result = SourceImportCommandResult(
            command_id=envelope.command_id, project_id=project_id, project_revision=revision,
            outcome="accepted", code="source_import_awaiting_executor", operation_id=operation_id,
            source=source, request_digest=digest,
        )
        append_event(uow.connection, command_id=envelope.command_id, project_id=project_id,
                     aggregate_kind="project", aggregate_id=project_id, aggregate_version=revision,
                     event_type="project.source_import_accepted", schema_version="p1-source-import-event-r1", payload=result)
        status = 202
    save_result(uow.connection, envelope, result, status_code=status, authorization=authorization.envelope)
    if status == 202 and enqueue_operation is not None:
        enqueue_operation(uow, result.operation_id, envelope.command_id, project_id,
                          result.project_revision, envelope.request_digest)
    return SourceImportHttpResult(status_code=status, body=result)


class SourceImportApplication:
    def __init__(self, engine, control_engine, *, enqueue_operation=None) -> None:
        self.engine, self.control_engine = engine, control_engine
        self.enqueue_operation = enqueue_operation

    def import_reference(self, actor, project_id, request, *, idempotency_key) -> SourceImportHttpResult:
        with UnitOfWork(self.engine) as uow:
            return accept_reference_import(uow, actor, project_id, request, idempotency_key=idempotency_key,
                                           enqueue_operation=self.enqueue_operation)

    def query(self, actor, project_id: str, operation_id: str) -> SourceImportView:
        with UnitOfWork(self.control_engine) as uow:
            current_project_access(uow, actor, project_id)
            row, spec = read_import_intent(uow.connection, operation_id)
            if row["project_id"] != project_id:
                raise SourceImportError("source_import_not_found")
            view = import_view(row, spec)
            registration = read_source_registration(uow.connection, row)
            if registration is not None:
                view = SourceImportView.model_validate({**view.model_dump(mode="python"), "state": "registered",
                                                        "code": "source_import_registered", "registration": registration})
            return view

    def finish_import(self, operation_id: str, importer: ReferenceSourceImporter) -> SourceImportRegistration:
        verified = verify_published_import(operation_id, importer)
        with UnitOfWork(self.engine) as uow:
            return register_published_import(uow, operation_id, verified)

    def resolve_import_operation(self, operation_id: str) -> ReferenceImportSpec:
        with UnitOfWork(self.control_engine) as uow:
            return resolve_import_operation_in_uow(uow, operation_id)
