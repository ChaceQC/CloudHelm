"""Register one immutable Run and enqueue it in the caller-owned transaction."""

from hashlib import sha256
from decimal import Decimal

from dbos import WorkflowSerializationFormat
from sqlalchemy import insert, select, update

from database.readiness import assert_runtime_ready
from database.uow import UnitOfWork
from modules.collaboration.command_support import lock_task_access
from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.facts import read_declaration
from modules.collaboration.guards import require_ordinary_progress
from modules.collaboration.records import contract_digest, read_registered_reference, reference_key
from modules.collaboration.tables import task_inputs, work_items
from modules.identity.actors import actor_for_command
from modules.workflow.tables import workflow_bindings
from modules.workflow.version import APPLICATION_NAME, APPLICATION_VERSION
from packages.contracts.p0.engineering_contracts import EngineeringRef
from packages.contracts.p2.runtime import RuntimeStartRequest
from packages.contracts.p2.workspace_tools import WORKSPACE_TOOL_SCHEMAS
from packages.contracts.p2.workspace_edits import WORKSPACE_EDIT_SCHEMAS
from packages.contracts.p2.workspace_environment import WORKSPACE_ENVIRONMENT_SCHEMAS
from .tables import agent_runs, agent_sessions

WORKFLOW_NAME = "agent_runtime.advance.v1"
MODEL_QUEUE = "models"


def start_run(engine, client, source_command_id, request: RuntimeStartRequest):
    incoming, policy = request.runtime_input, request.policy
    digest = contract_digest(request)
    with UnitOfWork(engine) as uow:
        assert_runtime_ready(uow.connection, role="worker")
        actor = actor_for_command(uow, source_command_id)
        task, authorization = lock_task_access(uow, actor, incoming.task_id, "task.command")
        existing = uow.connection.execute(select(agent_runs).where(
            agent_runs.c.run_id == incoming.run_id)).mappings().one_or_none()
        if existing is not None:
            if existing["request_digest"] != digest or existing["source_command_id"] != source_command_id:
                raise TaskBoundaryError("agent_run_identity_conflict")
            return {"run_id": incoming.run_id, "workflow_id": existing["workflow_id"], "state": existing["state"]}
        require_ordinary_progress(uow.connection, incoming.task_id, expected_version=task["version"],
            expected_control_revision=incoming.expected_task_control_revision,
            expected_input_validity_revision=incoming.expected_input_validity_revision)
        from modules.workspaces.handoff_gates import require_agent_workspace

        require_agent_workspace(uow.connection, incoming.task_id, request.context.work_item_id)
        _check_context(uow, task, authorization, request)
        session = uow.connection.execute(select(agent_sessions).where(
            agent_sessions.c.session_id == incoming.session_id).with_for_update()).mappings().one_or_none()
        if session is None:
            if incoming.expected_session_version != 0:
                raise TaskBoundaryError("agent_session_version_conflict")
            history_key = "sha256:" + sha256(b"[]").hexdigest()
            if incoming.committed_history.digest != history_key:
                raise TaskBoundaryError("initial_agent_history_not_empty")
            uow.connection.execute(insert(agent_sessions).values(session_id=incoming.session_id,
                task_id=incoming.task_id, source_command_id=source_command_id, epoch_id=policy.epoch_id,
                version=0, history_key=history_key, state="idle"))
        elif (session["task_id"] != incoming.task_id or session["version"] != incoming.expected_session_version
                or session["history_key"] != incoming.committed_history.digest):
            raise TaskBoundaryError("agent_session_version_conflict")
        if session is not None:
            previous = uow.connection.scalar(select(agent_runs.c.start_json).where(
                agent_runs.c.session_id == incoming.session_id).order_by(agent_runs.c.created_at.desc()).limit(1))
            if previous is not None:
                old = RuntimeStartRequest.model_validate(previous)
                if (old.policy.epoch_id, old.policy.model_config_id, old.policy.model_config_revision,
                    old.policy.model_name, old.policy.role, old.policy.instruction_revision, old.context.tool_names) != (
                    policy.epoch_id, policy.model_config_id, policy.model_config_revision,
                    policy.model_name, policy.role, policy.instruction_revision, request.context.tool_names):
                    raise TaskBoundaryError("agent_epoch_policy_change_requires_new_session")
        if uow.connection.scalar(select(agent_runs.c.run_id).where(
                agent_runs.c.session_id == incoming.session_id, agent_runs.c.state.in_(("queued", "running")))):
            raise TaskBoundaryError("agent_session_has_active_run")
        workflow_id = _enqueue_run(uow, client, source_command_id, request)
    return {"run_id": incoming.run_id, "workflow_id": workflow_id, "state": "queued"}


def _enqueue_run(uow, client, source_command_id, request):
    incoming = request.runtime_input
    digest = contract_digest(request)
    workflow_id = "agent-" + sha256(incoming.run_id.encode("utf-8")).hexdigest()
    uow.connection.execute(insert(agent_runs).values(run_id=incoming.run_id, session_id=incoming.session_id,
        source_command_id=source_command_id, workflow_id=workflow_id, request_digest=digest,
        start_json=request.model_dump(mode="json"), state="queued"))
    uow.connection.execute(update(agent_sessions).where(
        agent_sessions.c.session_id == incoming.session_id).values(state="queued"))
    uow.connection.execute(insert(workflow_bindings).values(workflow_id=workflow_id,
        command_id=source_command_id, business_kind="agent_run", business_id=incoming.run_id,
        process_type=WORKFLOW_NAME, advance_revision=incoming.expected_session_version,
        workflow_name=WORKFLOW_NAME, queue_name=MODEL_QUEUE, application_name=APPLICATION_NAME,
        application_version=APPLICATION_VERSION, request_digest=digest))
    client.enqueue_in_transaction(uow.connection, {"workflow_name": WORKFLOW_NAME,
        "queue_name": MODEL_QUEUE, "workflow_id": workflow_id, "workflow_id_reuse_policy": "return-existing",
        "app_version": APPLICATION_VERSION, "application_name": APPLICATION_NAME,
        "serialization_type": WorkflowSerializationFormat.PORTABLE}, incoming.run_id)
    return workflow_id


