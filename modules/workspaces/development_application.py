"""Workspace development application facade, preflight, and current Task guards."""

from uuid import uuid4

from sqlalchemy import select

from database.commands import save_result
from database.readiness import assert_schema_ready
from database.uow import UnitOfWork
from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.facts import read_task
from modules.collaboration.guards import MAX_REVISION, check_task_revisions, require_ordinary_progress
from modules.collaboration.tables import work_items
from modules.identity.actors import validate_actor
from modules.workspaces.development_commands import (
    development_command_result, development_operation_request, prepare_development_command_context,
    prepared_development_spec, store_development_operation, validated_development_request,
)
from modules.workspaces.development_queries import (
    WorkspaceDevelopmentError, pending_development_operations,
    query_development_environment_in_uow,
    query_development_operation_in_uow, read_development_environment, read_development_operation_record,
)
from modules.workspaces.development_tables import workspace_development_environments as environment_table
from modules.workspaces.operations import (
    current_engineering_input, pending_workspace_operations, read_workspace_operation, read_workspace_row,
)
from packages.contracts.p1.workspace_development_requests import (
    PrepareWorkspaceDevelopmentRequest, WorkspaceDevelopmentControlRequest, WorkspaceDevelopmentHttpResult,
)
from packages.contracts.p1.workspace_git import WorkspaceBinding


def _workspace_binding(context, request, workspace_id, *, environment=None):
    connection, task = context.uow.connection, context.task
    workspace = read_workspace_row(connection, workspace_id, for_update=True)
    if workspace["task_id"] != task["task_id"] or workspace["project_id"] != task["project_id"]:
        raise WorkspaceDevelopmentError("workspace_development_workspace_not_found", status_code=404)
    binding = WorkspaceBinding.model_validate(workspace["binding_json"])
    if (binding.workspace_revision != request.expected_workspace_revision
            or binding.write_generation != request.expected_write_generation):
        raise WorkspaceDevelopmentError("workspace_development_workspace_generation_conflict")
    if request.action not in {"suspend", "dispose"}:
        from modules.workspaces.handoff_gates import require_workspace_writer

        require_workspace_writer(connection, workspace, context.actor, "development")
        item = connection.execute(select(work_items).where(
            work_items.c.work_item_id == binding.work_item_id, work_items.c.task_id == task["task_id"],
        ).with_for_update()).mappings().one_or_none()
        if item is None or item["state"] not in {"ready", "running", "submitted"}:
            raise WorkspaceDevelopmentError("workspace_development_work_item_closed")
        if max(item["revision"], binding.workspace_revision, binding.write_generation) >= MAX_REVISION:
            raise WorkspaceDevelopmentError("revision_exhausted")
    if environment is not None:
        if (environment["workspace_id"] != workspace_id or environment["task_id"] != task["task_id"]
                or environment["project_id"] != task["project_id"]):
            raise WorkspaceDevelopmentError("workspace_development_environment_scope_mismatch")
    return workspace, binding


def _guard(context, request, workspace_id, *, environment=None):
    connection, task = context.uow.connection, context.task
    assert_schema_ready(connection)
    cleanup = request.action in {"suspend", "dispose"}
    if cleanup:
        check_task_revisions(
            task, expected_version=request.expected_version,
            expected_control_revision=request.expected_control_revision,
            expected_input_validity_revision=request.expected_input_validity_revision,
        )
    else:
        task = require_ordinary_progress(
            connection, task["task_id"], expected_version=request.expected_version,
            expected_control_revision=request.expected_control_revision,
            expected_input_validity_revision=request.expected_input_validity_revision,
            allowed_states=("draft", "active"),
        )
        context.task = task
        registration = current_engineering_input(connection, task, request.input_set_ref)
    workspace, binding = _workspace_binding(context, request, workspace_id, environment=environment)
    if not cleanup:
        source = registration.source_record.source
        if (source.source_id != binding.source_id or source.source_revision != binding.source_revision
                or registration.source_ref.revision != binding.base_commit):
            raise WorkspaceDevelopmentError("workspace_development_source_input_mismatch")
    for pending in pending_workspace_operations(connection, task["task_id"]):
        operation, _ = read_workspace_operation(connection, pending.operation_ref.object_id)
        if operation.result.workspace_id == workspace_id:
            raise WorkspaceDevelopmentError("workspace_operation_pending")
    for pending in pending_development_operations(connection, task["task_id"]):
        _, _, row, _, _ = read_development_operation_record(connection, pending.operation_ref.object_id)
        if row["workspace_id"] == workspace_id:
            raise WorkspaceDevelopmentError("workspace_development_operation_pending")
    return workspace, binding


