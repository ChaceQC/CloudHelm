"""Bounded immutable channel projections and original approved operation lookup."""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from database.commands import get_by_id
from modules.collaboration.errors import TaskBoundaryError
from modules.delivery.deployment_application import delivery_context
from modules.delivery.deployment_store import read_object
from modules.delivery.deployment_tables import deployment_approvals
from modules.delivery.release_recipe import delivery_digest
from modules.delivery.remote_tables import remote_results
from modules.identity.actors import actor_for_command
from packages.contracts.p1.remote_delivery import RemotePlan, RemoteStepResult


def save_projection(connection, table, credential, key, value, operation=None, step=None):
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    digest = delivery_digest(value)
    connection.execute(insert(table).values(id=key, credential_id=credential["credential_id"], operation_id=operation,
        step_id=step, digest=digest, value_json=value).on_conflict_do_nothing())
    saved = connection.execute(select(table).where(table.c.id == key)).mappings().one()
    if saved["digest"] != digest or saved["credential_id"] != credential["credential_id"]:
        raise TaskBoundaryError("remote_message_identity_conflict")


def approved_operation(uow, credential, operation):
    row = uow.connection.execute(select(deployment_approvals).where(
        deployment_approvals.c.project_id == credential["project_id"],
        deployment_approvals.c.value_json["operation_id"].astext == operation,
    )).mappings().one_or_none()
    if row is None:
        raise TaskBoundaryError("deployment_operation_not_found", status_code=404)
    actor = actor_for_command(uow, row["command_id"])
    context = delivery_context(uow, actor, row["project_id"], "deployment.approve")
    context.envelope = get_by_id(uow.connection, row["command_id"]).envelope
    plan = read_object(uow.connection, row["project_id"], "plan", row["plan_id"])
    binding = plan.value.binding
    if (binding.target_id != credential["target_id"] or binding.installation_id != credential["installation_id"]):
        raise TaskBoundaryError("remote_target_scope_mismatch", status_code=403)
    approval = read_object(uow.connection, row["project_id"], "approval", row["plan_id"]).value
    return context, plan, approval


def package_plan(connection, plan, approval):
    manifest = read_object(connection, plan.value.project_id, "release", plan.value.release_id).value
    return RemotePlan(operation_id=approval.operation_id, plan_digest=plan.digest, plan=plan.value,
        manifest=manifest, approval=approval)


def step_results(connection, operation):
    rows = connection.execute(select(remote_results.c.value_json).where(
        remote_results.c.operation_id == operation).limit(257)).scalars().all()
    if len(rows) > 256:
        raise TaskBoundaryError("remote_result_scope_exceeded")
    latest = {}
    # Unknown observations cannot supersede a known terminal fact, regardless of wall-clock order.
    for value in sorted((RemoteStepResult.model_validate(row) for row in rows), key=delivery_digest):
        previous = latest.get(value.step_id)
        if previous is not None and (
            previous.operation_id != value.operation_id or previous.plan_digest != value.plan_digest
            or previous.input_digest != value.input_digest or previous.grant_id != value.grant_id
            or previous.executor_instance != value.executor_instance or previous.generation != value.generation
        ):
            raise TaskBoundaryError("remote_terminal_fact_conflict")
        if previous is not None and previous.status != "unknown":
            if value.status != "unknown" and previous != value:
                raise TaskBoundaryError("remote_terminal_fact_conflict")
            continue
        if previous is None or value.status != "unknown":
            latest[value.step_id] = value
    return latest
