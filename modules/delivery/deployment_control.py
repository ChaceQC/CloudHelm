"""Human approval and fresh preflight; neither is a physical execution receipt."""

from sqlalchemy import insert, select, update

from database.readiness import assert_schema_ready
from modules.collaboration.errors import TaskBoundaryError
from modules.delivery.compose import bind_environment_config
from modules.delivery.deployment_planning import STEP_KINDS, check_baseline
from modules.delivery.deployment_store import lock_binding, read_object, write_object
from modules.delivery.deployment_tables import deployment_approvals, environment_bindings, environment_revisions
from modules.delivery.environment_commands import check_resources
from modules.delivery.release_recipe import delivery_digest
from modules.delivery.target_facts import fresh_target
from modules.identity.actors import AuthenticatedActor, AuthoritativeResource, actor_for_command
from modules.identity.authorization import authorize_current
from modules.identity.tables import device_sessions
from modules.sync.events import append_event
from packages.contracts.p1.delivery_records import DeploymentApproval, DeploymentPreflight, DeploymentRegisteredEvent


def validate_preflight(context, plan_object):
    connection, plan = context.uow.connection, plan_object.value
    row, binding = lock_binding(connection, context.project_id, plan.binding.binding_id)
    target, observation, now = fresh_target(connection, binding)
    check_baseline(connection, context.project_id, row, observation)
    if binding != plan.binding or observation.state != plan.expected_state:
        raise TaskBoundaryError("replan_required")
    if (plan.expected_state_digest != delivery_digest(observation.state)
            or plan.executor_instance != target.executor_instance or plan.generation != target.generation
            or plan.docker_identity_kind != target.docker_identity_kind):
        raise TaskBoundaryError("replan_required")
    current = context.authorization.envelope
    if current.policy_revision != plan.policy_revision or current.permission_revision != plan.authorization_revision:
        raise TaskBoundaryError("deployment_policy_changed")
    if now >= plan.start_before:
        raise TaskBoundaryError("deployment_plan_expired")
    release = read_object(connection, context.project_id, "release", plan.release_id)
    configuration = read_object(connection, context.project_id, "configuration",
        plan.configuration.configuration.config_revision_id).value
    if (release.digest != plan.manifest_digest or release.value.variant_digest != plan.variant_digest
            or configuration != plan.configuration
            or bind_environment_config(release.value.runtime, configuration.configuration) != plan.normalized_spec):
        raise TaskBoundaryError("deployment_plan_binding_invalid")
    if not set(configuration.configuration.secret_refs.values()) <= set(observation.available_secret_refs):
        raise TaskBoundaryError("deployment_secret_reference_unavailable")
    if not set(STEP_KINDS) <= set(target.supported_steps):
        raise TaskBoundaryError("deployment_step_unsupported")
    check_resources(configuration.resources, target)
    return row, now


def approve_plan(context, plan_id, request):
    if context.actor.principal.kind != "human" or not isinstance(context.actor, AuthenticatedActor):
        raise TaskBoundaryError("deployment_approval_requires_human", status_code=403)
    plan = read_object(context.uow.connection, context.project_id, "plan", plan_id)
    if request.plan_digest != plan.digest:
        raise TaskBoundaryError("deployment_approval_digest_mismatch", status_code=422)
    _, now = validate_preflight(context, plan)
    if not now < request.expires_at <= plan.value.start_before:
        raise TaskBoundaryError("deployment_approval_expiry_invalid", status_code=422)
    exists = context.uow.connection.scalar(select(deployment_approvals.c.plan_id).where(
        deployment_approvals.c.plan_id == plan_id))
    if exists is not None:
        previous = read_object(context.uow.connection, context.project_id, "approval", plan_id)
        if previous.value.expires_at != request.expires_at:
            raise TaskBoundaryError("deployment_approval_immutable")
        return previous
    if context.enqueue_deployment is None:
        raise TaskBoundaryError("deployment_handoff_unavailable")
    value = DeploymentApproval(approval_id="approval-" + plan.digest[7:], plan_id=plan_id,
        plan_digest=plan.digest, binding_id=plan.value.binding.binding_id,
        config_revision_id=plan.value.configuration.configuration.config_revision_id,
        approver_user_id=context.actor.principal.subject_id,
        authorization_revision=context.authorization.envelope.permission_revision,
        policy_revision=context.authorization.envelope.policy_revision, approved_at=now,
        expires_at=request.expires_at, operation_id="deployment-" + plan.digest[7:])
    result = write_object(context, "approval", plan_id, value)
    context.enqueue_deployment(context.uow, operation_id=value.operation_id, command_id=context.envelope.command_id,
        business_id=plan_id, advance_revision=1, request_digest=context.envelope.request_digest)
    return result


