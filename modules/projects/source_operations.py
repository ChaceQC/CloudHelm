"""Read immutable source intents and reauthorize their accepted command identity."""

from pydantic import ValidationError
from sqlalchemy import select

from database.commands import get_by_id
from database.uow import UnitOfWork, require_transaction
from modules.identity.actors import AuthoritativeResource, actor_for_command
from modules.identity.authorization import authorize_current
from modules.projects.source_import_tables import project_source_imports
from modules.workspaces.source_import import ReferenceImportSpec, reference_import_digest
from packages.contracts.p0.identity_contracts import CommandIntent, ResourceScope, request_digest
from packages.contracts.p1.source_requests import (
    ImportReferenceSourceRequest, SourceImportCommandResult, SourceImportView,
)

SOURCE_IMPORT_SCHEMA = "p1-source-reference-import-r1"


class SourceImportError(ValueError):
    """Fixed reason only; no database or filesystem diagnostics."""


def read_import_intent(connection, operation_id: str):
    require_transaction(connection)
    row = connection.execute(select(project_source_imports).where(
        project_source_imports.c.operation_id == operation_id,
    )).mappings().one_or_none()
    if row is None:
        raise SourceImportError("source_import_not_found")
    try:
        request = ImportReferenceSourceRequest.model_validate(row["request_json"])
        spec = ReferenceImportSpec.model_validate(row["spec_json"])
        command = get_by_id(connection, row["command_id"])
        if command is None:
            raise ValueError
        envelope = command.envelope
        intent = CommandIntent.model_validate(envelope.model_dump(include=set(CommandIntent.model_fields)))
        result = SourceImportCommandResult.model_validate(command.result)
        scope = ResourceScope(project_id=row["project_id"], resource_kind="project", resource_id=row["project_id"])
        if not all((
            command.status_code == 202, result.outcome == "accepted",
            envelope.request_schema_revision == SOURCE_IMPORT_SCHEMA, envelope.action == "project.manage",
            envelope.scope == scope, envelope.target == scope,
            envelope.request_digest == row["command_request_digest"] == request_digest(intent, request),
            envelope.expected_resource_revision == request.expected_project_revision == row["expected_project_revision"],
            command.authorization_decision_id == row["authorization_decision_id"],
            result.command_id == row["command_id"], result.project_id == row["project_id"],
            result.project_revision == row["accepted_project_revision"],
            result.operation_id == row["operation_id"] == "source-import-" + row["command_id"],
            result.source == spec.source, spec.source.project_id == row["project_id"],
            spec.source.source_id == row["source_id"] == "source-" + row["command_id"],
            spec.reference_revision == request.reference_revision,
            result.request_digest == row["request_digest"] == reference_import_digest(spec),
        )):
            raise ValueError
    except (ValueError, TypeError, KeyError, ValidationError):
        raise SourceImportError("source_import_intent_invalid") from None
    return row, spec


def import_view(row, spec: ReferenceImportSpec) -> SourceImportView:
    return SourceImportView(
        operation_id=row["operation_id"], command_id=row["command_id"], source=spec.source,
        request_digest=row["request_digest"], accepted_project_revision=row["accepted_project_revision"],
        accepted_at=row["accepted_at"],
    )


def resolve_import_operation_in_uow(uow: UnitOfWork, operation_id: str) -> ReferenceImportSpec:
    """Recheck accepted-command authority; the executor still owes real storage admission.

    RecordedCommandActor ignores device-session logout and rechecks current user,
    project role/ownership and policy. Call again before every new physical step.
    This read does not enqueue, claim, execute or report an import.
    """
    row, spec = read_import_intent(uow.connection, operation_id)
    actor = actor_for_command(uow, row["command_id"])
    resource = AuthoritativeResource(row["project_id"], "project", row["project_id"])
    authorize_current(uow, actor, resource, "project.manage")
    authorize_current(uow, actor, resource, "resource.read")
    return spec