def enqueue_wait_continuation_in_uow(uow, client, wait, result_digest):
    """Enqueue one new Run using committed history, current authorization and the original result."""
    previous = uow.connection.execute(select(agent_runs).where(
        agent_runs.c.run_id == wait["from_run_id"])).mappings().one()
    old = RuntimeStartRequest.model_validate(previous["start_json"])
    actor = actor_for_command(uow, previous["source_command_id"])
    task, authorization = lock_task_access(uow, actor, old.runtime_input.task_id, "task.command")
    require_ordinary_progress(uow.connection, task["task_id"], expected_version=task["version"],
        expected_control_revision=wait["control_revision"],
        expected_input_validity_revision=wait["input_validity_revision"])
    session = uow.connection.execute(select(agent_sessions).where(
        agent_sessions.c.session_id == wait["session_id"]).with_for_update()).mappings().one()
    if session["state"] != "idle" or uow.connection.scalar(select(agent_runs.c.run_id).where(
        agent_runs.c.session_id == session["session_id"], agent_runs.c.state.in_(("queued", "running")))):
        return None
    item = uow.connection.execute(select(work_items).where(
        work_items.c.task_id == task["task_id"],
        work_items.c.work_item_id == old.context.work_item_id)).mappings().one_or_none()
    if item is None or item["state"] not in {"ready", "running", "submitted"}:
        raise TaskBoundaryError("agent_work_item_not_current")
    suffix = sha256(wait["wait_condition_id"].encode("utf-8")).hexdigest()
    run_id = "agent-cont-" + suffix
    history = EngineeringRef(kind="history", object_id=session["session_id"],
        revision=str(session["version"]), digest=session["history_key"], digest_algorithm="sha256")
    context = old.context.model_copy(update={"context_id": "context-" + suffix,
        "context_revision": "1", "run_id": run_id, "starting_history_ref": history,
        "work_item_revision": item["revision"], "permission_revision": authorization.envelope.permission_revision})
    context_ref = EngineeringRef(kind="context", object_id=context.context_id, revision=context.context_revision,
        digest=contract_digest(context), digest_algorithm="sha256")
    deferred = EngineeringRef(kind="deferred_results", object_id=wait["wait_condition_id"], revision="1",
        digest=result_digest, digest_algorithm="sha256")
    incoming = old.runtime_input.model_copy(update={"run_id": run_id,
        "expected_session_version": session["version"], "context_package": context_ref,
        "committed_history": history, "pending_messages": None, "deferred_results": deferred})
    request = RuntimeStartRequest(runtime_input=incoming, context=context, policy=old.policy)
    _check_context(uow, task, authorization, request, allow_deferred=True)
    _enqueue_run(uow, client, previous["source_command_id"], request)
    return run_id


def _check_context(uow, task, authorization, request, *, allow_deferred=False):
    context, incoming = request.context, request.runtime_input
    if (incoming.committed_history.object_id != incoming.session_id
            or incoming.committed_history.revision != str(incoming.expected_session_version)):
        raise TaskBoundaryError("agent_history_boundary_mismatch")
    if incoming.context_package.digest != contract_digest(context):
        raise TaskBoundaryError("context_digest_mismatch")
    declaration = read_declaration(uow.connection, task)
    if (context.requirement_ref != declaration.requirement_ref
            or context.acceptance_assets_ref != declaration.acceptance_assets_ref
            or context.source_ref != declaration.source_ref
            or context.permission_revision != authorization.envelope.permission_revision
            or set(context.tool_names) - ({"task.read", "submit_operation", "query_operation", "await_operation"}
                                         | WORKSPACE_TOOL_SCHEMAS.keys() | WORKSPACE_EDIT_SCHEMAS.keys()
                                         | WORKSPACE_ENVIRONMENT_SCHEMAS.keys())
            or context.budget_currency != declaration.budget.currency
            or context.budget_limit > Decimal(declaration.budget.amount)
            or incoming.pending_messages is not None
            or (incoming.deferred_results is not None and not allow_deferred)):
        raise TaskBoundaryError("agent_context_not_current")
    current_input = uow.connection.scalar(select(task_inputs.c.input_set_key).where(
        task_inputs.c.task_id == task["task_id"],
        task_inputs.c.input_validity_revision == task["input_validity_revision"]))
    if current_input != reference_key(task["project_id"], context.input_set_ref):
        raise TaskBoundaryError("agent_input_not_current")
    item = uow.connection.execute(select(work_items).where(work_items.c.task_id == task["task_id"],
        work_items.c.work_item_id == context.work_item_id)).mappings().one_or_none()
    if item is None or item["revision"] != context.work_item_revision:
        raise TaskBoundaryError("agent_work_item_not_current")
    for ref in (context.input_set_ref, context.requirement_ref, context.acceptance_assets_ref, context.source_ref):
        read_registered_reference(uow.connection, task["project_id"], ref)
    for ref in (*context.contract_refs, *context.decision_refs, *context.unresolved_refs):
        if ref.authority != "source-files":
            read_registered_reference(uow.connection, task["project_id"], ref)
