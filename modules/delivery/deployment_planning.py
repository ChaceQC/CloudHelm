"""Construct complete finite archive plans from immutable inputs and fresh target facts."""

from datetime import timedelta

from modules.collaboration.errors import TaskBoundaryError
from modules.delivery.compose import bind_environment_config
from modules.delivery.deployment_store import lock_binding, read_object, write_object
from modules.delivery.environment_commands import check_resources
from modules.delivery.release_recipe import delivery_digest, parameter_contract_digest
from modules.delivery.target_facts import fresh_target
from packages.contracts.p0.permit_contracts import PlanStep, STEP_LIMITS
from packages.contracts.p1.delivery_records import DeploymentPlan

MIGRATION_REVISION = "0002_add_updated_at_index"
STEP_KINDS = ("artifact_prepare", "runtime_input_check", "database_migrate", "service_update", "health_verify")


def check_baseline(connection, project_id, row, observation):
    state = observation.state
    if (state.environment_revision != row["environment_revision"] or state.release_id != row["release_id"]
            or state.config_revision_id != row["config_revision_id"] or state.unregistered_resources):
        raise TaskBoundaryError("replan_required")
    if row["environment_revision"] == 0:
        if state.services or state.database_revision is not None or state.release_id is not None:
            raise TaskBoundaryError("first_installation_not_empty")
    else:
        current = read_object(connection, project_id, "release", row["release_id"]).value
        if set(state.services) != {item.role for item in current.artifacts} or state.database_revision != MIGRATION_REVISION:
            raise TaskBoundaryError("replan_required")
        for item in current.artifacts:
            service = state.services[item.role]
            expected = item.manifest_digest if service.docker_identity_kind == "oci_manifest" else item.config_digest
            if (service.manifest_digest != item.manifest_digest or service.config_digest != item.config_digest
                    or service.loaded_image_id != expected):
                raise TaskBoundaryError("replan_required")
    if row["active_operation_id"] is not None:
        raise TaskBoundaryError("environment_execution_pending")


def plan_steps(manifest, binding, config, normalized, state, target):
    artifacts = {item.role: item for item in manifest.artifacts}
    local_tags = {role: f"cloudhelm/{binding.namespace}/{role}:{item.config_digest[7:]}"
                  for role, item in artifacts.items()}
    inputs = {
        "artifact_prepare": {"delivery_mode": "archive", "artifacts": [item.model_dump(mode="json") for item in manifest.artifacts],
            "local_tags": local_tags, "verify": ["archive_sha256", "config_digest", "platform", "loaded_image_id"],
            "pull": "never", "build": False,
            "archive_bytes": sum(item.archive_bytes for item in manifest.artifacts),
            "total_writable_disk_limit_bytes": config.resources.disk_bytes,
            "require_load_unpack_space_preflight": True},
        "runtime_input_check": {"spec": normalized.model_dump(mode="json"), "namespace": binding.namespace,
            "local_tags": local_tags, "resources": config.resources.model_dump(mode="json"),
            "resource_scope": "all_processes_and_writable_storage", "secret_refs": config.configuration.secret_refs,
            "networks": list(normalized.networks), "volumes": list(normalized.volumes)},
        "database_migrate": {"backend_artifact": artifacts["backend"].model_dump(mode="json"),
            "postgres_artifact": artifacts["postgres"].model_dump(mode="json"),
            "migration_files": [item.model_dump(mode="json") for item in manifest.definition.migrations],
            "expected_database_revision": state.database_revision, "target_database_revision": MIGRATION_REVISION,
            "command": ["alembic", "upgrade", MIGRATION_REVISION], "database_identity": "reference_owner",
            "application_identity": "reference_app", "on_unknown": "query_original_operation",
            "automatic_rollback": False},
        "service_update": {"namespace": binding.namespace, "spec_digest": normalized.plan_digest,
            "local_tags": local_tags, "docker_identity_kind": target.docker_identity_kind,
            "expected_loaded_image_ids": {role: item.manifest_digest if target.docker_identity_kind == "oci_manifest"
                else item.config_digest for role, item in artifacts.items()},
            "expected_config_digests": {role: item.config_digest for role, item in artifacts.items()},
            "order": ["postgres", "backend", "frontend"], "downtime_services": ["backend", "frontend"],
            "pull": "never", "build": False},
        "health_verify": {"window_seconds": 30, "required_services": ["postgres", "backend", "frontend"],
            "database_revision": MIGRATION_REVISION,
            "http_probes": [{"service": "backend", "path": path, "expected_status": 200} for path in ("/health", "/ready")]
                + [{"service": "frontend", "path": path, "expected_status": 200} for path in ("/", "/api/notes")],
            "on_failure": "stop_and_reconcile"},
    }
    steps, previous = [], {"initial_state_digest": delivery_digest(state)}
    for kind in STEP_KINDS:
        post = {"required_fact": kind + "_verified", "subject_digest": delivery_digest(inputs[kind])}
        limit, stop_mode = STEP_LIMITS[kind]
        steps.append(PlanStep(step_id=kind, kind=kind, input_ref=kind, input_digest=delivery_digest(inputs[kind]),
            preconditions_digest=delivery_digest(previous), postconditions_digest=delivery_digest(post),
            max_runtime_seconds=limit, stop_mode=stop_mode, result_query_ref="original-operation-" + kind))
        inputs[kind]["preconditions"] = previous
        inputs[kind]["postconditions"] = post
        # Conditions are part of the fixed input, too.
        steps[-1] = steps[-1].model_copy(update={"input_digest": delivery_digest(inputs[kind])})
        previous = post
    return tuple(steps), inputs


