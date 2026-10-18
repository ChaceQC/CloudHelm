"""Command identity, trusted spec conversion, and atomic development intent writes."""

from sqlalchemy import func, insert, update

from database.commands import save_result
from modules.collaboration.command_support import TaskCommandContext, update_task
from modules.sync.events import append_event
from modules.workspaces.development_queries import (
    DEVELOPMENT_OPERATION_EVENT, DEVELOPMENT_OPERATION_EVENT_PREFIX, DEVELOPMENT_OPERATION_SCHEMA,
    WorkspaceDevelopmentError, development_command_digest,
)
from modules.workspaces.development_tables import (
    workspace_development_environment_operations as operation_table,
    workspace_development_environments as environment_table,
)
from packages.contracts.p0.identity_contracts import CommandEnvelope, CommandIntent
from packages.contracts.p1.development_environment import (
    DisposeWorkspaceDevelopmentEnvironment, PrepareWorkspaceDevelopmentEnvironment,
    ResetWorkspaceDevelopmentData, ResumeWorkspaceDevelopmentEnvironment,
    SuspendWorkspaceDevelopmentEnvironment, WorkspaceDevelopmentEnvironmentOperationIntent,
    WorkspaceDevelopmentEnvironmentSpec, workspace_development_operation_digest,
)
from packages.contracts.p1.workspace_development_requests import (
    DisposeWorkspaceDevelopmentRequest, PrepareWorkspaceDevelopmentRequest,
    ResetWorkspaceDevelopmentDataRequest, ResumeWorkspaceDevelopmentRequest,
    SuspendWorkspaceDevelopmentRequest, WorkspaceDevelopmentCommandResult,
    WorkspaceDevelopmentHttpResult,
)
from packages.contracts.p1.workspace_records import workspace_metadata_digest

_REQUEST_SCHEMAS = {action: "p1-workspace-development-" + action + "-r1" for action in (
    "prepare", "suspend", "resume", "reset_data", "dispose",
)}
_PUBLIC_TYPES = {
    "prepare": PrepareWorkspaceDevelopmentRequest,
    "suspend": SuspendWorkspaceDevelopmentRequest,
    "resume": ResumeWorkspaceDevelopmentRequest,
    "reset_data": ResetWorkspaceDevelopmentDataRequest,
    "dispose": DisposeWorkspaceDevelopmentRequest,
}


def validated_development_request(request, expected_type=None):
    allowed = (PrepareWorkspaceDevelopmentRequest,) if expected_type == "prepare" else (
        SuspendWorkspaceDevelopmentRequest, ResumeWorkspaceDevelopmentRequest,
        ResetWorkspaceDevelopmentDataRequest, DisposeWorkspaceDevelopmentRequest,
    ) if expected_type == "control" else tuple(_PUBLIC_TYPES.values())
    if type(request) not in allowed:
        raise WorkspaceDevelopmentError("workspace_development_request_invalid", status_code=422)
    try:
        return type(request).model_validate(request.model_dump(mode="python"))
    except ValueError:
        raise WorkspaceDevelopmentError("workspace_development_request_invalid", status_code=422) from None


def prepare_development_command_context(
    uow, actor, task_id, request, idempotency_key, command_id, *, workspace_id=None, environment_id=None,
):
    from database.commands import CommandConflict, lock_and_get
    from modules.collaboration.command_support import lock_task_access
    from modules.collaboration.guards import task_resource
    from modules.identity.actors import AuthoritativeResource
    from modules.identity.authorization import authorize_current
    from modules.workspaces.development_queries import DEVELOPMENT_OPERATION_ACTION

    task, authorization = lock_task_access(uow, actor, task_id, DEVELOPMENT_OPERATION_ACTION)
    resource = task_resource(task)
    intent = CommandIntent(
        request_schema_revision=_REQUEST_SCHEMAS[request.action], caller=actor.principal,
        scope=resource.scope, target=resource.target_scope, action=DEVELOPMENT_OPERATION_ACTION,
        expected_resource_revision=request.expected_version,
    )
    envelope = CommandEnvelope(
        **intent.model_dump(), command_id=command_id, idempotency_key=idempotency_key,
        request_digest=development_command_digest(
            intent, request, workspace_id=workspace_id, environment_id=environment_id,
        ),
    )
    context = TaskCommandContext(uow, actor, task, authorization, envelope)
    try:
        existing = lock_and_get(uow.connection, envelope)
    except CommandConflict:
        raise WorkspaceDevelopmentError("idempotency_key_conflict") from None
    if existing is None:
        return context, None
    result = WorkspaceDevelopmentCommandResult.model_validate(existing.result)
    if (result.action != request.action
            or workspace_id is not None and result.workspace_id != workspace_id
            or environment_id is not None and result.environment_id != environment_id):
        raise WorkspaceDevelopmentError("workspace_development_result_scope_mismatch")
    if result.operation_id is not None:
        authorize_current(uow, actor, AuthoritativeResource(
            task["project_id"], "operation", result.operation_id, task_id=task_id,
        ), "operation.query")
    return context, WorkspaceDevelopmentHttpResult(status_code=existing.status_code, body=result)


