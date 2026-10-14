"""Task creation/start and their real, bounded initial work inside a shared UoW."""

from uuid import uuid4

from sqlalchemy import insert, select, update

from database.commands import lock_and_get, save_result
from database.readiness import assert_schema_ready
from modules.collaboration.command_support import command_result, record_event, update_task
from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.facts import read_declaration
from modules.collaboration.guards import require_ordinary_progress
from modules.collaboration.records import contract_digest, validate_declaration_references
from modules.collaboration.tables import task_declarations, tasks, work_items
from modules.identity.actors import AuthoritativeResource
from modules.identity.authorization import authorize_current
from modules.identity.locking import lock_current_subject, lock_project_policy
from modules.projects.tables import projects
from modules.sync.events import append_event
from modules.workflow.dispatch import bind_and_enqueue
from modules.workflow.version import INITIAL_WORKFLOW
from packages.contracts.p0.identity_contracts import CommandEnvelope, CommandIntent, request_digest
from packages.contracts.p1.commands import WorkflowDispatch
from packages.contracts.p1.task_internal import TaskChangedEvent
from packages.contracts.p1.task_results import TaskBlocker, TaskCommandResult, TaskCreateRejection, TaskHttpResult


def _create_context(uow, actor, project_id, request, key):
    lock_current_subject(uow, actor)
    lock_project_policy(uow, project_id)
    project = uow.connection.execute(select(projects).where(
        projects.c.project_id == project_id,
    ).with_for_update()).mappings().one_or_none()
    if project is None:
        raise TaskBoundaryError("project_not_found", status_code=404)
    resource = AuthoritativeResource(project_id, "project", project_id, revision=project["revision"])
    authorization = authorize_current(uow, actor, resource, "task.command")
    authorize_current(uow, actor, resource, "resource.read")
    intent = CommandIntent(
        request_schema_revision="p1-task-create-r1", caller=actor.principal,
        scope=resource.scope, target=resource.target_scope, action="task.command",
        expected_resource_revision=request.expected_project_revision,
    )
    envelope = CommandEnvelope(**intent.model_dump(), command_id=uuid4().hex,
                               idempotency_key=key, request_digest=request_digest(intent, request))
    return project, authorization, envelope


def _insert_task(uow, envelope, project, request):
    if project["revision"] != request.expected_project_revision:
        raise TaskBoundaryError("resource_revision_conflict")
    validate_declaration_references(uow.connection, project["project_id"], request.declaration)
    assert_schema_ready(uow.connection)
    # Target remains the fixed Project until dedupe is known to be new. These IDs
    # are allocated only now, so retries never hash a fresh random Task target.
    task_id, declaration_id = uuid4().hex, uuid4().hex
    uow.connection.execute(insert(task_declarations).values(
        declaration_id=declaration_id, project_id=project["project_id"],
        declaration_json=request.declaration.model_dump(mode="json"),
        declaration_digest=contract_digest(request.declaration), created_by_command_id=envelope.command_id,
    ))
    uow.connection.execute(insert(tasks).values(
        task_id=task_id, project_id=project["project_id"], declaration_id=declaration_id,
        state="draft", version=1, control_revision=0, input_validity_revision=0,
        input_status="valid", operation_set_revision=0, ordinary_progress_closed=False,
    ))
    result = TaskCommandResult(command_id=envelope.command_id, task_id=task_id, outcome="created",
                               code="task_created", state="draft", version=1, control_revision=0,
                               input_validity_revision=0)
    append_event(uow.connection, command_id=envelope.command_id, project_id=project["project_id"],
                 aggregate_kind="task", aggregate_id=task_id, aggregate_version=1,
                 event_type="task.created", schema_version="p1-task-event-r1",
                 payload=TaskChangedEvent(result=result))
    return result


def create_task(uow, actor, project_id, request, key) -> TaskHttpResult:
    project, authorization, envelope = _create_context(uow, actor, project_id, request, key)
    existing = lock_and_get(uow.connection, envelope)
    if existing is not None:
        return TaskHttpResult(status_code=existing.status_code, body=existing.result)
    status = 201
    try:
        with uow.connection.begin_nested():
            result = _insert_task(uow, envelope, project, request)
    except TaskBoundaryError as error:
        status = error.status_code
        result = TaskCreateRejection(command_id=envelope.command_id, project_id=project_id,
                                     code=error.code, blockers=(TaskBlocker(
                                         code=error.code, object_kind="project", object_id=project_id,
                                     ),))
    save_result(uow.connection, envelope, result, status_code=status, authorization=authorization.envelope)
    return TaskHttpResult(status_code=status, body=result)


def start_task(context, request, client):
    context.task = require_ordinary_progress(
        context.uow.connection, context.task["task_id"], expected_version=request.expected_version,
        expected_control_revision=request.expected_control_revision,
        expected_input_validity_revision=request.expected_input_validity_revision, allowed_states=("draft",),
    )
    declaration = read_declaration(context.uow.connection, context.task)
    validate_declaration_references(context.uow.connection, context.task["project_id"], declaration)
    update_task(context, state="active")
    context.uow.connection.execute(insert(work_items).values(
        work_item_id=uuid4().hex, task_id=context.task["task_id"], declaration_id=context.task["declaration_id"],
        revision=1, state="pending", required=True, goal=declaration.goal,
    ))
    workflow_id = "task-initial-" + context.envelope.command_id
    bind_and_enqueue(context.uow.connection, client, WorkflowDispatch(
        command_id=context.envelope.command_id, workflow_id=workflow_id, task_id=context.task["task_id"],
        advance_revision=context.task["version"], workflow_name=INITIAL_WORKFLOW,
        request_digest=context.envelope.request_digest,
    ))
    result = command_result(context, "started", "task_started", workflow_id=workflow_id)
    record_event(context, result, "task.started")
    return result, 202


def advance_initial(context, request):
    context.task = require_ordinary_progress(
        context.uow.connection, context.task["task_id"], expected_version=request.expected_version,
        expected_control_revision=request.expected_control_revision,
        expected_input_validity_revision=request.expected_input_validity_revision,
    )
    declaration = read_declaration(context.uow.connection, context.task)
    validate_declaration_references(context.uow.connection, context.task["project_id"], declaration)
    count = context.uow.connection.scalar(select(work_items.c.work_item_id).where(
        work_items.c.task_id == context.task["task_id"], work_items.c.state.in_(("pending", "ready")),
    ).limit(1))
    if count is None:
        raise TaskBoundaryError("initial_work_item_missing")
    update_task(context)
    context.uow.connection.execute(update(work_items).where(
        work_items.c.task_id == context.task["task_id"], work_items.c.state.in_(("pending", "ready")),
    ).values(state="blocked", blocked_reason="capability_not_enabled"))
    result = command_result(context, "blocked", "capability_not_enabled", blockers=(
        TaskBlocker(code="capability_not_enabled", object_id=context.task["task_id"]),
    ))
    record_event(context, result, "task.initial_progress_blocked", source_command_id=request.source_command_id)
    return result, 200