def _guard_environment_control(request, environment):
    if environment["state"] == "disposed":
        raise WorkspaceDevelopmentError("workspace_development_environment_disposed")
    if request.expected_environment_revision != environment["environment_revision"]:
        raise WorkspaceDevelopmentError("workspace_development_revision_conflict")
    if (request.expected_data_revision != environment["data_revision"]
            or request.expected_data_generation != environment["data_generation"]):
        raise WorkspaceDevelopmentError("workspace_development_data_revision_conflict")
    allowed = {
        "suspend": {"ready", "failed", "preparing"},
        "resume": {"ready", "suspended", "failed"},
        "reset_data": {"ready", "suspended", "failed"},
        "dispose": {"preparing", "ready", "suspended", "failed"},
    }
    if environment["state"] not in allowed[request.action]:
        raise WorkspaceDevelopmentError("workspace_development_state_conflict")


def _accept(uow, actor, task_id, request, *, idempotency_key, command_id, workspace_id,
            environment_id, spec, resolver_error, enqueue_operation):
    context, existing = prepare_development_command_context(
        uow, actor, task_id, request, idempotency_key, command_id,
        workspace_id=workspace_id, environment_id=environment_id,
    )
    if existing is not None:
        return existing
    try:
        with uow.connection.begin_nested():
            environment = None if request.action == "prepare" else read_development_environment(
                uow.connection, environment_id,
            )
            workspace, binding = _guard(context, request, workspace_id, environment=environment)
            if resolver_error is None and request.action not in {"suspend", "dispose"} and (
                spec is None or spec.binding != binding or spec.environment_id != environment_id
            ):
                raise WorkspaceDevelopmentError("workspace_development_metadata_stale")
            environment = None if request.action == "prepare" else read_development_environment(
                uow.connection, environment_id, for_update=True,
            )
            if environment is None and request.action != "prepare":
                raise WorkspaceDevelopmentError("workspace_development_environment_not_found", status_code=404)
            if environment is None:
                open_environment = uow.connection.scalar(select(environment_table.c.environment_id).where(
                    environment_table.c.workspace_id == workspace_id,
                    environment_table.c.state != "disposed",
                ).limit(1))
                if open_environment is not None:
                    raise WorkspaceDevelopmentError("workspace_development_environment_already_open")
            else:
                _guard_environment_control(request, environment)
            if resolver_error is not None:
                raise resolver_error
            assert_schema_ready(uow.connection)
            accepted = store_development_operation(
                context, request, development_operation_request(
                    request, command_id, environment_id, binding, spec, environment,
                ), binding, environment, spec, enqueue_operation is not None,
            )
    except TaskBoundaryError as error:
        context.task = read_task(uow.connection, task_id, for_update=True)
        result = development_command_result(
            context, request, "rejected", error.code, workspace_id, environment_id,
        )
        save_result(uow.connection, context.envelope, result, status_code=error.status_code,
                    authorization=context.authorization.envelope)
        return WorkspaceDevelopmentHttpResult(status_code=error.status_code, body=result)
    if enqueue_operation is not None:
        result = accepted.body
        enqueue_operation(
            uow, operation_id=result.operation_id, command_id=result.command_id,
            environment_id=result.environment_id, advance_revision=result.version,
            request_digest=result.request_digest,
        )
    return accepted


def _preflight(engine, actor, task_id, request, *, idempotency_key, command_id, workspace_id, environment_id):
    with UnitOfWork(engine) as uow:
        context, existing = prepare_development_command_context(
            uow, actor, task_id, request, idempotency_key, command_id,
            workspace_id=workspace_id, environment_id=environment_id,
        )
        if existing is not None:
            return existing, None, None
        try:
            environment = None if request.action == "prepare" else read_development_environment(
                uow.connection, environment_id,
            )
            workspace, binding = _guard(context, request, workspace_id, environment=environment)
            if environment is not None:
                environment = read_development_environment(uow.connection, environment_id, for_update=True)
                _guard_environment_control(request, environment)
            else:
                open_environment = uow.connection.scalar(select(environment_table.c.environment_id).where(
                    environment_table.c.workspace_id == workspace_id,
                    environment_table.c.state != "disposed",
                ).limit(1))
                if open_environment is not None:
                    raise WorkspaceDevelopmentError("workspace_development_environment_already_open")
            return None, binding, environment
        except TaskBoundaryError as error:
            context.task = read_task(uow.connection, task_id, for_update=True)
            result = development_command_result(
                context, request, "rejected", error.code, workspace_id, environment_id,
            )
            save_result(uow.connection, context.envelope, result, status_code=error.status_code,
                        authorization=context.authorization.envelope)
            return WorkspaceDevelopmentHttpResult(status_code=error.status_code, body=result), None, None


