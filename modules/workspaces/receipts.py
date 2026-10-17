"""Verify original physical queries, then register facts in a short transaction."""

from dataclasses import dataclass, field

import rfc8785
from pydantic import StrictBool, model_validator
from sqlalchemy import insert, select, update

from database.readiness import assert_schema_ready
from database.uow import require_transaction
from modules.collaboration.command_support import TaskCommandContext, update_task
from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.guards import MAX_REVISION
from modules.collaboration.tables import work_items
from modules.sync.events import append_event
from modules.sync.tables import event_log
from modules.workspaces.file_operations import WorkspaceFileService
from modules.workspaces.operations import (
    WorkspaceError, candidate_spec, current_engineering_input, resolve_workspace_operation_in_uow,
)
from modules.workspaces.tables import workspace_candidates, workspaces
from modules.workspaces.workfiles import WorkfileStore
from packages.contracts.p0.decision_common import Contract, Digest, Identifier, Revision
from packages.contracts.p1.workspace_candidates import CandidateFreezeReceipt
from packages.contracts.p1.workspace_git import WorkspaceBinding, WorkspaceFiles, WorkspaceMutationReceipt, content_digest
from packages.contracts.p1.workspace_records import workspace_metadata_digest

RECEIPT_SCHEMA = "p1-workspace-receipt-event-r1"
_PHYSICAL_PROOF = object()
Receipt = WorkspaceFiles | WorkspaceMutationReceipt | CandidateFreezeReceipt


def receipt_digest(receipt):
    return content_digest(rfc8785.dumps(receipt.model_dump(mode="json")))


class WorkspaceOperationRegistration(Contract):
    operation_id: Identifier
    request_digest: Digest
    receipt_digest: Digest
    receipt: Receipt
    applicable: StrictBool
    binding_after: WorkspaceBinding
    registered_task_version: Revision

    @model_validator(mode="after")
    def check_digest(self):
        if self.receipt_digest != receipt_digest(self.receipt):
            raise ValueError("workspace_receipt_digest_mismatch")
        return self


@dataclass(frozen=True, slots=True)
class _VerifiedWorkspaceReceipt:
    operation_id: str
    receipt: Receipt
    _proof: object = field(repr=False, compare=False)

    def __post_init__(self):
        if self._proof is not _PHYSICAL_PROOF:
            raise WorkspaceError("verified_workspace_receipt_required")


def verify_materialization(operation_id, binding, store):
    if type(store) is not WorkfileStore:
        raise WorkspaceError("trusted_workfile_store_required")
    receipt = store.query(binding, operation_id)
    receipt = WorkspaceFiles.model_validate(receipt.model_dump(mode="python"))
    if receipt.operation_id != operation_id or receipt.binding != binding:
        raise WorkspaceError("workspace_receipt_binding_mismatch")
    return _VerifiedWorkspaceReceipt(operation_id, receipt, _PHYSICAL_PROOF)


def verify_mutation(operation_id, service):
    if type(service) is not WorkspaceFileService:
        raise WorkspaceError("trusted_workspace_file_service_required")
    status = service.query(operation_id)
    if (status.operation_id != operation_id or status.state not in {"applied", "not_applied"}
            or status.receipt is None or status.receipt.outcome != status.state):
        raise WorkspaceError("workspace_mutation_unsettled")
    receipt = WorkspaceMutationReceipt.model_validate(status.receipt.model_dump(mode="python"))
    if receipt.operation_id != operation_id or receipt.request_digest != status.request_digest:
        raise WorkspaceError("workspace_receipt_binding_mismatch")
    return _VerifiedWorkspaceReceipt(operation_id, receipt, _PHYSICAL_PROOF)


def verify_candidate(operation_id, store):
    from modules.workspaces.candidate_store import CandidateStore

    if type(store) is not CandidateStore:
        raise WorkspaceError("trusted_candidate_store_required")
    status = store.query(operation_id)
    if status.operation_id != operation_id or status.state != "captured" or status.receipt is None:
        raise WorkspaceError("workspace_candidate_unsettled")
    receipt = CandidateFreezeReceipt.model_validate(status.receipt.model_dump(mode="python"))
    if receipt.operation_id != operation_id or receipt.request_digest != status.request_digest:
        raise WorkspaceError("workspace_receipt_binding_mismatch")
    return _VerifiedWorkspaceReceipt(operation_id, receipt, _PHYSICAL_PROOF)


