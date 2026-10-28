"""Original-operation receipts and human closeout for the pre-runtime scope."""

from sqlalchemy import func, select, update

from modules.collaboration.errors import TaskBoundaryError
from modules.delivery.deployment_store import lock_binding, read_object, write_object
from modules.delivery.deployment_tables import (
    deployment_approvals, deployment_closeouts, environment_bindings, environment_revisions,
)
from modules.delivery.release_recipe import delivery_digest
from modules.delivery.remote_tables import remote_closeouts, remote_grants, remote_results
from modules.identity.actors import AuthenticatedActor
from packages.contracts.p1.closeout_contracts import DeploymentCloseout, RemoteCloseoutReceipt


def original_remote_operation(connection, credential, operation_id):
    """Resolve the immutable original inputs without reviving the old approver."""
    row = connection.execute(select(deployment_approvals).where(
        deployment_approvals.c.project_id == credential["project_id"],
        deployment_approvals.c.value_json["operation_id"].astext == operation_id,
    )).mappings().one_or_none()
    if row is None:
        raise TaskBoundaryError("deployment_operation_not_found", status_code=404)
    plan = read_object(connection, credential["project_id"], "plan", row["plan_id"])
    approval = read_object(connection, credential["project_id"], "approval", row["plan_id"]).value
    binding = plan.value.binding
    if binding.target_id != credential["target_id"] or binding.installation_id != credential["installation_id"]:
        raise TaskBoundaryError("remote_target_scope_mismatch", status_code=403)
    if (approval.operation_id != operation_id or approval.plan_id != plan.object_id
            or approval.plan_digest != plan.digest or approval.binding_id != binding.binding_id
            or approval.config_revision_id != plan.value.configuration.configuration.config_revision_id):
        raise TaskBoundaryError("deployment_approval_digest_mismatch")
    return row, plan, approval


def operation_closed(connection, operation_id):
    return (connection.scalar(select(remote_closeouts.c.id).where(remote_closeouts.c.id == operation_id)) is not None
        or connection.scalar(select(deployment_closeouts.c.operation_id).where(
            deployment_closeouts.c.operation_id == operation_id)) is not None)


def require_open_operation(connection, operation_id):
    if operation_closed(connection, operation_id):
        raise TaskBoundaryError("deployment_operation_closed")


def accept_remote_closeout(uow, credential, receipt):
    # The HTTP contract validates the receipt once before entering this application method.
    connection = uow.connection
    _, plan, approval = original_remote_operation(connection, credential, receipt.operation_id)
    row, binding = lock_binding(connection, credential["project_id"], plan.value.binding.binding_id)
    fence = {"operation_id": approval.operation_id, "plan_digest": plan.digest,
        "binding_id": binding.binding_id, "target_id": binding.target_id,
        "installation_id": binding.installation_id, "executor_instance": plan.value.executor_instance,
        "generation": plan.value.generation}
    if (any(getattr(receipt, key) != value for key, value in fence.items())
            or receipt.fence_digest != delivery_digest(fence)):
        raise TaskBoundaryError("remote_closeout_binding_invalid")
    digest = delivery_digest(receipt)
    previous = connection.execute(select(remote_closeouts).where(
        remote_closeouts.c.id == receipt.operation_id)).mappings().one_or_none()
    if previous is not None:
        if (previous["operation_id"] != receipt.operation_id or previous["digest"] != digest
                or previous["value_json"] != receipt.model_dump(mode="json")):
            raise TaskBoundaryError("remote_message_identity_conflict")
        return {"digest": digest, "status": "received"}
    state = plan.value.expected_state
    if (state.environment_revision != 0 or state.release_id is not None or state.config_revision_id is not None
            or state.services or state.database_revision is not None or state.unregistered_resources
            or plan.value.expected_state_digest != delivery_digest(state)
            or not any(step.step_id == "artifact_prepare" and step.kind == "artifact_prepare" for step in plan.value.steps)
            or plan.value.step_inputs["artifact_prepare"].get("delivery_mode") != "archive"
            or plan.value.step_inputs["artifact_prepare"].get("total_writable_disk_limit_bytes")
                != plan.value.configuration.resources.disk_bytes
            or receipt.environment_revision != state.environment_revision + 1
            or receipt.retained_resources.disk_bytes != plan.value.configuration.resources.disk_bytes):
        raise TaskBoundaryError("remote_closeout_scope_invalid")
    revision = connection.execute(select(environment_revisions).where(
        environment_revisions.c.operation_id == receipt.operation_id)).mappings().one_or_none()
    if (revision is None or revision["binding_id"] != binding.binding_id
            or revision["plan_id"] != plan.object_id or revision["environment_revision"] != receipt.environment_revision
            or row["active_operation_id"] != receipt.operation_id
            or row["environment_revision"] != receipt.environment_revision
            or row["release_id"] != plan.value.release_id
            or row["config_revision_id"] != approval.config_revision_id):
        raise TaskBoundaryError("remote_closeout_revision_mismatch")
    grants = connection.execute(select(remote_grants).where(
        remote_grants.c.id.in_(receipt.closed_grant_ids))).mappings().all()
    if (len(grants) != len(receipt.closed_grant_ids)
            or any(grant["operation_id"] != receipt.operation_id
                   or grant["digest"] != delivery_digest(grant["value_json"]) for grant in grants)):
        raise TaskBoundaryError("remote_closeout_grants_invalid")
    if connection.scalar(select(remote_results.c.id).where(
        remote_results.c.operation_id == receipt.operation_id,
        remote_results.c.step_id != "artifact_prepare").limit(1)) is not None:
        raise TaskBoundaryError("remote_closeout_runtime_started")
    from modules.delivery.remote_store import save_projection

    save_projection(connection, remote_closeouts, credential, receipt.operation_id, receipt, receipt.operation_id)
    return {"digest": digest, "status": "received"}


