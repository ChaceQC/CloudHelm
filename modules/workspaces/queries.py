"""Authorized workspace metadata and original-operation queries."""

from typing import Literal

from sqlalchemy import select

from modules.collaboration.command_support import lock_task_access
from modules.collaboration.tables import work_items
from modules.identity.actors import AuthoritativeResource
from modules.identity.authorization import authorize_current
from modules.workspaces.operations import (
    WorkspaceError, pending_workspace_operations, read_workspace_operation, read_workspace_row,
)
from modules.workspaces.receipts import WorkspaceOperationRegistration, read_workspace_registration
from packages.contracts.p0.decision_common import Contract
from packages.contracts.p0.engineering_contracts import UtcTimestamp
from packages.contracts.p1.workspace_git import WorkspaceReadSpec
from packages.contracts.p1.workspace_records import PhysicalCandidateRecord, WorkspaceRecord
from packages.contracts.p1.workspace_requests import WorkspaceCommandResult, WorkspaceView


class WorkspaceOperationView(Contract):
    result: WorkspaceCommandResult
    accepted_at: UtcTimestamp
    state: Literal["accepted", "registered"]
    registration: WorkspaceOperationRegistration | None = None


def workspace_record(row):
    return WorkspaceRecord(
        binding=row["binding_json"], binding_digest=row["binding_digest"],
        files=row["files_json"], files_digest=row["files_digest"],
        created_by_command_id=row["created_by_command_id"], authorization_decision_id=row["authorization_decision_id"],
        created_at=row["created_at"],
    )


def lock_workspace_read(uow, actor, workspace_id):
    initial = read_workspace_row(uow.connection, workspace_id)
    task, _ = lock_task_access(uow, actor, initial["task_id"], "resource.read")
    row = read_workspace_row(uow.connection, workspace_id, for_update=True)
    if row["task_id"] != task["task_id"] or row["project_id"] != task["project_id"]:
        raise WorkspaceError("workspace_task_binding_mismatch")
    return task, row


def query_workspace_in_uow(uow, actor, workspace_id):
    task, row = lock_workspace_read(uow, actor, workspace_id)
    record = workspace_record(row)
    item = uow.connection.execute(select(work_items).where(
        work_items.c.work_item_id == record.binding.work_item_id,
        work_items.c.task_id == task["task_id"],
    )).mappings().one()
    pending = []
    for operation in pending_workspace_operations(uow.connection, task["task_id"]):
        intent, _ = read_workspace_operation(uow.connection, operation.operation_ref.object_id)
        if intent.result.workspace_id == workspace_id:
            pending.append(intent.result.operation_id)
    return WorkspaceView(
        workspace=record, task_version=task["version"], control_revision=task["control_revision"],
        input_validity_revision=task["input_validity_revision"], work_item_revision=item["revision"],
        work_item_state=item["state"], pending_operation_ids=tuple(pending),
    )


def query_workspace_operation_in_uow(uow, actor, workspace_id, operation_id):
    task, _ = lock_workspace_read(uow, actor, workspace_id)
    resource = AuthoritativeResource(task["project_id"], "operation", operation_id, task_id=task["task_id"])
    authorize_current(uow, actor, resource, "operation.query")
    intent, accepted_at = read_workspace_operation(uow.connection, operation_id)
    if intent.result.workspace_id != workspace_id or intent.result.task_id != task["task_id"]:
        raise WorkspaceError("workspace_operation_not_found", status_code=404)
    registration = read_workspace_registration(uow.connection, intent)
    return WorkspaceOperationView(result=intent.result, accepted_at=accepted_at,
                                  state="registered" if registration else "accepted", registration=registration)


def workspace_read_spec_in_uow(uow, actor, workspace_id):
    _, row = lock_workspace_read(uow, actor, workspace_id)
    record = workspace_record(row)
    if record.files is None:
        raise WorkspaceError("workspace_not_materialized")
    return WorkspaceReadSpec(binding=record.binding, materialization_operation_id=record.files.operation_id)


def read_physical_candidate_in_uow(uow, actor, workspace_id, candidate_id):
    from modules.workspaces.tables import workspace_candidates

    lock_workspace_read(uow, actor, workspace_id)
    row = uow.connection.execute(select(workspace_candidates).where(
        workspace_candidates.c.workspace_id == workspace_id, workspace_candidates.c.candidate_id == candidate_id,
    )).mappings().one_or_none()
    if row is None:
        raise WorkspaceError("workspace_candidate_not_found", status_code=404)
    return PhysicalCandidateRecord(
        snapshot=row["snapshot_json"], snapshot_digest=row["snapshot_digest"],
        created_by_command_id=row["created_by_command_id"], authorization_decision_id=row["authorization_decision_id"],
        created_at=row["created_at"],
    )
