"""Application-owned workspace handoff transactions; the executor supplies snapshots."""

import re
from uuid import uuid4

from sqlalchemy import func, insert, select, update

from database.commands import get_by_id, lock_and_get, save_result
from database.readiness import assert_schema_ready
from database.uow import UnitOfWork
from modules.collaboration.command_support import TaskCommandContext, lock_task_access, update_task
from modules.collaboration.guards import MAX_REVISION, check_task_revisions, require_ordinary_progress, task_resource
from modules.collaboration.input_commands import _advance_input_validity
from modules.collaboration.records import contract_digest
from modules.collaboration.tables import work_items
from modules.identity.actors import actor_for_command
from modules.integration.tables import verification_dependencies
from modules.sync.events import append_event
from modules.workspaces.handoff_gates import active_handoff
from modules.workspaces.handoff_tables import workspace_handoffs
from modules.workspaces.operations import WorkspaceError, current_engineering_input, pending_workspace_operations, read_workspace_row
from modules.workspaces.queries import lock_workspace_read
from modules.workspaces.tables import workspaces
from packages.contracts.p0.decision_common import Contract, Identifier
from packages.contracts.p0.identity_contracts import CommandEnvelope, CommandIntent, request_digest
from packages.contracts.p1.workspace_candidates import CandidateFreezeSpec, candidate_freeze_digest, workspace_runtime_scope_id
from packages.contracts.p1.workspace_git import WorkspaceBinding
from packages.contracts.p1.workspace_records import workspace_metadata_digest
from packages.contracts.p2.handoffs import WorkspaceHandoffRecord, WorkspaceHandoffRequest, WorkspaceHandoffResult


class _ScopedHandoff(Contract):
    workspace_id: Identifier
    request: WorkspaceHandoffRequest


class _HandoffChanged(Contract):
    handoff_id: Identifier
    state: str
    record_digest: str
    change_count: int


def _read(connection, handoff_id):
    raw = connection.scalar(select(workspace_handoffs.c.record_json).where(
        workspace_handoffs.c.handoff_id == handoff_id))
    if raw is None:
        raise WorkspaceError("workspace_handoff_not_found", status_code=404)
    return WorkspaceHandoffRecord.model_validate(raw)


def _operation(connection, operation_id):
    match = re.fullmatch(r"workspace-handoff-(takeover|return)-([0-9a-f]{32})", operation_id)
    if match is None:
        raise WorkspaceError("workspace_handoff_operation_not_found", status_code=404)
    command = get_by_id(connection, match[2])
    if command is None:
        raise WorkspaceError("workspace_handoff_operation_not_found", status_code=404)
    result = WorkspaceHandoffResult.model_validate(command.result)
    record = _read(connection, result.handoff.handoff_id)
    spec = record.takeover_spec if match[1] == "takeover" else record.return_spec
    if spec is None or spec.candidate_id != "handoff-snapshot-" + match[2]:
        raise WorkspaceError("workspace_handoff_operation_mismatch")
    return command, result, record, spec