def _check_receipt(intent, receipt):
    result, request = intent.result, intent.request
    if result.kind == "materialize":
        valid = (type(receipt) is WorkspaceFiles and receipt.binding == result.binding
                 and receipt.operation_id == result.operation_id)
    elif result.kind == "mutate":
        valid = (type(receipt) is WorkspaceMutationReceipt and receipt.binding == result.binding
                 and receipt.operation_id == result.operation_id and receipt.request_digest == result.request_digest
                 and receipt.materialization_operation_id == intent.materialization_operation_id
                 and receipt.action == request.action and receipt.path == request.path
                 and receipt.before_manifest_digest == request.expected_manifest_digest
                 and receipt.before_file == request.expected_file)
        if valid:
            expected = request.replacement if receipt.outcome == "applied" else request.expected_file
            valid = receipt.after_file == expected
            if receipt.outcome == "not_applied":
                valid = valid and receipt.after_manifest_digest == receipt.before_manifest_digest
    else:
        spec = candidate_spec(intent)
        valid = (type(receipt) is CandidateFreezeReceipt and receipt.operation_id == result.operation_id
                 and receipt.request_digest == result.request_digest and receipt.snapshot.binding == result.binding
                 and receipt.materialization_operation_id == intent.materialization_operation_id
                 and receipt.runtime_scope_id == intent.runtime_scope_id
                 and receipt.snapshot.candidate_id == spec.candidate_id
                 and receipt.snapshot.freeze_operation_id == result.operation_id
                 and receipt.snapshot.parent_commit == result.binding.base_commit
                 and receipt.snapshot.manifest_digest == request.expected_manifest_digest)
    if not valid:
        raise WorkspaceError("workspace_receipt_binding_mismatch")


def read_workspace_registration(connection, intent):
    require_transaction(connection)
    event = connection.execute(select(event_log).where(
        event_log.c.event_id == "workspace-receipt-" + intent.result.command_id,
    )).mappings().one_or_none()
    if event is None:
        return None
    try:
        value = WorkspaceOperationRegistration.model_validate(event["payload"])
        result = intent.result
        if not all((event["command_id"] == result.command_id, event["project_id"] == result.binding.project_id,
                    event["aggregate_kind"] == "workspace", event["aggregate_id"] == result.workspace_id,
                    event["aggregate_version"] == value.binding_after.workspace_revision,
                    event["event_type"] == "workspace.operation_registered", event["schema_version"] == RECEIPT_SCHEMA,
                    value.operation_id == result.operation_id, value.request_digest == result.request_digest)):
            raise ValueError
        _check_receipt(intent, value.receipt)
        expected = intent.result.binding
        if type(value.receipt) is WorkspaceMutationReceipt and value.receipt.outcome == "applied":
            expected = expected.model_copy(update={"workspace_revision": expected.workspace_revision + 1,
                                                   "write_generation": expected.write_generation + 1})
        if value.binding_after != expected or value.registered_task_version <= intent.result.version:
            raise ValueError
        return value
    except (ValueError, TypeError, KeyError):
        raise WorkspaceError("workspace_receipt_fact_invalid") from None


def _applicable(connection, task, intent):
    if (task["state"] not in {"draft", "active"} or task["ordinary_progress_closed"]
            or task["cancel_requested_at"] is not None
            or task["control_revision"] != intent.request.expected_control_revision
            or task["input_validity_revision"] != intent.request.expected_input_validity_revision
            or task["input_status"] != "valid"):
        return False
    try:
        current_engineering_input(connection, task, intent.request.input_set_ref)
    except TaskBoundaryError:
        return False
    return True