class WorkspaceDevelopmentApplication:
    """Hub interface for mutable development env intents; Runner facts stay trusted."""

    def __init__(self, engine, control_engine, *, prepared_spec_for=None, runtime_for=None,
                 enqueue_operation=None):
        self.engine, self.control_engine = engine, control_engine
        self.prepared_spec_for, self.runtime_for = prepared_spec_for, runtime_for
        self.enqueue_operation = enqueue_operation

    def prepare(self, actor, workspace_id, request: PrepareWorkspaceDevelopmentRequest, key):
        request = validated_development_request(request, "prepare")
        validate_actor(actor)
        command_id = uuid4().hex
        environment_id = "dev-env-" + command_id
        with UnitOfWork(self.engine) as uow:
            task_id = _initial_workspace_task(uow, workspace_id)
        preflight, binding, environment = _preflight(
            self.engine, actor, task_id, request, idempotency_key=key, command_id=command_id,
            workspace_id=workspace_id, environment_id=None,
        )
        if preflight is not None:
            return preflight
        spec, resolver_error = prepared_development_spec(
            self.prepared_spec_for, binding, request, command_id, environment_id, environment,
        )
        with UnitOfWork(self.engine) as uow:
            return _accept(
                uow, actor, task_id, request, idempotency_key=key, command_id=command_id,
                workspace_id=workspace_id, environment_id=environment_id, spec=spec,
                resolver_error=resolver_error, enqueue_operation=self.enqueue_operation,
            )

    def control(self, actor, environment_id, request: WorkspaceDevelopmentControlRequest, key):
        request = validated_development_request(request, "control")
        validate_actor(actor)
        command_id = uuid4().hex
        with UnitOfWork(self.engine) as uow:
            assert_schema_ready(uow.connection)
            environment = read_development_environment(uow.connection, environment_id)
            task_id, workspace_id = environment["task_id"], environment["workspace_id"]
        preflight, binding, current = _preflight(
            self.engine, actor, task_id, request, idempotency_key=key, command_id=command_id,
            workspace_id=workspace_id, environment_id=environment_id,
        )
        if preflight is not None:
            return preflight
        spec, resolver_error = prepared_development_spec(
            self.prepared_spec_for, binding, request, command_id, environment_id, current,
        )
        with UnitOfWork(self.engine) as uow:
            return _accept(
                uow, actor, task_id, request, idempotency_key=key, command_id=command_id,
                workspace_id=workspace_id, environment_id=environment_id,
                spec=spec, resolver_error=resolver_error, enqueue_operation=self.enqueue_operation,
            )

    def query(self, actor, environment_id):
        with UnitOfWork(self.control_engine) as uow:
            assert_schema_ready(uow.connection)
            return query_development_environment_in_uow(uow, actor, environment_id)

    def query_operation(self, actor, environment_id, operation_id):
        with UnitOfWork(self.control_engine) as uow:
            assert_schema_ready(uow.connection)
            return query_development_operation_in_uow(uow, actor, environment_id, operation_id)

    def read_operation(self, operation_id, *, reconciliation=False):
        from modules.workspaces.development_queries import read_development_operation

        with UnitOfWork(self.control_engine) as uow:
            assert_schema_ready(uow.connection)
            return read_development_operation(uow, operation_id, reconciliation=reconciliation)

    def register_observation(self, operation_id):
        from modules.workspaces.development_receipts import register_development_observation

        if self.runtime_for is None:
            raise WorkspaceDevelopmentError("workspace_development_controller_unavailable")
        controller = self.runtime_for(operation_id)
        return register_development_observation(self.engine, operation_id, controller)


def _initial_workspace_task(uow, workspace_id):
    return read_workspace_row(uow.connection, workspace_id)["task_id"]
