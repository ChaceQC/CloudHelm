"""Task commands assemble current context and join the existing Run transaction."""

from hashlib import sha256
from uuid import uuid4

from sqlalchemy import select, update

from database.commands import lock_and_get, save_result
from database.readiness import assert_runtime_ready
from database.uow import UnitOfWork
from modules.collaboration.command_support import TaskCommandContext, lock_task_access, update_task
from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.guards import MAX_REVISION, check_ordinary_progress, task_resource
from modules.collaboration.tables import task_wait_conditions, work_items
from modules.collaboration.records import contract_digest
from modules.collaboration.work_item_run import build_work_item_run_spec, read_work_item_run_inputs
from modules.identity.actors import validate_actor
from modules.identity.authorization import authorize_current
from modules.sync.events import append_event
from modules.workspaces.commands import _create
from modules.workspaces.operations import current_engineering_input
from modules.workspaces.queries import workspace_read_spec_in_uow
from modules.workspaces.tables import workspaces
from packages.contracts.p0.core_contracts import RuntimeInput
from packages.contracts.p0.engineering_contracts import EngineeringRef
from packages.contracts.p0.identity_contracts import CommandEnvelope, CommandIntent, request_digest
from packages.contracts.p1.workspace_requests import CreateWorkspaceRequest
from packages.contracts.p2.runtime import ContextPackage, RunPolicy, RuntimeStartRequest
from packages.contracts.p2.task_agent import TaskAgentCommandResult
from packages.contracts.p2.workspace_tools import WORKSPACE_TOOL_SCHEMAS
from packages.contracts.p2.workspace_edits import WORKSPACE_EDIT_SCHEMAS
from packages.contracts.p2.workspace_environment import WORKSPACE_ENVIRONMENT_SCHEMAS
from packages.contracts.p2.workspace_builds import WORKSPACE_BUILD_SCHEMAS
from packages.contracts.p2.workspace_checks import WORKSPACE_CHECK_SCHEMAS
from .admission import check_new_run_budget
from .operation_tables import agent_operation_waits
from .registration import active_work_item_run, enqueue_prepared_run_in_uow, lock_run_work_item, read_agent_workspace
from .tables import agent_runs, agent_sessions
from .task_queries import query_agent_in_uow
from .work_item_capabilities import project_work_item_capabilities_in_uow, require_formal_preview_in_uow


