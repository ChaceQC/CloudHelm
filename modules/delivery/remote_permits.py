"""Issue one named-step grant after current authorization and preceding physical facts."""

from sqlalchemy import select

from modules.collaboration.errors import TaskBoundaryError
from modules.delivery.closeout_application import require_open_operation
from modules.delivery.deployment_control import begin_deployment, check_approval_current
from modules.delivery.deployment_store import lock_binding, read_object
from modules.delivery.release_recipe import delivery_digest
from modules.delivery.remote_store import approved_operation, save_projection, step_results
from modules.delivery.remote_capacity import reserve_target_capacity
from modules.delivery.remote_tables import remote_grants, remote_samples
from modules.delivery.target_facts import fresh_target
from modules.integration.validity import require_release_verification
from packages.contracts.p0.permit_contracts import PermitBinding, StepPermit
from packages.contracts.p1.remote_delivery import RemotePermit, RemoteTimeSample


def verify_mapping(connection, credential, request, clock):
    mapping = request.mapping
    row = connection.execute(select(remote_samples.c.value_json).where(
        remote_samples.c.id == "sample-" + delivery_digest({"credential": credential["credential_id"], "nonce": mapping.sample_nonce})[7:])).scalar_one_or_none()
    if row is None:
        raise TaskBoundaryError("remote_time_sample_missing")
    sample = RemoteTimeSample.model_validate(row)
    support = clock.support
    current = clock.now()
    if (support is None or mapping.time_epoch != clock.epoch or mapping.hub_incarnation != clock.incarnation
            or sample.hub_sample_us != mapping.hub_sample_us or sample.hello.executor_instance != mapping.executor_instance
            or sample.hello.mapping_epoch != mapping.mapping_epoch
            or sample.hello.clock_continuity_id != mapping.clock_continuity_id
            or sample.time_epoch != mapping.time_epoch or sample.channel_binding_id != mapping.channel_binding_id
            or mapping.support_evidence_digest != support.evidence_digest
            or mapping.hub_sample_error_us != support.sample_error_us
            or mapping.local_read_error_us != support.local_read_error_us
            or mapping.relative_rate_ppm != support.relative_rate_ppm
            or not 0 <= current - sample.hub_sample_us < 60_000_000):
        raise TaskBoundaryError("remote_time_mapping_invalid")
    return current


def issue_permit(uow, credential, request, clock):
    current = verify_mapping(uow.connection, credential, request, clock)
    context, plan, approval = approved_operation(uow, credential, request.operation_id)
    if request.plan_digest != plan.digest:
        raise TaskBoundaryError("remote_plan_digest_mismatch")
    steps = plan.value.steps
    matches = [index for index, step in enumerate(steps) if step.step_id == request.step_id]
    if len(matches) != 1:
        raise TaskBoundaryError("remote_step_unknown")
    index, step = matches[0], steps[matches[0]]
    row, binding = lock_binding(uow.connection, context.project_id, plan.value.binding.binding_id)
    require_open_operation(uow.connection, request.operation_id)
    results = step_results(uow.connection, request.operation_id)
    if step.step_id in results or any(s.step_id not in results or results[s.step_id].status != "succeeded" for s in steps[:index]):
        raise TaskBoundaryError("remote_previous_execution_unresolved")
    predecessors = [results[s.step_id].model_dump(mode="json") for s in steps[:index]]
    target, observed, now = fresh_target(uow.connection, binding)
    check_approval_current(context, plan, approval, now)
    if (request.mapping.executor_instance != target.executor_instance or target.executor_instance != plan.value.executor_instance
            or target.generation != plan.value.generation or request.mapping.executor_instance != observed.executor_instance
            or observed.state.unregistered_resources
            or not set(plan.value.configuration.configuration.secret_refs.values()) <= set(observed.available_secret_refs)):
        raise TaskBoundaryError("remote_execution_gate_closed")
    expected = plan.value.expected_state if index == 0 else results[steps[index - 1].step_id].state
    if (observed.state != expected or request.actual_state_digest != delivery_digest(expected)
            or request.predecessor_results_digest != delivery_digest(predecessors)):
        raise TaskBoundaryError("remote_intermediate_state_drift")
    reserve_target_capacity(uow.connection, plan.value, target)
    previous = uow.connection.execute(select(remote_grants).where(
        remote_grants.c.operation_id == request.operation_id, remote_grants.c.step_id == step.step_id)).mappings().all()
    if len(previous) > 64:
        raise TaskBoundaryError("remote_grant_limit")
    key = "grant-" + delivery_digest(request)[7:]
    for old in previous:
        if old["id"] == key:
            return RemotePermit.model_validate(old["value_json"]["permit"])
        if old["id"] not in request.closed_unstarted_grants:
            raise TaskBoundaryError("remote_old_start_path_not_closed")
    release = read_object(uow.connection, context.project_id, "release", plan.value.release_id)
    require_release_verification(uow.connection, context.project_id, release.value)
    revision = begin_deployment(context, plan.object_id, plan.digest)
    if row["active_operation_id"] not in (None, request.operation_id):
        raise TaskBoundaryError("remote_environment_execution_conflict")
    remaining = int((min(plan.value.start_before, approval.expires_at) - now).total_seconds() * 1_000_000)
    lifetime = min(30_000_000, remaining)
    if lifetime <= 0:
        raise TaskBoundaryError("deployment_approval_expired")
    grant = StepPermit(grant_id=key, binding=PermitBinding(operation_id=request.operation_id,
        plan_digest=plan.digest, step_id=step.step_id, input_digest=step.input_digest,
        executor_instance=target.executor_instance, hub_incarnation=clock.incarnation, generation=target.generation,
        environment_execution_id=request.operation_id, environment_config_revision_id=approval.config_revision_id,
        expected_environment_revision_id="environment-" + str(revision), control_revision=revision,
        authorization_revision=approval.authorization_revision, predecessor_results_digest=request.predecessor_results_digest,
        actual_state_digest=request.actual_state_digest), time_epoch=clock.epoch,
        mapping_epoch=request.mapping.mapping_epoch, clock_continuity_id=request.mapping.clock_continuity_id,
        channel_binding_id=request.mapping.channel_binding_id, issued_at=current, expires_at=current + lifetime)
    result = RemotePermit(grant=grant, environment_revision=revision)
    save_projection(uow.connection, remote_grants, credential, key,
        {"permit": result.model_dump(mode="json"), "request": request.model_dump(mode="json")}, request.operation_id, step.step_id)
    return result
