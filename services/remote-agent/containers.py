"""Translate only the validated fixed recipe to bounded Docker Engine requests."""

import json
import time
from urllib.parse import quote

from .ledger import RemoteError


def labels(deployment, revision):
    plan = deployment.plan
    return {"cloudhelm.namespace": plan.binding.namespace, "cloudhelm.installation": plan.binding.installation_id,
        "cloudhelm.operation": deployment.operation_id, "cloudhelm.plan": deployment.plan_digest,
        "cloudhelm.release": plan.release_id, "cloudhelm.configuration": plan.configuration.configuration.config_revision_id,
        "cloudhelm.environment_revision": str(revision)}


def inventory(docker, deployment):
    filters = quote(json.dumps({"label": ["cloudhelm.namespace=" + deployment.plan.binding.namespace]}))
    return docker.api("GET", "/containers/json?all=1&filters=" + filters)


def prepare_storage(docker, deployment, revision, authorize_network):
    namespace = deployment.plan.binding.namespace
    known = labels(deployment, revision)
    networks = docker.api("GET", "/networks")
    network = next((item for item in networks if item["Name"] == namespace + "-application"), None)
    if network is None:
        network = docker.api("POST", "/networks/create", {"Name": namespace + "-application", "Driver": "bridge",
            "Internal": True, "Labels": known, "CheckDuplicate": True})
    elif network.get("Labels", {}).get("cloudhelm.installation") != known["cloudhelm.installation"] or not network["Internal"]:
        raise RemoteError("remote_network_ownership_conflict")
    authorize_network(network["Id"], namespace)
    volumes = docker.api("GET", "/volumes").get("Volumes") or []
    volume = next((item for item in volumes if item["Name"] == namespace + "-database"), None)
    if volume is None:
        docker.api("POST", "/volumes/create", {"Name": namespace + "-database", "Driver": "local", "Labels": known})
    elif volume.get("Labels", {}).get("cloudhelm.installation") != known["cloudhelm.installation"]:
        raise RemoteError("remote_volume_ownership_conflict")


def create_service(docker, resources, deployment, role, environment, revision):
    plan, namespace = deployment.plan, deployment.plan.binding.namespace
    spec = plan.normalized_spec.services[role]
    ports = {f"{item.target}/tcp": [{"HostIp": item.host_ip, "HostPort": str(item.published)}] for item in spec.ports}
    payload = {"Image": plan.step_inputs["service_update"]["local_tags"][role],
        "Env": [key + "=" + value for key, value in environment.items()],
        "Labels": labels(deployment, revision), "ExposedPorts": {key: {} for key in ports},
        "HostConfig": {"NetworkMode": namespace + "-application", "CgroupParent": resources.parent,
            "RestartPolicy": {"Name": spec.restart}, "Memory": plan.configuration.resources.memory_mib * 1024**2,
            "NanoCpus": plan.configuration.resources.cpu_millicores * 1_000_000,
            "PidsLimit": plan.configuration.resources.pids, "PortBindings": ports,
            "LogConfig": {"Type": "json-file", "Config": {"max-size": "1m", "max-file": "2"}},
            "Mounts": [{"Type": "volume", "Source": namespace + "-" + mount.source,
                "Target": mount.target, "ReadOnly": mount.read_only} for mount in spec.volumes]},
        "NetworkingConfig": {"EndpointsConfig": {namespace + "-application": {"Aliases": [role]}}}}
    if spec.command is not None:
        payload["Cmd"] = list(spec.command)
    if spec.healthcheck is not None:
        payload["Healthcheck"] = {"Test": list(spec.healthcheck.test), "Interval": 5_000_000_000,
            "Timeout": 3_000_000_000, "Retries": 3, "StartPeriod": 5_000_000_000}
    name = namespace + "-" + role
    docker.api("POST", "/containers/create?name=" + name, payload)
    docker.api("POST", "/containers/" + name + "/start")


def wait_postgres(docker, name, *, deadline):
    while time.monotonic() < deadline:
        value = docker.inspect(name)
        if value["State"].get("Health", {}).get("Status") == "healthy":
            return
        time.sleep(1)
    raise RemoteError("remote_database_readiness_unresolved")


def database_revision(docker, name):
    sql = "SELECT version_num FROM public.alembic_version"
    try:
        return docker.command("exec", name, "psql", "-U", "reference_owner", "-d", "reference_notes",
            "-At", "-c", sql).decode("utf-8").strip()
    except RemoteError:
        return None
