"""Immutable workspace operation intents and current execution gates."""

import re
import hashlib
import rfc8785
from pydantic import model_validator
from sqlalchemy import func, select

from database.commands import get_by_id
from database.uow import require_transaction
from modules.collaboration.command_support import lock_task_access
from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.guards import require_ordinary_progress
from modules.collaboration.initial_inputs import validate_initial_input_set
from modules.collaboration.records import read_fact_source, read_registered_reference, reference_key
from modules.collaboration.tables import task_inputs
from modules.identity.actors import actor_for_command
from modules.projects.source_import_tables import project_source_imports
from modules.projects.source_receipts import read_source_registration
from modules.sync.tables import event_log
from modules.workspaces.tables import workspaces
from packages.contracts.p0.decision_common import Contract, Identifier
from packages.contracts.p0.engineering_contracts import EngineeringRef
from packages.contracts.p0.identity_contracts import ResourceScope
from packages.contracts.p0.task_control_contracts import OperationClosureFact
from packages.contracts.p1.workspace_git import WorkspaceBinding, WorkspaceMutationSpec, content_digest
from packages.contracts.p1.workspace_records import workspace_metadata_digest
from packages.contracts.p1.workspace_requests import WorkspaceCommandResult, WorkspaceRequest

OPERATION_SCHEMA = "p1-workspace-operation-event-r1"
REQUEST_SCHEMAS = {kind: "p1-workspace-" + kind + "-r1" for kind in ("create", "materialize", "mutate", "candidate")}


class WorkspaceError(TaskBoundaryError):
    """Fixed reason codes only, with no filesystem/database diagnostics."""


class WorkspaceOperationIntent(Contract):
    request: WorkspaceRequest
    result: WorkspaceCommandResult
    materialization_operation_id: Identifier | None = None
    runtime_scope_id: Identifier | None = None

    @model_validator(mode="after")
    def check_operation(self):
        result = self.result
        if (result.outcome != "accepted" or result.kind == "create" or result.kind != self.request.kind
                or result.input_set_ref != self.request.input_set_ref):
            raise ValueError("workspace_operation_intent_invalid")
        if (result.kind != "materialize") != (self.materialization_operation_id is not None):
            raise ValueError("workspace_materialization_binding_invalid")
        if (result.kind == "candidate") != (self.runtime_scope_id is not None):
            raise ValueError("workspace_runtime_scope_binding_invalid")
        return self


def operation_identity(kind, command_id):
    return "workspace-" + kind + "-" + command_id


def operation_command_id(operation_id):
    if not isinstance(operation_id, str):
        raise WorkspaceError("workspace_operation_not_found", status_code=404)
    match = re.fullmatch(r"workspace-(materialize|mutate|candidate)-([0-9a-f]{32})", operation_id)
    if match is None:
        raise WorkspaceError("workspace_operation_not_found", status_code=404)
    return match.group(2)


def mutation_spec(intent, content):
    request, binding = intent.request, intent.result.binding
    if request.kind != "mutate":
        raise WorkspaceError("workspace_operation_kind_invalid")
    try:
        spec = WorkspaceMutationSpec(
            binding=binding, materialization_operation_id=intent.materialization_operation_id,
            action=request.action, path=request.path, expected_manifest_digest=request.expected_manifest_digest,
            expected_file=request.expected_file, content=content,
            mode=request.replacement.mode if request.replacement else None,
        )
    except ValueError:
        raise WorkspaceError("workspace_mutation_content_mismatch") from None
    if spec.replacement != request.replacement:
        raise WorkspaceError("workspace_mutation_content_mismatch")
    return spec


def candidate_spec(intent):
    from packages.contracts.p1.workspace_candidates import CandidateFreezeSpec

    return CandidateFreezeSpec(
        binding=intent.result.binding, materialization_operation_id=intent.materialization_operation_id,
        candidate_id="candidate-" + intent.result.command_id,
        expected_manifest_digest=intent.request.expected_manifest_digest, runtime_scope_id=intent.runtime_scope_id,
    )