class TaskAgentApplication:
    def __init__(self, engine, control_engine, client, *, diff_reader=None,
                 engineering_registration=None, preview_installation=None):
        self.engine, self.control_engine, self.client = engine, control_engine, client
        self.diff_reader = diff_reader
        self.engineering_registration, self.preview_installation = engineering_registration, preview_installation

    def start(self, actor, task_id, request, *, idempotency_key):
        validate_actor(actor)
        with UnitOfWork(self.engine) as uow:
            assert_runtime_ready(uow.connection, role="api")
            task, authorization = lock_task_access(uow, actor, task_id, "task.command")
            resource = task_resource(task)
            intent = CommandIntent(request_schema_revision="p2-task-agent-start-r1", caller=actor.principal,
                scope=resource.scope, target=resource.target_scope, action="task.command",
                expected_resource_revision=request.expected_version)
            envelope = CommandEnvelope(**intent.model_dump(), command_id=uuid4().hex,
                idempotency_key=idempotency_key, request_digest=request_digest(intent, request))
            previous = lock_and_get(uow.connection, envelope)
            if previous is not None:
                return previous.status_code, TaskAgentCommandResult.model_validate(previous.result)
            context = TaskCommandContext(uow, actor, task, authorization, envelope)
            try:
                with uow.connection.begin_nested():
                    runtime_request = _prepare_runtime(context, request,
                        engineering_registration=self.engineering_registration,
                        preview_installation=self.preview_installation)
                    incoming = runtime_request.runtime_input
                    result = TaskAgentCommandResult(command_id=envelope.command_id, task_id=task_id,
                        code="agent_run_queued", state="queued", session_id=incoming.session_id,
                        run_id=incoming.run_id, workflow_id="agent-" + sha256(incoming.run_id.encode("utf-8")).hexdigest())
                    save_result(uow.connection, envelope, result, status_code=202, authorization=authorization.envelope)
                    enqueue_prepared_run_in_uow(uow, self.client, envelope.command_id, runtime_request,
                                                 new_session=request.session_id is None)
                    append_event(uow.connection, command_id=envelope.command_id, project_id=task["project_id"],
                        aggregate_kind="task", aggregate_id=task_id, aggregate_version=context.task["version"],
                        event_type="task.agent_run_queued", schema_version="p2-task-agent-event-r1", payload=result)
                    return 202, result
            except TaskBoundaryError as error:
                result = TaskAgentCommandResult(command_id=envelope.command_id, task_id=task_id,
                    code=error.code, state="rejected")
                save_result(uow.connection, envelope, result, status_code=error.status_code,
                            authorization=authorization.envelope)
                return error.status_code, result

    def query(self, actor, task_id):
        validate_actor(actor)
        with UnitOfWork(self.control_engine) as uow:
            task, _ = lock_task_access(uow, actor, task_id, "resource.read")
            authorize_current(uow, actor, task_resource(task), "operation.query")
            return query_agent_in_uow(uow, task)

    def capabilities(self, actor, task_id, work_item_id):
        validate_actor(actor)
        with UnitOfWork(self.control_engine) as uow:
            task, authorization = lock_task_access(uow, actor, task_id, "resource.read")
            item = uow.connection.execute(select(work_items).where(
                work_items.c.task_id == task_id, work_items.c.work_item_id == work_item_id,
            )).mappings().one_or_none()
            if item is None:
                raise TaskBoundaryError("agent_work_item_not_found", status_code=404)
            return project_work_item_capabilities_in_uow(uow, actor, task, item,
                authorization_revision=authorization.envelope.permission_revision,
                engineering_registration=self.engineering_registration, preview_installation=self.preview_installation)

    def diff(self, actor, task_id, work_item_id):
        validate_actor(actor)
        with UnitOfWork(self.control_engine) as uow:
            task, _ = lock_task_access(uow, actor, task_id, "resource.read")
            authorize_current(uow, actor, task_resource(task), "operation.query")
            if uow.connection.scalar(select(work_items.c.work_item_id).where(
                work_items.c.task_id == task_id, work_items.c.work_item_id == work_item_id)) is None:
                raise TaskBoundaryError("agent_work_item_not_found", status_code=404)
            workspace_id = uow.connection.scalar(select(workspaces.c.workspace_id).where(
                workspaces.c.task_id == task_id, workspaces.c.work_item_id == work_item_id))
            if workspace_id is None:
                return {"workspace_id": None, "work_item_id": work_item_id, "files": [], "truncated": False}
            spec = workspace_read_spec_in_uow(uow, actor, workspace_id)
        if self.diff_reader is None:
            raise TaskBoundaryError("agent_workspace_reader_unavailable")
        result = self.diff_reader(spec)
        with UnitOfWork(self.control_engine) as uow:
            task, _ = lock_task_access(uow, actor, task_id, "resource.read")
            authorize_current(uow, actor, task_resource(task), "operation.query")
            if workspace_read_spec_in_uow(uow, actor, workspace_id) != spec:
                raise TaskBoundaryError("workspace_revision_conflict")
        return result