def approved_preflight(context, plan_id, digest):
    plan = read_object(context.uow.connection, context.project_id, "plan", plan_id)
    approval = read_object(context.uow.connection, context.project_id, "approval", plan_id).value
    if digest != plan.digest or approval.plan_digest != plan.digest:
        raise TaskBoundaryError("deployment_approval_digest_mismatch", status_code=422)
    _, now = validate_preflight(context, plan)
    if not approval.approved_at <= now < approval.expires_at:
        raise TaskBoundaryError("deployment_approval_expired")
    # An operator's access cannot replace the original human approver's current access.
    row = context.uow.connection.execute(select(deployment_approvals.c.command_id).where(
        deployment_approvals.c.plan_id == plan_id)).one()
    actor = actor_for_command(context.uow, row.command_id)
    decision = authorize_current(context.uow, actor, AuthoritativeResource(
        context.project_id, "project", context.project_id), "deployment.approve")
    if (decision.envelope.policy_revision != approval.policy_revision
            or decision.envelope.permission_revision != approval.authorization_revision):
        raise TaskBoundaryError("deployment_policy_changed")
    session = context.uow.connection.execute(select(device_sessions).where(
        device_sessions.c.session_id == actor.audit_session_id,
    )).mappings().one_or_none()
    if (session is None or session["user_id"] != approval.approver_user_id or session["revoked_at"] is not None
            or not session["issued_at"] <= now < session["expires_at"]):
        raise TaskBoundaryError("deployment_approval_credential_not_current")
    return DeploymentPreflight(plan_id=plan_id, operation_id=approval.operation_id,
        plan_digest=plan.digest, checked_at=now)


def begin_deployment(context, plan_id, digest):
    """Internal P1.4-02 handoff: call under target execution ownership before effects.

    An active unknown operation is never cleared here. Retrying its own claim
    cannot allocate another desired revision. This function grants no step permit.
    """
    connection = context.uow.connection
    approval = read_object(connection, context.project_id, "approval", plan_id).value
    plan = read_object(connection, context.project_id, "plan", plan_id)
    row, _ = lock_binding(connection, context.project_id, plan.value.binding.binding_id)
    existing = connection.execute(select(environment_revisions).where(
        environment_revisions.c.operation_id == approval.operation_id)).mappings().one_or_none()
    if existing is not None:
        if (plan.digest != digest or existing["plan_id"] != plan_id
                or row["active_operation_id"] != approval.operation_id):
            raise TaskBoundaryError("deployment_operation_conflict")
        assert_schema_ready(connection)
        return existing["environment_revision"]
    approved_preflight(context, plan_id, digest)
    if row["environment_revision"] == 9007199254740991:
        raise TaskBoundaryError("environment_revision_exhausted")
    revision = row["environment_revision"] + 1
    changed = connection.execute(update(environment_bindings).where(
        environment_bindings.c.binding_id == plan.value.binding.binding_id,
        environment_bindings.c.environment_revision == plan.value.expected_state.environment_revision,
        environment_bindings.c.active_operation_id.is_(None),
    ).values(environment_revision=revision, active_operation_id=approval.operation_id,
        release_id=plan.value.release_id, config_revision_id=approval.config_revision_id))
    if changed.rowcount != 1:
        raise TaskBoundaryError("replan_required")
    connection.execute(insert(environment_revisions).values(binding_id=plan.value.binding.binding_id,
        environment_revision=revision, plan_id=plan_id, operation_id=approval.operation_id))
    append_event(connection, command_id=context.envelope.command_id, project_id=context.project_id,
        aggregate_kind="deployment", aggregate_id=approval.operation_id, aggregate_version=revision,
        event_type="deployment.execution_registered", schema_version="p1-deployment-event-r1",
        payload=DeploymentRegisteredEvent(plan_id=plan_id, plan_digest=digest, environment_revision=revision))
    return revision