def operation_request_digest(intent):
    result, request = intent.result, intent.request
    if result.kind == "materialize":
        return workspace_metadata_digest(result.binding)
    if result.kind == "candidate":
        from packages.contracts.p1.workspace_candidates import candidate_freeze_digest

        return candidate_freeze_digest(candidate_spec(intent))
    return content_digest(rfc8785.dumps({
        "schema_revision": "p1-workspace-file-operation-r1", "binding": result.binding.model_dump(mode="json"),
        "materialization_operation_id": intent.materialization_operation_id, "action": request.action,
        "path": request.path, "expected_manifest_digest": request.expected_manifest_digest,
        "expected_file": request.expected_file.model_dump() if request.expected_file else None,
        "replacement": request.replacement.model_dump() if request.replacement else None,
    }))


def read_workspace_operation(connection, operation_id):
    """Internal lookup; callers must authorize before returning any result."""
    require_transaction(connection)
    command_id = operation_command_id(operation_id)
    event = connection.execute(select(event_log).where(
        event_log.c.event_id == "workspace-intent-" + command_id,
    )).mappings().one_or_none()
    if event is None:
        raise WorkspaceError("workspace_operation_not_found", status_code=404)
    try:
        value = WorkspaceOperationIntent.model_validate(event["payload"])
        result, request = value.result, value.request
        command = get_by_id(connection, command_id)
        if command is None:
            raise ValueError
        envelope = command.envelope
        from modules.workspaces.commands import workspace_command_digest

        scope = ResourceScope(project_id=result.binding.project_id, resource_kind="task", resource_id=result.task_id)
        action = "candidate.submit" if request.kind == "candidate" else "workspace.write"
        if not all((
            event["command_id"] == command_id == result.command_id,
            event["project_id"] == result.binding.project_id, event["aggregate_kind"] == "workspace",
            event["aggregate_id"] == result.workspace_id, event["aggregate_version"] == result.binding.workspace_revision,
            event["schema_version"] == OPERATION_SCHEMA, event["event_type"] == "workspace.operation_accepted",
            command.status_code == 202, command.result == result.model_dump(mode="json"),
            envelope.scope == scope, envelope.target == scope, envelope.action == action,
            envelope.request_schema_revision == REQUEST_SCHEMAS[request.kind],
            envelope.expected_resource_revision == request.expected_version,
            envelope.request_digest == workspace_command_digest(envelope, request, result.workspace_id),
            result.version == request.expected_version + 1,
            result.control_revision == request.expected_control_revision,
            result.input_validity_revision == request.expected_input_validity_revision,
            result.binding.workspace_revision == request.expected_workspace_revision,
            result.binding.write_generation == request.expected_write_generation,
            result.operation_id == operation_id == operation_identity(request.kind, command_id),
            result.request_digest == operation_request_digest(value),
        )):
            raise ValueError
    except (ValueError, TypeError, KeyError):
        raise WorkspaceError("workspace_operation_intent_invalid") from None
    return value, event["created_at"]


def read_workspace_row(connection, workspace_id, *, for_update=False):
    require_transaction(connection)
    if for_update:
        # API owns INSERT but no mutable Workspace columns. PostgreSQL row-lock
        # SELECTs require UPDATE privilege; an advisory lock preserves that role
        # boundary. The caller already holds the owning Task row lock.
        digest = hashlib.sha256(rfc8785.dumps(["cloudhelm.workspace.v1", workspace_id])).digest()
        connection.execute(select(func.pg_advisory_xact_lock(int.from_bytes(digest[:8], "big", signed=True))))
    statement = select(workspaces).where(workspaces.c.workspace_id == workspace_id)
    row = connection.execute(statement).mappings().one_or_none()
    if row is None:
        raise WorkspaceError("workspace_not_found", status_code=404)
    return row


