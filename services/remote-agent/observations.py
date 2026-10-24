"""Read actual service identity and configuration; a full vector alone is not a new revision."""

from packages.contracts.p1.delivery_records import EnvironmentState, ObservedService
from packages.contracts.p1.remote_delivery import RemotePlan
from . import containers


def _origin(ledger, deployment, labels, role):
    if labels.get("cloudhelm.operation") == deployment.operation_id:
        step_id = "database_migrate" if role == "postgres" else "service_update"
        return deployment if ledger.step(deployment.operation_id, step_id) is not None else None
    row = ledger.db.execute("SELECT payload FROM operations WHERE id=?", (labels.get("cloudhelm.operation"),)).fetchone()
    if row is not None:
        previous = RemotePlan.model_validate_json(row[0])
        if previous.plan.binding == deployment.plan.binding:
            return previous
    return None


def observe(docker, ledger, deployment, environment):
    plan, services, unknown, desired_matches = deployment.plan, {}, [], []
    known = {plan.binding.namespace + "-" + role: role for role in plan.normalized_spec.services}
    for item in containers.inventory(docker, deployment):
        names = [name.removeprefix("/") for name in item["Names"]]
        if len(names) != 1 or names[0] not in known:
            unknown.append("unregistered-" + item["Id"][:32])
            continue
        role = known[names[0]]
        actual = docker.inspect(names[0])
        labels = actual["Config"].get("Labels") or {}
        origin = _origin(ledger, deployment, labels, role)
        if (origin is None or labels.get("cloudhelm.installation") != plan.binding.installation_id
                or labels.get("cloudhelm.plan") != origin.plan_digest
                or labels.get("cloudhelm.release") != origin.plan.release_id
                or labels.get("cloudhelm.configuration") != origin.plan.configuration.configuration.config_revision_id):
            unknown.append("unregistered-" + role)
            origin = deployment
        artifact = next(value for value in origin.manifest.artifacts if value.role == role)
        expected_id = artifact.manifest_digest if plan.docker_identity_kind == "oci_manifest" else artifact.config_digest
        services[role] = ObservedService(manifest_digest=artifact.manifest_digest, config_digest=artifact.config_digest,
            loaded_image_id=actual["Image"], docker_identity_kind=plan.docker_identity_kind,
            state="running" if actual["State"]["Running"] else "stopped")
        if (actual["Image"] != expected_id or set(actual["NetworkSettings"]["Networks"]) != {plan.binding.namespace + "-application"}
                or actual["HostConfig"]["RestartPolicy"]["Name"] != origin.plan.normalized_spec.services[role].restart):
            unknown.append("drift-" + role)
        wanted = next(value for value in deployment.manifest.artifacts if value.role == role)
        wanted_id = wanted.manifest_digest if plan.docker_identity_kind == "oci_manifest" else wanted.config_digest
        actual_environment = dict(value.split("=", 1) for value in actual["Config"].get("Env", ()) if "=" in value)
        if any(actual_environment.get(key) != value for key, value in environment(origin, role).items()):
            unknown.append("configuration-drift-" + role)
        desired_matches.append(actual["Image"] == wanted_id and all(actual_environment.get(key) == value
            for key, value in environment(deployment, role).items()))
    # A same-image configuration change must not appear applied before its update intent.
    update_intent = ledger.step(deployment.operation_id, "service_update") is not None
    complete = (set(services) == {"postgres", "backend", "frontend"} and not unknown
        and all(desired_matches) and update_intent)
    baseline = plan.expected_state
    revision = containers.database_revision(docker, plan.binding.namespace + "-postgres") if "postgres" in services else baseline.database_revision
    return EnvironmentState(environment_revision=baseline.environment_revision + 1 if complete else baseline.environment_revision,
        release_id=plan.release_id if complete else baseline.release_id,
        config_revision_id=plan.configuration.configuration.config_revision_id if complete else baseline.config_revision_id,
        services=services, database_revision=revision, unregistered_resources=tuple(unknown))