def _save_physical_metadata(uow, intent, workspace, receipt, authorization):
    binding = WorkspaceBinding.model_validate(workspace["binding_json"])
    if binding != intent.result.binding:
        raise WorkspaceError("workspace_receipt_binding_stale")
    if type(receipt) is WorkspaceFiles:
        if workspace["files_json"] is not None:
            raise WorkspaceError("workspace_materialization_conflict")
        uow.connection.execute(update(workspaces).where(workspaces.c.workspace_id == binding.workspace_id).values(
            files_json=receipt.model_dump(mode="json"), files_digest=workspace_metadata_digest(receipt),
            materialization_operation_id=receipt.operation_id, storage_id=receipt.storage_id,
        ))
    elif type(receipt) is WorkspaceMutationReceipt and receipt.outcome == "applied":
        if max(binding.workspace_revision, binding.write_generation) == MAX_REVISION:
            raise WorkspaceError("revision_exhausted")
        binding = WorkspaceBinding.model_validate({**binding.model_dump(),
                                                  "workspace_revision": binding.workspace_revision + 1,
                                                  "write_generation": binding.write_generation + 1})
        uow.connection.execute(update(workspaces).where(workspaces.c.workspace_id == binding.workspace_id).values(
            workspace_revision=binding.workspace_revision, write_generation=binding.write_generation,
            binding_json=binding.model_dump(mode="json"), binding_digest=workspace_metadata_digest(binding),
        ))
    elif type(receipt) is CandidateFreezeReceipt:
        snapshot = receipt.snapshot
        uow.connection.execute(insert(workspace_candidates).values(
            candidate_id=snapshot.candidate_id, **snapshot.binding.model_dump(exclude={"base_commit"}),
            candidate_commit=snapshot.candidate_commit, parent_commit=snapshot.parent_commit,
            freeze_operation_id=snapshot.freeze_operation_id, storage_id=snapshot.storage_id,
            snapshot_json=snapshot.model_dump(mode="json"), snapshot_digest=workspace_metadata_digest(snapshot),
            created_by_command_id=intent.result.command_id, authorization_decision_id=authorization.envelope.decision_id,
        ))
    return binding


def register_workspace_receipt_in_uow(uow, operation_id, verified):
    """A late terminal fact is archived without restoring ordinary Task progress."""
    require_transaction(uow.connection)
    if type(verified) is not _VerifiedWorkspaceReceipt or verified._proof is not _PHYSICAL_PROOF:
        raise WorkspaceError("verified_workspace_receipt_required")
    if verified.operation_id != operation_id:
        raise WorkspaceError("workspace_receipt_binding_mismatch")
    intent, task, workspace, authorization = resolve_workspace_operation_in_uow(uow, operation_id, reconciliation=True)
    _check_receipt(intent, verified.receipt)
    existing = read_workspace_registration(uow.connection, intent)
    if existing is not None:
        if existing.receipt_digest != receipt_digest(verified.receipt):
            raise WorkspaceError("workspace_physical_digest_conflict")
        return existing
    assert_schema_ready(uow.connection)
    applicable = _applicable(uow.connection, task, intent)
    binding = _save_physical_metadata(uow, intent, workspace, verified.receipt, authorization)
    from database.commands import get_by_id
    from modules.identity.actors import actor_for_command

    command = get_by_id(uow.connection, intent.result.command_id)
    context = TaskCommandContext(uow, actor_for_command(uow, intent.result.command_id), task, authorization, command.envelope)
    update_task(context, operation_set_revision=task["operation_set_revision"] + 1)
    if applicable:
        state = "submitted" if intent.result.kind == "candidate" else "running"
        uow.connection.execute(update(work_items).where(
            work_items.c.work_item_id == binding.work_item_id,
            work_items.c.state.in_(("ready", "running", "submitted")),
        ).values(revision=work_items.c.revision + 1, state=state))
    value = WorkspaceOperationRegistration(
        operation_id=operation_id, request_digest=intent.result.request_digest, receipt_digest=receipt_digest(verified.receipt),
        receipt=verified.receipt, applicable=applicable, binding_after=binding, registered_task_version=context.task["version"],
    )
    append_event(uow.connection, command_id=intent.result.command_id, project_id=binding.project_id,
                 aggregate_kind="workspace", aggregate_id=binding.workspace_id, aggregate_version=binding.workspace_revision,
                 event_type="workspace.operation_registered", schema_version=RECEIPT_SCHEMA,
                 event_id="workspace-receipt-" + intent.result.command_id, payload=value)
    return value
