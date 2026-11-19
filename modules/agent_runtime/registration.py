"""Register one immutable Run and enqueue it in the caller-owned transaction."""

from hashlib import sha256
from decimal import Decimal

import rfc8785
from dbos import WorkflowSerializationFormat
from sqlalchemy import insert, or_, select, update

from database.readiness import assert_runtime_ready
from database.uow import UnitOfWork
from modules.collaboration.command_support import lock_task_access
from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.guards import check_ordinary_progress, task_resource
from modules.collaboration.records import contract_digest, read_registered_reference
from modules.collaboration.tables import work_items
from modules.collaboration.work_item_run import build_work_item_run_spec, read_work_item_run_inputs
from modules.identity.actors import actor_for_command
from modules.identity.authorization import authorize_current
from modules.workflow.tables import workflow_bindings
from modules.workflow.version import APPLICATION_NAME, APPLICATION_VERSION
from modules.workspaces.handoff_gates import active_handoff
from modules.workspaces.tables import workspaces
from packages.contracts.p0.engineering_contracts import EngineeringRef
from packages.contracts.p1.workspace_git import WorkspaceBinding
from packages.contracts.p2.runtime import RuntimeStartRequest
from packages.contracts.p2.workspace_tools import WORKSPACE_TOOL_SCHEMAS
from packages.contracts.p2.workspace_edits import WORKSPACE_EDIT_SCHEMAS
from packages.contracts.p2.workspace_environment import WORKSPACE_ENVIRONMENT_SCHEMAS
from packages.contracts.p2.workspace_builds import WORKSPACE_BUILD_SCHEMAS
from packages.contracts.p2.workspace_checks import WORKSPACE_CHECK_SCHEMAS
from packages.contracts.p2.verification_agent import VERIFICATION_TOOL_SCHEMAS
from packages.contracts.p2.review_agent import REVIEW_TOOL_SCHEMAS
from .admission import check_new_run_budget
from .operation_tables import agent_operation_waits
from .tables import agent_runs, agent_sessions
from .work_item_capabilities import require_formal_preview_in_uow

WORKFLOW_NAME = "agent_runtime.advance.v1"
MODEL_QUEUE = "models"


def lock_run_work_item(connection, task_id, work_item_id, *, starting=False):
    item = connection.execute(select(work_items).where(
        work_items.c.task_id == task_id, work_items.c.work_item_id == work_item_id,
    ).with_for_update()).mappings().one_or_none()
    if item is None:
        raise TaskBoundaryError("agent_work_item_not_found", status_code=404)
    if item["state"] not in {"ready", "running", "submitted"} and not (starting and (
            item["state"] == "pending" or
            (item["state"] == "blocked" and item["blocked_reason"] == "capability_not_enabled"))):
        raise TaskBoundaryError("agent_work_item_not_current")
    return item


def active_work_item_run(connection, task_id, work_item_id, session_id=None):
    same_item = agent_runs.c.start_json["context"]["work_item_id"].astext == work_item_id
    scope = same_item if session_id is None else or_(same_item, agent_runs.c.session_id == session_id)
    return connection.scalar(select(agent_runs.c.session_id).join(agent_sessions).where(
        agent_sessions.c.task_id == task_id, scope,
        agent_runs.c.state.in_(("queued", "running")),
    ).limit(1))


def read_agent_workspace(connection, task_id, work_item_id):
    raw = connection.scalar(select(workspaces.c.binding_json).where(
        workspaces.c.task_id == task_id, workspaces.c.work_item_id == work_item_id))
    if raw is None:
        return None
    binding = WorkspaceBinding.model_validate(raw)
    if active_handoff(connection, binding.workspace_id) is not None:
        raise TaskBoundaryError("workspace_write_ownership_conflict")
    return binding


def start_run(engine, client, source_command_id, request: RuntimeStartRequest, *,
              engineering_registration=None, preview_installation=None):
    with UnitOfWork(engine) as uow:
        assert_runtime_ready(uow.connection, role="worker")
        return start_run_in_uow(uow, client, source_command_id, request,
                                engineering_registration=engineering_registration,
                                preview_installation=preview_installation)