def current_engineering_input(connection, task, input_set_ref):
    row = connection.execute(select(task_inputs).where(
        task_inputs.c.task_id == task["task_id"],
        task_inputs.c.input_validity_revision == task["input_validity_revision"],
    )).mappings().one_or_none()
    if row is None or row["input_set_key"] != reference_key(task["project_id"], input_set_ref):
        raise WorkspaceError("workspace_input_not_current")
    inputs, source = validate_initial_input_set(connection, task, input_set_ref)
    records = [inputs, source, *(read_registered_reference(connection, task["project_id"], reference)
                                for reference in inputs.metadata.input_set.references)]
    for record in records:
        if read_fact_source(connection, task["project_id"], record.source_id).purpose != "product":
            raise WorkspaceError("workspace_product_input_required")
    if row["source_key"] != reference_key(task["project_id"], source.reference):
        raise WorkspaceError("workspace_source_input_mismatch")
    imported = connection.execute(select(project_source_imports).where(
        project_source_imports.c.project_id == task["project_id"],
    )).mappings().one_or_none()
    registration = read_source_registration(connection, imported) if imported is not None else None
    if registration is None or registration.source_ref != source.reference:
        raise WorkspaceError("workspace_registered_source_required")
    return registration


def resolve_workspace_operation_in_uow(uow, operation_id, *, reconciliation=False):
    """Reconciliation permits original-result queries only, never a new side effect."""
    intent, _ = read_workspace_operation(uow.connection, operation_id)
    actor = actor_for_command(uow, intent.result.command_id)
    action = "candidate.submit" if intent.request.kind == "candidate" else "workspace.write"
    task, authorization = lock_task_access(uow, actor, intent.result.task_id, action)
    workspace = read_workspace_row(uow.connection, intent.result.workspace_id, for_update=True)
    if workspace["task_id"] != task["task_id"]:
        raise WorkspaceError("workspace_task_binding_mismatch")
    if not reconciliation:
        require_ordinary_progress(
            uow.connection, task["task_id"], expected_version=task["version"],
            expected_control_revision=intent.request.expected_control_revision,
            expected_input_validity_revision=intent.request.expected_input_validity_revision,
            allowed_states=("draft", "active"),
        )
        current_engineering_input(uow.connection, task, intent.request.input_set_ref)
        if WorkspaceBinding.model_validate(workspace["binding_json"]) != intent.result.binding:
            raise WorkspaceError("workspace_operation_binding_stale")
        from modules.workspaces.receipts import read_workspace_registration

        if read_workspace_registration(uow.connection, intent) is not None:
            raise WorkspaceError("workspace_operation_already_registered")
    return intent, task, workspace, authorization


def pending_workspace_operations(connection, task_id):
    """Project only real accepted intents lacking a verified physical terminal fact."""
    require_transaction(connection)
    rows = connection.execute(select(event_log.c.payload).where(
        event_log.c.schema_version == OPERATION_SCHEMA,
        event_log.c.payload["result"]["task_id"].astext == task_id,
    ).order_by(event_log.c.event_id).limit(129)).all()
    if len(rows) > 128:
        raise WorkspaceError("workspace_operation_scope_too_large")
    from modules.workspaces.receipts import read_workspace_registration

    pending = []
    for row in rows:
        raw = WorkspaceOperationIntent.model_validate(row.payload)
        intent, _ = read_workspace_operation(connection, raw.result.operation_id)
        if read_workspace_registration(connection, intent) is None:
            reference = EngineeringRef(
                kind="operation", object_id=intent.result.operation_id, revision="p1-workspace-operation-r1",
                authority="workspaces", digest=intent.result.request_digest, digest_algorithm="sha256",
            )
            pending.append(OperationClosureFact(operation_ref=reference, owner_kind="task", owner_id=task_id,
                                                affects_completion=True, closure="unknown"))
    return tuple(pending)