class WorkspaceHandoffApplication:
    def __init__(self, engine, control_engine, *, enqueue_operation=None):
        self.engine, self.control_engine, self.enqueue_operation = engine, control_engine, enqueue_operation

    def request(self, actor, workspace_id, request: WorkspaceHandoffRequest, *, idempotency_key):
        if actor.principal.kind != "human" or actor.authentication_source != "device_session":
            raise WorkspaceError("workspace_handoff_human_required", status_code=403)
        with UnitOfWork(self.engine) as uow:
            task_id = read_workspace_row(uow.connection, workspace_id)["task_id"]
            task, authorization = lock_task_access(uow, actor, task_id, "workspace.write")
            workspace = read_workspace_row(uow.connection, workspace_id, for_update=True)
            resource = task_resource(task)
            intent = CommandIntent(request_schema_revision="p2-workspace-handoff-r1", caller=actor.principal,
                scope=resource.scope, target=resource.target_scope, action="workspace.write",
                expected_resource_revision=request.expected_version)
            command = CommandEnvelope(**intent.model_dump(), command_id=uuid4().hex,
                idempotency_key=idempotency_key, request_digest=request_digest(
                    intent, _ScopedHandoff(workspace_id=workspace_id, request=request)))
            existing = lock_and_get(uow.connection, command)
            if existing is not None:
                return WorkspaceHandoffResult.model_validate(existing.result)
            assert_schema_ready(uow.connection)
            context = TaskCommandContext(uow, actor, task, authorization, command)
            record = self._accept(context, workspace, request)
            result = WorkspaceHandoffResult(command_id=command.command_id, version=context.task["version"],
                control_revision=context.task["control_revision"],
                input_validity_revision=context.task["input_validity_revision"], handoff=record)
            save_result(uow.connection, command, result, status_code=202, authorization=authorization.envelope)
            append_event(uow.connection, command_id=command.command_id, project_id=task["project_id"],
                aggregate_kind="workspace", aggregate_id=workspace_id,
                aggregate_version=record.takeover_spec.binding.workspace_revision,
                event_type="workspace.handoff_requested", schema_version="p2-workspace-handoff-r1", payload=result)
            if self.enqueue_operation is not None:
                spec = record.takeover_spec if request.action == "takeover" else record.return_spec
                self.enqueue_operation(uow, "workspace-handoff-" + request.action + "-" + command.command_id,
                    command.command_id, workspace_id, context.task["version"], candidate_freeze_digest(spec))
            return result

    def _accept(self, context, workspace, request):
        connection, task = context.uow.connection, context.task
        if request.action == "takeover":
            require_ordinary_progress(connection, task["task_id"], expected_version=request.expected_version,
                expected_control_revision=request.expected_control_revision,
                expected_input_validity_revision=request.expected_input_validity_revision, allowed_states=("draft", "active"))
        else:
            check_task_revisions(task, expected_version=request.expected_version,
                expected_control_revision=request.expected_control_revision,
                expected_input_validity_revision=request.expected_input_validity_revision)
        current_engineering_input(connection, task, request.input_set_ref)
        binding = WorkspaceBinding.model_validate(workspace["binding_json"])
        if (binding.workspace_revision != request.expected_workspace_revision
                or binding.write_generation != request.expected_write_generation):
            raise WorkspaceError("workspace_revision_conflict")
        if workspace["files_json"] is None:
            raise WorkspaceError("workspace_not_materialized")
        # Existing writes must first reach their original terminal receipt; never cancel or replay unknown work.
        from modules.workspaces.development_queries import pending_development_operations
        from modules.workspaces.operations import read_workspace_operation
        from modules.workspaces.development_tables import workspace_development_environment_operations

        for fact in pending_workspace_operations(connection, task["task_id"]):
            value, _ = read_workspace_operation(connection, fact.operation_ref.object_id)
            if value.result.workspace_id == binding.workspace_id:
                raise WorkspaceError("workspace_operation_pending")
        pending_development = {fact.operation_ref.object_id for fact in pending_development_operations(connection, task["task_id"])}
        if pending_development and connection.scalar(select(workspace_development_environment_operations.c.operation_id).where(
            workspace_development_environment_operations.c.workspace_id == binding.workspace_id,
            workspace_development_environment_operations.c.operation_id.in_(pending_development)).limit(1)):
            raise WorkspaceError("workspace_operation_pending")
        if max(binding.workspace_revision, binding.write_generation) == MAX_REVISION:
            raise WorkspaceError("revision_exhausted")
        spec = CandidateFreezeSpec(binding=binding, materialization_operation_id=workspace["materialization_operation_id"],
            candidate_id="handoff-snapshot-" + context.envelope.command_id,
            expected_manifest_digest=request.expected_manifest_digest, runtime_scope_id=workspace_runtime_scope_id(binding))
        record = active_handoff(connection, binding.workspace_id)
        if request.action == "takeover":
            if record is not None:
                raise WorkspaceError("workspace_write_ownership_conflict")
            record = WorkspaceHandoffRecord(handoff_id="handoff-" + context.envelope.command_id,
                workspace_id=binding.workspace_id, task_id=task["task_id"], human_user_id=context.actor.principal.subject_id,
                reason=request.reason, state="handoff_pending", takeover_spec=spec,
                created_at=connection.scalar(select(func.clock_timestamp())))
            connection.execute(insert(workspace_handoffs).values(handoff_id=record.handoff_id,
                workspace_id=record.workspace_id, task_id=record.task_id, state=record.state,
                record_json=record.model_dump(mode="json"), created_at=record.created_at))
        else:
            if (record is None or record.handoff_id != request.handoff_id or record.state != "human_owned"
                    or record.human_user_id != context.actor.principal.subject_id):
                raise WorkspaceError("workspace_write_ownership_conflict")
            record = record.model_copy(update={"state": "return_pending", "return_spec": spec})
            connection.execute(update(workspace_handoffs).where(workspace_handoffs.c.handoff_id == record.handoff_id).values(
                state=record.state, record_json=record.model_dump(mode="json")))
        update_task(context, operation_set_revision=task["operation_set_revision"] + 1)
        return record

    def query(self, actor, workspace_id, handoff_id):
        with UnitOfWork(self.control_engine) as uow:
            lock_workspace_read(uow, actor, workspace_id)
            record = _read(uow.connection, handoff_id)
            if record.workspace_id != workspace_id:
                raise WorkspaceError("workspace_handoff_not_found", status_code=404)
            return record

    def record_for_operation(self, operation_id):
        with UnitOfWork(self.control_engine) as uow:
            command, _, record, _ = _operation(uow.connection, operation_id)
            lock_task_access(uow, actor_for_command(uow, command.envelope.command_id), record.task_id, "workspace.write")
            return record

    def resolve(self, operation_id, *, reconciliation=False):
        with UnitOfWork(self.control_engine) as uow:
            command, result, record, spec = _operation(uow.connection, operation_id)
            task, _ = lock_task_access(uow, actor_for_command(uow, command.envelope.command_id), record.task_id, "workspace.write")
            workspace = read_workspace_row(uow.connection, record.workspace_id, for_update=True)
            if not reconciliation:
                returning = spec == record.return_spec
                expected = "return_pending" if returning else "handoff_pending"
                if record.state != expected or WorkspaceBinding.model_validate(workspace["binding_json"]) != spec.binding:
                    raise WorkspaceError("workspace_handoff_binding_stale")
                if not returning:
                    require_ordinary_progress(uow.connection, task["task_id"], expected_version=task["version"],
                        expected_control_revision=result.control_revision,
                        expected_input_validity_revision=result.input_validity_revision, allowed_states=("draft", "active"))
            return spec

    def finish(self, operation_id, store, *, changes=()):
        from modules.workspaces.candidate_store import CandidateStore

        if type(store) is not CandidateStore:
            raise WorkspaceError("verified_workspace_receipt_required")
        status = store.query(operation_id)
        if status.state != "captured":
            raise WorkspaceError("workspace_handoff_outcome_unknown")
        receipt = status.receipt
        with UnitOfWork(self.engine) as uow:
            command, _, record, spec = _operation(uow.connection, operation_id)
            actor = actor_for_command(uow, command.envelope.command_id)
            task, authorization = lock_task_access(uow, actor, record.task_id, "workspace.write")
            workspace = read_workspace_row(uow.connection, record.workspace_id, for_update=True)
            returning = spec == record.return_spec
            previous = record.returned if returning else record.baseline
            if previous is not None:
                if previous != receipt:
                    raise WorkspaceError("workspace_handoff_receipt_conflict")
                return record
            if (receipt.operation_id != operation_id or receipt.request_digest != candidate_freeze_digest(spec)
                    or receipt.snapshot.binding != spec.binding or receipt.snapshot.candidate_id != spec.candidate_id
                    or receipt.snapshot.manifest_digest != spec.expected_manifest_digest
                    or WorkspaceBinding.model_validate(workspace["binding_json"]) != spec.binding
                    or record.state != ("return_pending" if returning else "handoff_pending")):
                raise WorkspaceError("workspace_handoff_receipt_conflict")
            binding = spec.binding.model_copy(update={"workspace_revision": spec.binding.workspace_revision + 1,
                                                      "write_generation": spec.binding.write_generation + 1})
            uow.connection.execute(update(workspaces).where(workspaces.c.workspace_id == record.workspace_id).values(
                workspace_revision=binding.workspace_revision, write_generation=binding.write_generation,
                binding_json=binding.model_dump(mode="json"), binding_digest=workspace_metadata_digest(binding)))
            context = TaskCommandContext(uow, actor, task, authorization, command.envelope)
            if returning and task["state"] not in {"completed", "cancelled"}:
                _advance_input_validity(context, operation_set_revision=task["operation_set_revision"] + 1)
                uow.connection.execute(update(verification_dependencies).where(
                    verification_dependencies.c.task_id == record.task_id).values(applicability="needs_review"))
                uow.connection.execute(update(work_items).where(work_items.c.work_item_id == binding.work_item_id).values(
                    state="ready", revision=work_items.c.revision + 1))
            else:
                update_task(context, operation_set_revision=task["operation_set_revision"] + 1)
            record = record.model_copy(update={"state": "agent_owned" if returning else "human_owned",
                **({"returned": receipt, "changes": tuple(changes)} if returning else {"baseline": receipt})})
            uow.connection.execute(update(workspace_handoffs).where(workspace_handoffs.c.handoff_id == record.handoff_id).values(
                state=record.state, record_json=record.model_dump(mode="json")))
            append_event(uow.connection, command_id=command.envelope.command_id, project_id=binding.project_id,
                aggregate_kind="workspace", aggregate_id=binding.workspace_id, aggregate_version=binding.workspace_revision,
                event_type="workspace.handoff_confirmed", schema_version="p2-workspace-handoff-r1",
                payload=_HandoffChanged(handoff_id=record.handoff_id, state=record.state,
                    record_digest=contract_digest(record), change_count=len(record.changes)))
            return record