def start_run_in_uow(uow, client, source_command_id, request: RuntimeStartRequest, *,
                     engineering_registration=None, preview_installation=None):
    """Join an authorized API/worker transaction; never acquire another connection."""
    incoming, policy = request.runtime_input, request.policy
    actor = actor_for_command(uow, source_command_id)
    task, authorization = lock_task_access(uow, actor, incoming.task_id, "task.command")
    existing = uow.connection.execute(select(agent_runs).where(
        agent_runs.c.run_id == incoming.run_id)).mappings().one_or_none()
    if existing is not None:
        original = request.model_dump(mode="json")
        if ("max_no_progress_calls" not in existing["start_json"]["policy"]
                and "max_no_progress_calls" not in policy.model_fields_set):
            del original["policy"]["max_no_progress_calls"]
        for field in ("verification", "review"):
            if field not in existing["start_json"]["context"] and field not in request.context.model_fields_set:
                del original["context"][field]
        digest = "sha256:" + sha256(rfc8785.dumps(original)).hexdigest()
        if existing["request_digest"] != digest or existing["source_command_id"] != source_command_id:
            raise TaskBoundaryError("agent_run_identity_conflict")
        return {"run_id": incoming.run_id, "workflow_id": existing["workflow_id"], "state": existing["state"]}
    check_ordinary_progress(task, expected_version=task["version"],
        expected_control_revision=incoming.expected_task_control_revision,
        expected_input_validity_revision=incoming.expected_input_validity_revision)
    item = lock_run_work_item(uow.connection, incoming.task_id, request.context.work_item_id, starting=True)
    inputs = read_work_item_run_inputs(uow.connection, task, item)
    _check_context(uow, task, authorization, request, item, inputs, actor=actor)
    if policy.role == "developer":
        authorize_current(uow, actor, task_resource(task), "workspace.write")
        workspace = read_agent_workspace(uow.connection, incoming.task_id, item["work_item_id"])
    else:
        workspace = None
    if (request.context.work_item_spec is not None
            and request.context.work_item_spec != build_work_item_run_spec(uow.connection, item, inputs, workspace)):
        raise TaskBoundaryError("agent_work_item_spec_not_current")
    require_formal_preview_in_uow(uow, inputs.requirements, engineering_registration=engineering_registration,
                                  preview_installation=preview_installation)
    check_new_run_budget(uow.connection, task, inputs.declaration.budget, policy,
                         context_limit=request.context.budget_limit)
    session = uow.connection.execute(select(agent_sessions).where(
        agent_sessions.c.session_id == incoming.session_id).with_for_update()).mappings().one_or_none()
    if session is None:
        if incoming.expected_session_version != 0:
            raise TaskBoundaryError("agent_session_version_conflict")
        history_key = "sha256:" + sha256(b"[]").hexdigest()
        if incoming.committed_history.digest != history_key:
            raise TaskBoundaryError("initial_agent_history_not_empty")
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
            old_verification, new_verification = old.context.verification, request.context.verification
            if ((old_verification.candidate_id, old_verification.round_id) if old_verification else None) != (
                    (new_verification.candidate_id, new_verification.round_id) if new_verification else None):
                raise TaskBoundaryError("agent_epoch_policy_change_requires_new_session")
            if old.context.review != request.context.review:
                raise TaskBoundaryError("agent_epoch_policy_change_requires_new_session")
    active = active_work_item_run(uow.connection, incoming.task_id, item["work_item_id"], incoming.session_id)
    if active is not None:
        raise TaskBoundaryError("agent_session_has_active_run" if active == incoming.session_id
                                else "agent_work_item_has_active_run")
    workflow_id = enqueue_prepared_run_in_uow(uow, client, source_command_id, request, new_session=session is None)
    return {"run_id": incoming.run_id, "workflow_id": workflow_id, "state": "queued"}


def enqueue_prepared_run_in_uow(uow, client, source_command_id, request, *, new_session=False):
    """Persist a Run after admission under the caller's Task lock."""
    incoming = request.runtime_input
    if new_session:
        uow.connection.execute(insert(agent_sessions).values(session_id=incoming.session_id,
            task_id=incoming.task_id, source_command_id=source_command_id, epoch_id=request.policy.epoch_id,
            version=0, history_key=incoming.committed_history.digest, state="idle"))
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