def development_command_result(context, request, outcome, code, workspace_id, environment_id=None,
                               operation_id=None, request_digest=None, environment_revision=None):
    task = context.task
    return WorkspaceDevelopmentCommandResult(
        command_id=context.envelope.command_id, task_id=task["task_id"], workspace_id=workspace_id,
        action=request.action, outcome=outcome, code=code, version=task["version"],
        control_revision=task["control_revision"], input_validity_revision=task["input_validity_revision"],
        environment_id=environment_id, operation_id=operation_id, request_digest=request_digest,
        environment_revision=environment_revision,
    )


def prepared_development_spec(callback, binding, request, command_id, environment_id, environment):
    if request.action in {"suspend", "dispose"}:
        return None, None
    if callback is None:
        return None, WorkspaceDevelopmentError("workspace_development_resolver_unavailable")
    try:
        spec = callback(
            binding=binding, request=request, command_id=command_id,
            environment_id=environment_id, current_environment=environment,
        )
        if type(spec) is not WorkspaceDevelopmentEnvironmentSpec:
            raise ValueError
        spec = WorkspaceDevelopmentEnvironmentSpec.model_validate(spec.model_dump(mode="python"))
        if (spec.environment_id != environment_id or spec.binding != binding
                or spec.profile_revision != "notes-backend-dev-r1"):
            raise ValueError
        if environment is None:
            if spec.data_generation != 0:
                raise ValueError
        elif (spec.storage_ref.model_dump(mode="json") != environment["storage_ref_json"]
              or spec.toolchain.model_dump(mode="json") != environment["toolchain_json"]
              or spec.migration_revision != environment["migration_revision"]
              or spec.data_generation != environment["data_generation"]):
            raise ValueError
        elif request.action != "resume" and (
            spec.original_lock_digest != environment["original_lock_digest"]
            or spec.dependency_cache_key != environment["dependency_cache_key"]
        ):
            raise ValueError
        if request.action == "reset_data" and spec.data_revision != request.target_data_revision:
            raise ValueError
        if environment is not None and request.action != "reset_data" and spec.data_revision != environment["data_revision"]:
            raise ValueError
        return spec, None
    except Exception:
        return None, WorkspaceDevelopmentError("workspace_development_metadata_unavailable")


def development_operation_request(request, command_id, environment_id, binding, spec, environment):
    common = dict(
        command_id=command_id, operation_id="workspace-dev-env-" + request.action + "-" + command_id,
        environment_id=environment_id, binding=binding,
        source_manifest_digest=(spec.source_manifest_digest if spec is not None
                                else environment["source_manifest_digest"]),
    )
    if request.action == "prepare":
        return PrepareWorkspaceDevelopmentEnvironment(
            **common, expected_environment_revision=0, spec=spec,
        )
    values = dict(
        **common, expected_environment_revision=request.expected_environment_revision,
        expected_data_revision=request.expected_data_revision,
        expected_data_generation=request.expected_data_generation,
    )
    if request.action == "suspend":
        return SuspendWorkspaceDevelopmentEnvironment(**values)
    if request.action == "resume":
        return ResumeWorkspaceDevelopmentEnvironment(**values, spec=spec)
    if request.action == "reset_data":
        return ResetWorkspaceDevelopmentData(**values, target_data_revision=request.target_data_revision)
    return DisposeWorkspaceDevelopmentEnvironment(**values)