def _prepare_runtime(context, request, *, engineering_registration, preview_installation):
    uow, task = context.uow, context.task
    check_ordinary_progress(task, expected_version=request.expected_version,
        expected_control_revision=request.expected_control_revision,
        expected_input_validity_revision=request.expected_input_validity_revision)
    item = lock_run_work_item(uow.connection, task["task_id"], request.work_item_id, starting=True)
    if active_work_item_run(uow.connection, task["task_id"], request.work_item_id, request.session_id) is not None:
        raise TaskBoundaryError("agent_work_item_has_active_run")
    waiting = select(agent_operation_waits.c.wait_condition_id).join(agent_runs,
        agent_runs.c.run_id == agent_operation_waits.c.from_run_id).join(task_wait_conditions).where(
        task_wait_conditions.c.task_id == task["task_id"], task_wait_conditions.c.state != "closed",
        agent_runs.c.start_json["context"]["work_item_id"].astext == request.work_item_id,
        agent_operation_waits.c.continuation_run_id.is_(None))
    if uow.connection.scalar(waiting.limit(1)):
        raise TaskBoundaryError("agent_operation_waiting")
    if item["revision"] == MAX_REVISION:
        raise TaskBoundaryError("revision_exhausted")
    write_access = authorize_current(uow, context.actor, task_resource(task), "workspace.write")
    session_id, version, history_key, policy, tools = _session_for_run(context, request, item)
    inputs = read_work_item_run_inputs(uow.connection, task, item)
    input_ref, declaration = inputs.input_set_ref, inputs.declaration
    check_new_run_budget(uow.connection, task, declaration.budget, policy)
    require_formal_preview_in_uow(uow, inputs.requirements, engineering_registration=engineering_registration,
                                  preview_installation=preview_installation)
    workspace = read_agent_workspace(uow.connection, task["task_id"], item["work_item_id"])
    if workspace is None:
        workspace_context = TaskCommandContext(uow, context.actor, task, write_access, context.envelope)
        workspace_request = CreateWorkspaceRequest(expected_version=task["version"],
            expected_control_revision=task["control_revision"], expected_input_validity_revision=task["input_validity_revision"],
            input_set_ref=input_ref, goal=item["goal"])
        registration = current_engineering_input(uow.connection, task, input_ref)
        result, _ = _create(workspace_context, workspace_request, registration, work_item=item)
        workspace = result.binding
        context.task = workspace_context.task
    else:
        update_task(context)
    work_item_revision = item["revision"] + 1
    uow.connection.execute(update(work_items).where(work_items.c.work_item_id == item["work_item_id"]).values(
        revision=work_item_revision, state="running", blocked_reason=None, owner_session_id=session_id))
    history = EngineeringRef(kind="history", object_id=session_id, revision=str(version), digest=history_key,
                             digest_algorithm="sha256")
    run_id = "agent-run-" + context.envelope.command_id
    package = ContextPackage(context_id="context-" + context.envelope.command_id, context_revision="1", run_id=run_id,
        input_set_ref=input_ref, work_item_id=item["work_item_id"], work_item_revision=work_item_revision,
        requirement_ref=declaration.requirement_ref, acceptance_assets_ref=declaration.acceptance_assets_ref,
        source_ref=declaration.source_ref, baseline_commit=declaration.source_ref.revision,
        starting_history_ref=history, tool_names=tools, permission_revision=context.authorization.envelope.permission_revision,
        permission_scopes=("task.command", "workspace.write"), budget_limit=declaration.budget.amount,
        budget_currency=declaration.budget.currency,
        work_item_spec=build_work_item_run_spec(uow.connection, item, inputs, workspace))
    incoming = RuntimeInput(task_id=task["task_id"], session_id=session_id, run_id=run_id, expected_session_version=version,
        expected_task_control_revision=task["control_revision"], expected_input_validity_revision=task["input_validity_revision"],
        context_package=EngineeringRef(kind="context", object_id=package.context_id, revision="1",
            digest=contract_digest(package), digest_algorithm="sha256"), input_set=input_ref, committed_history=history)
    return RuntimeStartRequest(runtime_input=incoming, context=package, policy=policy)


def _session_for_run(context, request, item):
    uow, task = context.uow, context.task
    if request.session_id is not None:
        session = uow.connection.execute(select(agent_sessions).where(
            agent_sessions.c.session_id == request.session_id,
            agent_sessions.c.task_id == task["task_id"]).with_for_update()).mappings().one_or_none()
        if (session is None or session["version"] != request.expected_session_version
                or item["owner_session_id"] not in {None, session["session_id"]}):
            raise TaskBoundaryError("agent_session_version_conflict")
        previous = uow.connection.scalar(select(agent_runs.c.start_json).where(
            agent_runs.c.session_id == session["session_id"]).order_by(
                agent_runs.c.created_at.desc(), agent_runs.c.run_id.desc()).limit(1))
        old = RuntimeStartRequest.model_validate(previous)
        if old.context.work_item_id != request.work_item_id or old.policy.role != "developer":
            raise TaskBoundaryError("agent_session_work_item_mismatch")
        if {"max_requests", "max_duration_seconds", "max_output_tokens", "per_request_cost_upper_bound"} & request.model_fields_set:
            raise TaskBoundaryError("agent_session_policy_change_requires_new_session")
        return session["session_id"], session["version"], session["history_key"], old.policy, old.context.tool_names
    if request.expected_session_version != 0 or request.per_request_cost_upper_bound is None:
        raise TaskBoundaryError("agent_initial_policy_required", status_code=422)
    policy = RunPolicy(model_config_id="default-responses", model_config_revision="1", model_name="gpt-6-luna",
        epoch_id="agent-development-r2", max_requests=request.max_requests,
        max_duration_seconds=request.max_duration_seconds, max_output_tokens=request.max_output_tokens,
        per_request_cost_upper_bound=request.per_request_cost_upper_bound)
    tools = (
        "task.read", "submit_operation", "query_operation", "await_operation", *WORKSPACE_TOOL_SCHEMAS,
        *WORKSPACE_EDIT_SCHEMAS, *WORKSPACE_ENVIRONMENT_SCHEMAS, *WORKSPACE_BUILD_SCHEMAS, *WORKSPACE_CHECK_SCHEMAS)
    return "agent-session-" + context.envelope.command_id, 0, "sha256:" + sha256(b"[]").hexdigest(), policy, tools