def enqueue_wait_continuation_in_uow(uow, client, wait, result_digest, *,
                                    engineering_registration=None, preview_installation=None):
    """Enqueue one new Run using committed history, current authorization and the original result."""
    previous = uow.connection.execute(select(agent_runs).where(
        agent_runs.c.run_id == wait["from_run_id"])).mappings().one()
    old = RuntimeStartRequest.model_validate(previous["start_json"])
    actor = actor_for_command(uow, previous["source_command_id"])
    task, authorization = lock_task_access(uow, actor, old.runtime_input.task_id, "task.command")
    check_ordinary_progress(task, expected_version=task["version"],
        expected_control_revision=wait["control_revision"],
        expected_input_validity_revision=wait["input_validity_revision"])
    work_item_id = old.context.work_item_id
    item = lock_run_work_item(uow.connection, task["task_id"], work_item_id)
    session = uow.connection.execute(select(agent_sessions).where(
        agent_sessions.c.session_id == wait["session_id"]).with_for_update()).mappings().one()
    if session["state"] != "idle" or active_work_item_run(
        uow.connection, task["task_id"], work_item_id, session["session_id"]
    ) is not None:
        return None
    if (previous["session_id"] != session["session_id"] or session["task_id"] != task["task_id"]
            or old.policy.role == "developer" and item["owner_session_id"] != session["session_id"]):
        raise TaskBoundaryError("agent_session_work_item_mismatch")
    if uow.connection.scalar(select(agent_operation_waits.c.continuation_run_id).where(
            agent_operation_waits.c.wait_condition_id == wait["wait_condition_id"])) is not None:
        return None
    inputs = read_work_item_run_inputs(uow.connection, task, item)
    declaration = inputs.declaration
    if (old.context.input_set_ref != inputs.input_set_ref
            or old.context.requirement_ref != declaration.requirement_ref
            or old.context.acceptance_assets_ref != declaration.acceptance_assets_ref
            or old.context.source_ref != declaration.source_ref):
        raise TaskBoundaryError("agent_input_not_current")
    require_formal_preview_in_uow(uow, inputs.requirements, engineering_registration=engineering_registration,
                                  preview_installation=preview_installation)
    check_new_run_budget(uow.connection, task, declaration.budget, old.policy,
                         context_limit=old.context.budget_limit)
    workspace = None
    if old.policy.role == "developer":
        authorize_current(uow, actor, task_resource(task), "workspace.write")
        workspace = read_agent_workspace(uow.connection, task["task_id"], work_item_id)
    suffix = sha256(wait["wait_condition_id"].encode("utf-8")).hexdigest()
    run_id = "agent-cont-" + suffix
    history = EngineeringRef(kind="history", object_id=session["session_id"],
        revision=str(session["version"]), digest=session["history_key"], digest_algorithm="sha256")
    context = old.context.model_copy(update={"context_id": "context-" + suffix,
        "context_revision": "1", "run_id": run_id, "starting_history_ref": history,
        "work_item_revision": item["revision"], "permission_revision": authorization.envelope.permission_revision,
        "work_item_spec": build_work_item_run_spec(uow.connection, item, inputs, workspace)})
    context_ref = EngineeringRef(kind="context", object_id=context.context_id, revision=context.context_revision,
        digest=contract_digest(context), digest_algorithm="sha256")
    deferred = EngineeringRef(kind="deferred_results", object_id=wait["wait_condition_id"], revision="1",
        digest=result_digest, digest_algorithm="sha256")
    incoming = old.runtime_input.model_copy(update={"run_id": run_id,
        "expected_session_version": session["version"], "context_package": context_ref,
        "committed_history": history, "pending_messages": None, "deferred_results": deferred})
    request = RuntimeStartRequest(runtime_input=incoming, context=context, policy=old.policy)
    enqueue_prepared_run_in_uow(uow, client, previous["source_command_id"], request)
    return run_id


def _check_context(uow, task, authorization, request, item, inputs, *, actor):
    context, incoming = request.context, request.runtime_input
    if (incoming.committed_history.object_id != incoming.session_id
            or incoming.committed_history.revision != str(incoming.expected_session_version)):
        raise TaskBoundaryError("agent_history_boundary_mismatch")
    context_digest = contract_digest(context)
    legacy = context.model_dump(mode="json")
    for field in ("verification", "review"):
        if field not in context.model_fields_set:
            del legacy[field]
    legacy_digest = "sha256:" + sha256(rfc8785.dumps(legacy)).hexdigest()
    if incoming.context_package.digest not in {context_digest, legacy_digest}:
        raise TaskBoundaryError("context_digest_mismatch")
    declaration = inputs.declaration
    if (context.requirement_ref != declaration.requirement_ref
            or context.acceptance_assets_ref != declaration.acceptance_assets_ref
            or context.source_ref != declaration.source_ref
            or context.permission_revision != authorization.envelope.permission_revision
            or set(context.tool_names) - ({"task.read", "submit_operation", "query_operation", "await_operation"}
                                         | WORKSPACE_TOOL_SCHEMAS.keys() | WORKSPACE_EDIT_SCHEMAS.keys()
                                         | WORKSPACE_ENVIRONMENT_SCHEMAS.keys() | WORKSPACE_BUILD_SCHEMAS.keys()
                                         | WORKSPACE_CHECK_SCHEMAS.keys() | VERIFICATION_TOOL_SCHEMAS.keys()
                                         | REVIEW_TOOL_SCHEMAS.keys())
            or context.budget_currency != declaration.budget.currency
            or context.budget_limit > Decimal(declaration.budget.amount)
            or incoming.pending_messages is not None
            or incoming.deferred_results is not None):
        raise TaskBoundaryError("agent_context_not_current")
    if inputs.input_set_ref != context.input_set_ref:
        raise TaskBoundaryError("agent_input_not_current")
    if item["revision"] != context.work_item_revision:
        raise TaskBoundaryError("agent_work_item_not_current")
    for ref in (*context.contract_refs, *context.decision_refs, *context.unresolved_refs):
        if ref.authority != "source-files":
            read_registered_reference(uow.connection, task["project_id"], ref)
    if context.verification is not None:
        from .verification import read_verification_candidate_in_uow

        read_verification_candidate_in_uow(uow, actor, task, request)
    if context.review is not None:
        from .review import read_review_evidence_in_uow

        read_review_evidence_in_uow(uow, actor, task, request)