def close_deployment(context, plan_id, request):
    if not isinstance(context.actor, AuthenticatedActor) or context.actor.principal.kind != "human":
        raise TaskBoundaryError("deployment_closeout_requires_human", status_code=403)
    connection = context.uow.connection
    plan = read_object(connection, context.project_id, "plan", plan_id)
    approval = read_object(connection, context.project_id, "approval", plan_id).value
    if request.plan_digest != plan.digest or approval.plan_digest != plan.digest:
        raise TaskBoundaryError("deployment_approval_digest_mismatch", status_code=422)
    row, binding = lock_binding(connection, context.project_id, plan.value.binding.binding_id)
    receipt_row = connection.execute(select(remote_closeouts).where(
        remote_closeouts.c.id == approval.operation_id)).mappings().one_or_none()
    if receipt_row is None:
        raise TaskBoundaryError("remote_closeout_receipt_missing")
    receipt = RemoteCloseoutReceipt.model_validate(receipt_row["value_json"])
    if (receipt_row["operation_id"] != approval.operation_id or receipt.operation_id != approval.operation_id
            or receipt.plan_digest != plan.digest or receipt.binding_id != binding.binding_id
            or receipt_row["digest"] != delivery_digest(receipt) or request.receipt_digest != receipt_row["digest"]):
        raise TaskBoundaryError("remote_closeout_receipt_mismatch")
    previous_id = connection.scalar(select(deployment_closeouts.c.operation_id).where(
        deployment_closeouts.c.operation_id == approval.operation_id))
    if previous_id is not None:
        previous = read_object(connection, context.project_id, "closeout", previous_id)
        if (previous.value.plan_id != plan_id or previous.value.plan_digest != request.plan_digest
                or previous.value.receipt_digest != request.receipt_digest):
            raise TaskBoundaryError("deployment_closeout_identity_conflict")
        return previous
    revision = connection.execute(select(environment_revisions).where(
        environment_revisions.c.operation_id == approval.operation_id)).mappings().one_or_none()
    if (revision is None or revision["binding_id"] != binding.binding_id or revision["plan_id"] != plan_id
            or revision["environment_revision"] != plan.value.expected_state.environment_revision + 1
            or receipt.environment_revision != revision["environment_revision"]
            or row["environment_revision"] != revision["environment_revision"]
            or row["active_operation_id"] != approval.operation_id
            or row["release_id"] != plan.value.release_id or row["config_revision_id"] != approval.config_revision_id):
        raise TaskBoundaryError("deployment_closeout_revision_mismatch")
    if connection.scalar(select(remote_results.c.id).where(
        remote_results.c.operation_id == approval.operation_id,
        remote_results.c.step_id != "artifact_prepare").limit(1)) is not None:
        raise TaskBoundaryError("remote_closeout_runtime_started")
    value = DeploymentCloseout(operation_id=approval.operation_id, plan_id=plan_id, plan_digest=plan.digest,
        binding_id=binding.binding_id, target_id=binding.target_id, installation_id=binding.installation_id,
        receipt_digest=receipt_row["digest"], retained_resources=receipt.retained_resources,
        environment_revision=revision["environment_revision"], closed_by_user_id=context.actor.principal.subject_id,
        closed_at=connection.scalar(select(func.clock_timestamp())))
    result = write_object(context, "closeout", approval.operation_id, value)
    changed = connection.execute(update(environment_bindings).where(
        environment_bindings.c.binding_id == binding.binding_id,
        environment_bindings.c.active_operation_id == approval.operation_id,
        environment_bindings.c.environment_revision == revision["environment_revision"],
    ).values(active_operation_id=None, release_id=None, config_revision_id=None))
    if changed.rowcount != 1:
        raise TaskBoundaryError("deployment_closeout_revision_mismatch")
    return result