def create_plan(context, binding_id, request):
    connection = context.uow.connection
    release = read_object(connection, context.project_id, "release", request.release_id)
    config = read_object(connection, context.project_id, "configuration", request.config_revision_id).value
    row, binding = lock_binding(connection, context.project_id, binding_id)
    if config.binding_id != binding_id or config.parameter_contract_digest != parameter_contract_digest(release.value.runtime):
        raise TaskBoundaryError("deployment_configuration_mismatch", status_code=422)
    target, observed, now = fresh_target(connection, binding)
    check_baseline(connection, context.project_id, row, observed)
    if (request.expected_environment_revision != row["environment_revision"]
            or request.expected_state_digest != delivery_digest(observed.state)):
        raise TaskBoundaryError("replan_required")
    if not now < request.start_before <= now + timedelta(hours=24):
        raise TaskBoundaryError("deployment_start_deadline_invalid", status_code=422)
    check_resources(config.resources, target)
    if not set(config.configuration.secret_refs.values()) <= set(observed.available_secret_refs):
        raise TaskBoundaryError("deployment_secret_reference_unavailable")
    if not set(STEP_KINDS) <= set(target.supported_steps):
        raise TaskBoundaryError("deployment_step_unsupported")
    normalized = bind_environment_config(release.value.runtime, config.configuration)
    steps, inputs = plan_steps(release.value, binding, config, normalized, observed.state, target)
    if inputs["artifact_prepare"]["archive_bytes"] > config.resources.disk_bytes:
        raise TaskBoundaryError("deployment_archive_space_insufficient")
    # The id is derived before adding itself; its entire final payload has a separate digest.
    identity = delivery_digest({"project": context.project_id, "binding": binding_id, **request.model_dump(mode="json"),
        "manifest": release.digest, "configuration": delivery_digest(config), "executor": target.model_dump(mode="json"),
        "policy": context.authorization.envelope.policy_revision,
        "authorization": context.authorization.envelope.permission_revision})
    plan = DeploymentPlan(plan_id="plan-" + identity[7:], project_id=context.project_id,
        release_id=request.release_id, manifest_digest=release.digest, variant_digest=release.value.variant_digest,
        binding=binding, executor_instance=target.executor_instance, generation=target.generation,
        docker_identity_kind=target.docker_identity_kind,
        expected_state=observed.state, expected_state_digest=delivery_digest(observed.state), configuration=config,
        normalized_spec=normalized, steps=steps, step_inputs=inputs, start_before=request.start_before,
        max_runtime_seconds=sum(step.max_runtime_seconds for step in steps),
        policy_revision=context.authorization.envelope.policy_revision,
        authorization_revision=context.authorization.envelope.permission_revision)
    return write_object(context, "plan", plan.plan_id, plan)