def store_development_operation(context, client_request, internal_request, binding, environment, spec, has_enqueue):
    connection, task = context.uow.connection, context.task
    command_id, action = context.envelope.command_id, client_request.action
    operation_id = internal_request.operation_id
    operation_digest = workspace_development_operation_digest(internal_request)
    expected_revision = 0 if environment is None else environment["environment_revision"]
    accepted_revision = expected_revision + 1
    update_task(context, operation_set_revision=task["operation_set_revision"] + 1)
    if environment is None:
        connection.execute(insert(environment_table).values(
            environment_id=internal_request.environment_id, project_id=task["project_id"],
            task_id=task["task_id"], workspace_id=binding.workspace_id, work_item_id=binding.work_item_id,
            owner_user_id=binding.owner_user_id, source_id=binding.source_id, source_revision=binding.source_revision,
            workspace_revision=binding.workspace_revision, write_generation=binding.write_generation,
            binding_json=binding.model_dump(mode="json"), binding_digest=workspace_metadata_digest(binding),
            profile_revision=spec.profile_revision, storage_ref_json=spec.storage_ref.model_dump(mode="json"),
            toolchain_json=spec.toolchain.model_dump(mode="json"), toolchain_digest=spec.toolchain.artifact_digest,
            source_manifest_digest=spec.source_manifest_digest, original_lock_digest=spec.original_lock_digest,
            dependency_cache_key=spec.dependency_cache_key, migration_revision=spec.migration_revision,
            data_revision=spec.data_revision, data_generation=spec.data_generation,
            environment_revision=accepted_revision, state="preparing", created_by_command_id=command_id,
            authorization_decision_id=context.authorization.envelope.decision_id,
        ))
    else:
        result = connection.execute(update(environment_table).where(
            environment_table.c.environment_id == internal_request.environment_id,
            environment_table.c.environment_revision == expected_revision,
        ).values(environment_revision=accepted_revision, updated_at=func.now()))
        if result.rowcount != 1:
            raise WorkspaceDevelopmentError("workspace_development_revision_conflict")
    stored_request = {
        **internal_request.model_dump(mode="json"),
        "client_request": client_request.model_dump(mode="json"),
    }
    connection.execute(insert(operation_table).values(
        operation_id=operation_id, environment_id=internal_request.environment_id,
        project_id=task["project_id"], task_id=task["task_id"], workspace_id=binding.workspace_id,
        action=action, operation_state="pending", expected_environment_revision=expected_revision,
        accepted_environment_revision=accepted_revision, workspace_revision=binding.workspace_revision,
        write_generation=binding.write_generation, binding_json=binding.model_dump(mode="json"),
        binding_digest=workspace_metadata_digest(binding), source_manifest_digest=internal_request.source_manifest_digest,
        data_revision=(spec.data_revision if environment is None else environment["data_revision"]),
        data_generation=(spec.data_generation if environment is None else environment["data_generation"]),
        request_json=stored_request, command_request_digest=context.envelope.request_digest,
        request_digest=operation_digest, command_id=command_id,
        authorization_decision_id=context.authorization.envelope.decision_id,
    ))
    intent = WorkspaceDevelopmentEnvironmentOperationIntent(
        request=internal_request, request_digest=operation_digest,
        accepted_environment_revision=accepted_revision,
    )
    append_event(
        connection, command_id=command_id, project_id=task["project_id"],
        aggregate_kind="workspace_development_environment", aggregate_id=internal_request.environment_id,
        aggregate_version=accepted_revision, event_type=DEVELOPMENT_OPERATION_EVENT,
        schema_version=DEVELOPMENT_OPERATION_SCHEMA,
        event_id=DEVELOPMENT_OPERATION_EVENT_PREFIX + command_id, payload=intent,
    )
    code = "workspace_development_operation_queued" if has_enqueue else "workspace_development_awaiting_runner"
    result = development_command_result(
        context, client_request, "accepted", code, binding.workspace_id,
        internal_request.environment_id, operation_id, operation_digest, accepted_revision,
    )
    save_result(connection, context.envelope, result, status_code=202,
                authorization=context.authorization.envelope)
    return WorkspaceDevelopmentHttpResult(status_code=202, body=result)
