#!/usr/bin/env python3
"""Run the isolated P0 Compose and two-stage deployment seam probe.

This is a local design experiment. It is not a product deployment command and
does not read user configuration, environment values, or secret material.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import copy
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import rfc8785
import yaml
from yaml.tokens import AliasToken, AnchorToken, TagToken


CONTRACT = "cloudhelm.p0.experimental"
APP_IMAGE = "example.invalid/cloudhelm/api@sha256:" + "a" * 64
WORKER_IMAGE = "example.invalid/cloudhelm/worker@sha256:" + "b" * 64
PARAM_MARKER = "__CH_PARAMETER:APP_MODE__"
SECRET_MARKER = "__CH_SECRET_REF:API_TOKEN__"
SECRET_REF = "secret://synthetic/api-token@v1"
ROOT_FIELDS = {"name", "services", "networks", "volumes", "x-cloudhelm"}
SERVICE_FIELDS = {"image", "environment", "networks", "volumes", "restart", "healthcheck"}
DENIED_FIELDS = {
    "include",
    "extends",
    "profiles",
    "build",
    "privileged",
    "devices",
    "network_mode",
    "env_file",
    "volumes_from",
    "secrets",
    "configs",
}
INTERPOLATION = re.compile(r"\$(?:\{|[A-Za-z_])")


class ProbeRefusal(ValueError):
    """A deliberately unsupported or unsafe input with a source position."""


class StrictLoader(yaml.SafeLoader):
    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict:
        result: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            if key_node.tag == "tag:yaml.org,2002:merge":
                mark = key_node.start_mark
                raise ProbeRefusal(f"line {mark.line + 1}: YAML merge inheritance is unsupported")
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str):
                mark = key_node.start_mark
                raise ProbeRefusal(f"line {mark.line + 1}: mapping keys must be strings")
            if key in result:
                mark = key_node.start_mark
                raise ProbeRefusal(f"line {mark.line + 1}: duplicate YAML key {key!r}")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def canonical_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def reject_interpolation(value: Any, path: str = "$") -> None:
    if isinstance(value, str) and INTERPOLATION.search(value):
        raise ProbeRefusal(f"{path}: Compose interpolation from process or dotenv inputs is unsupported")
    if isinstance(value, dict):
        for key, child in value.items():
            reject_interpolation(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_interpolation(child, f"{path}[{index}]")


def parse_source(text: str) -> dict[str, Any]:
    for token in yaml.scan(text):
        if isinstance(token, (AnchorToken, AliasToken)):
            raise ProbeRefusal(f"line {token.start_mark.line + 1}: YAML anchor/alias inheritance is unsupported")
        if isinstance(token, TagToken):
            raise ProbeRefusal(f"line {token.start_mark.line + 1}: custom YAML tags are unsupported")
    try:
        document = yaml.load(text, Loader=StrictLoader)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f"line {mark.line + 1}: " if mark else ""
        raise ProbeRefusal(f"{where}invalid YAML") from None
    if not isinstance(document, dict):
        raise ProbeRefusal("$: Compose document must be a mapping")
    reject_interpolation(document)
    validate_source(document)
    return document


def mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ProbeRefusal(f"{path}: expected an object with string keys")
    return value


def reject_unknown(value: dict[str, Any], allowed: set[str], path: str) -> None:
    for key in value:
        if key in DENIED_FIELDS:
            raise ProbeRefusal(f"{path}.{key}: unsupported Compose feature")
        if key not in allowed:
            raise ProbeRefusal(f"{path}.{key}: unknown or unsupported field")


def validate_extensions(document: dict[str, Any]) -> dict[str, Any]:
    ext = mapping(document.get("x-cloudhelm"), "$.x-cloudhelm")
    reject_unknown(ext, {"contract", "parameters", "secret_refs"}, "$.x-cloudhelm")
    if ext.get("contract") != CONTRACT:
        raise ProbeRefusal("$.x-cloudhelm.contract: expected the P0 experimental contract marker")
    params = mapping(ext.get("parameters"), "$.x-cloudhelm.parameters")
    for name, item in params.items():
        spec = mapping(item, f"$.x-cloudhelm.parameters.{name}")
        reject_unknown(spec, {"service", "target", "kind", "allowed_values"}, f"$.x-cloudhelm.parameters.{name}")
        if set(spec) != {"service", "target", "kind", "allowed_values"}:
            raise ProbeRefusal(f"$.x-cloudhelm.parameters.{name}: incomplete parameter contract")
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", name):
            raise ProbeRefusal(f"$.x-cloudhelm.parameters.{name}: parameter name is invalid")
        if spec["kind"] != "enum" or spec["target"] != f"environment.{name}":
            raise ProbeRefusal(f"$.x-cloudhelm.parameters.{name}: only enum environment slots are supported")
        if not isinstance(spec["service"], str) or not isinstance(spec["allowed_values"], list):
            raise ProbeRefusal(f"$.x-cloudhelm.parameters.{name}: malformed parameter contract")
        if not spec["allowed_values"] or any(not isinstance(v, str) for v in spec["allowed_values"]):
            raise ProbeRefusal(f"$.x-cloudhelm.parameters.{name}.allowed_values: expected nonempty strings")
    refs = mapping(ext.get("secret_refs"), "$.x-cloudhelm.secret_refs")
    for name, item in refs.items():
        spec = mapping(item, f"$.x-cloudhelm.secret_refs.{name}")
        reject_unknown(spec, {"service", "target"}, f"$.x-cloudhelm.secret_refs.{name}")
        if set(spec) != {"service", "target"}:
            raise ProbeRefusal(f"$.x-cloudhelm.secret_refs.{name}: incomplete secret-reference contract")
        if spec["target"] != f"environment.{name}" or not isinstance(spec["service"], str):
            raise ProbeRefusal(f"$.x-cloudhelm.secret_refs.{name}: only named environment references are supported")
    if set(params) & set(refs):
        raise ProbeRefusal("$.x-cloudhelm: parameter and secret-reference names overlap")
    return ext


def validate_source(document: dict[str, Any]) -> None:
    reject_unknown(document, ROOT_FIELDS, "$")
    if not isinstance(document.get("name"), str) or not document["name"]:
        raise ProbeRefusal("$.name: a fixed Compose project name is required")
    services = mapping(document.get("services"), "$.services")
    if not services:
        raise ProbeRefusal("$.services: at least one service is required")
    networks = mapping(document.get("networks", {}), "$.networks")
    volumes = mapping(document.get("volumes", {}), "$.volumes")
    for name, spec in networks.items():
        network = mapping(spec or {}, f"$.networks.{name}")
        reject_unknown(network, {"driver", "internal"}, f"$.networks.{name}")
        if network.get("internal", False) is not True:
            raise ProbeRefusal(f"$.networks.{name}.internal: only internal project networks are supported")
    for name, spec in volumes.items():
        volume = mapping(spec or {}, f"$.volumes.{name}")
        reject_unknown(volume, {"driver", "name"}, f"$.volumes.{name}")
        if volume.get("driver", "local") != "local":
            raise ProbeRefusal(f"$.volumes.{name}.driver: only the managed local volume driver is supported")
    for service_name, raw_spec in services.items():
        path = f"$.services.{service_name}"
        spec = mapping(raw_spec, path)
        reject_unknown(spec, SERVICE_FIELDS, path)
        image = spec.get("image")
        if not isinstance(image, str) or "@sha256:" not in image:
            raise ProbeRefusal(f"{path}.image: fixed digest-pinned image required; build tags are unsupported")
        environment = mapping(spec.get("environment", {}), f"{path}.environment")
        for key, value in environment.items():
            if not isinstance(value, str):
                raise ProbeRefusal(f"{path}.environment.{key}: values must be fixed strings or P0 markers")
        service_networks = spec.get("networks", [])
        if isinstance(service_networks, dict):
            names = set(service_networks)
        elif isinstance(service_networks, list):
            names = set(service_networks)
        else:
            raise ProbeRefusal(f"{path}.networks: expected a project-network list or mapping")
        if not names <= set(networks):
            raise ProbeRefusal(f"{path}.networks: undeclared or external network reference")
        mount_list = spec.get("volumes", [])
        if not isinstance(mount_list, list):
            raise ProbeRefusal(f"{path}.volumes: only explicit long-syntax named volumes are supported")
        for index, raw_mount in enumerate(mount_list):
            mount_path = f"{path}.volumes[{index}]"
            if isinstance(raw_mount, str):
                lowered = raw_mount.lower()
                if "docker.sock" in lowered or "/var/run/docker" in lowered:
                    raise ProbeRefusal(f"{mount_path}: Docker socket access is unsupported")
                raise ProbeRefusal(f"{mount_path}: short-syntax bind/volume mounts are unsupported")
            mount = mapping(raw_mount, mount_path)
            reject_unknown(mount, {"type", "source", "target", "read_only"}, mount_path)
            source = mount.get("source")
            target = mount.get("target")
            if isinstance(source, str) and ("docker.sock" in source.lower() or "/var/run/docker" in source.lower()):
                raise ProbeRefusal(f"{mount_path}.source: Docker socket access is unsupported")
            if mount.get("type") != "volume":
                raise ProbeRefusal(f"{mount_path}.type: bind mounts and device paths are unsupported")
            if not isinstance(source, str) or source not in volumes:
                raise ProbeRefusal(f"{mount_path}.source: external or undeclared volume is unsupported")
            if not isinstance(target, str) or not target.startswith("/") or target in {"/", "/var/run/docker.sock"}:
                raise ProbeRefusal(f"{mount_path}.target: expected a safe absolute container path")
        if "healthcheck" in spec:
            health = mapping(spec["healthcheck"], f"{path}.healthcheck")
            reject_unknown(health, {"test", "interval", "timeout", "retries", "start_period", "disable"}, f"{path}.healthcheck")
        if "restart" in spec and spec["restart"] not in {"no", "always", "on-failure", "unless-stopped"}:
            raise ProbeRefusal(f"{path}.restart: unsupported restart policy")
    ext = validate_extensions(document)
    for collection_name in ("parameters", "secret_refs"):
        collection = ext.get(collection_name, {})
        for name, target in collection.items():
            service = target["service"]
            if service not in services:
                raise ProbeRefusal(f"$.x-cloudhelm.{collection_name}.{name}.service: unknown service {service}")
            env_name = name
            current = services[service].get("environment", {}).get(env_name)
            marker = f"__CH_PARAMETER:{name}__" if collection_name == "parameters" else f"__CH_SECRET_REF:{name}__"
            if current != marker:
                raise ProbeRefusal(f"$.services.{service}.environment.{env_name}: expected marker for declared slot")
    for service, spec in services.items():
        for env_name, value in spec.get("environment", {}).items():
            if value.startswith("__CH_PARAMETER:") and env_name not in ext.get("parameters", {}):
                raise ProbeRefusal(f"$.services.{service}.environment.{env_name}: undeclared parameter marker")
            if value.startswith("__CH_SECRET_REF:") and env_name not in ext.get("secret_refs", {}):
                raise ProbeRefusal(f"$.services.{service}.environment.{env_name}: undeclared secret-reference marker")
    reject_dangerous_service_values(services)


def reject_dangerous_service_values(services: dict[str, Any]) -> None:
    for service, spec in services.items():
        for field in ("image", "environment", "networks", "volumes", "restart", "healthcheck"):
            rendered = json.dumps(spec.get(field, ""), ensure_ascii=False).lower()
            if "docker.sock" in rendered or "/var/run/docker" in rendered:
                raise ProbeRefusal(f"$.services.{service}.{field}: Docker socket access is unsupported")
            if "network_mode" in rendered and "host" in rendered:
                raise ProbeRefusal(f"$.services.{service}.network_mode: host network is unsupported")


def compose_version(docker: str) -> str:
    with tempfile.TemporaryDirectory(prefix="cloudhelm-p0-docker-config-") as tmp:
        environment = {"PATH": str(Path(docker).parent) + os.pathsep + "/usr/bin" + os.pathsep + "/bin", "DOCKER_CONFIG": tmp, "LANG": "C.UTF-8"}
        result = subprocess.run([docker, "compose", "version", "--short"], check=True, capture_output=True, text=True, encoding="utf-8", env=environment)
        return result.stdout.strip()


def compose_normalize(document_text: str, docker: str) -> dict[str, Any]:
    parsed = parse_source(document_text)
    with tempfile.TemporaryDirectory(prefix="cloudhelm-p0-compose-") as tmp:
        root = Path(tmp)
        docker_config = root / "docker-config"
        docker_config.mkdir()
        source = root / "compose.yaml"
        source.write_text(document_text, encoding="utf-8", newline="\n")
        environment = {"PATH": str(Path(docker).parent) + os.pathsep + "/usr/bin" + os.pathsep + "/bin", "DOCKER_CONFIG": str(docker_config), "LANG": "C.UTF-8"}
        result = subprocess.run(
            [docker, "compose", "--project-directory", str(root), "--file", str(source), "config", "--format", "json"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=environment,
        )
    normalized = json.loads(result.stdout)
    if not isinstance(normalized.get("services"), dict) or set(normalized["services"]) != set(parsed["services"]):
        raise AssertionError("docker compose config changed the fixed service set")
    return {"raw": parsed, "normalized": normalized}


def build_release(parsed: dict[str, Any], normalized: dict[str, Any], source_text: str, compose_cli: str) -> dict[str, Any]:
    compose_services = normalized["services"]
    for service, spec in compose_services.items():
        if "build" in spec or "image" not in spec:
            raise ProbeRefusal(f"$.services.{service}: normalized target must use a fixed image and cannot build")
        for field in ("privileged", "devices", "network_mode"):
            if field in spec:
                raise ProbeRefusal(f"$.services.{service}.{field}: unsafe or unverified normalized field")
    ext = parsed["x-cloudhelm"]
    release = {
        "protocol": CONTRACT,
        "compose_cli": compose_cli,
        "source_digest": canonical_digest({"compose.yaml": source_text}),
        "services": compose_services,
        "networks": normalized.get("networks", {}),
        "volumes": normalized.get("volumes", {}),
        "parameter_contract": ext.get("parameters", {}),
        "secret_reference_contract": ext.get("secret_refs", {}),
    }
    release["release_digest"] = canonical_digest(release)
    release["release_id"] = "p0-release-" + release["release_digest"][-12:]
    return release


def make_plan(release: dict[str, Any], revision: dict[str, Any]) -> dict[str, Any]:
    required_revision = {"revision_id", "parameters", "secret_refs"}
    if set(revision) != required_revision:
        raise ProbeRefusal("EnvironmentConfigRevision: unknown or missing fields")
    contract = release["parameter_contract"]
    secret_contract = release["secret_reference_contract"]
    params = mapping(revision["parameters"], "EnvironmentConfigRevision.parameters")
    secrets = mapping(revision["secret_refs"], "EnvironmentConfigRevision.secret_refs")
    if set(params) != set(contract):
        missing = sorted(set(contract) - set(params))
        extra = sorted(set(params) - set(contract))
        raise ProbeRefusal(f"EnvironmentConfigRevision.parameters: missing={missing}; unauthorized={extra}")
    if set(secrets) != set(secret_contract):
        missing = sorted(set(secret_contract) - set(secrets))
        extra = sorted(set(secrets) - set(secret_contract))
        raise ProbeRefusal(f"EnvironmentConfigRevision.secret_refs: missing={missing}; unauthorized={extra}")
    for name, value in params.items():
        if not isinstance(value, str) or value not in contract[name]["allowed_values"]:
            raise ProbeRefusal(f"EnvironmentConfigRevision.parameters.{name}: value outside the declared contract")
    for name, ref in secrets.items():
        if not isinstance(ref, str) or not re.fullmatch(r"secret://synthetic/[A-Za-z0-9._/-]+@v[0-9]+", ref):
            raise ProbeRefusal(f"EnvironmentConfigRevision.secret_refs.{name}: only versioned synthetic references are accepted")
    revision_snapshot = {"revision_id": revision["revision_id"], "parameters": params, "secret_refs": secrets}
    revision_snapshot["revision_digest"] = canonical_digest(revision_snapshot)
    services = json.loads(json.dumps(release["services"]))
    for name, spec in contract.items():
        service = spec["service"]
        services[service]["environment"][name] = params[name]
    for name, spec in secret_contract.items():
        service = spec["service"]
        services[service]["environment"][name] = secrets[name]
    plan = {
        "protocol": CONTRACT,
        "release_id": release["release_id"],
        "release_digest": release["release_digest"],
        "environment_config_revision": revision_snapshot,
        "services": services,
        "networks": release["networks"],
        "volumes": release["volumes"],
    }
    validate_plan_against_release(plan, release)
    plan["plan_digest"] = canonical_digest(plan)
    return plan


def validate_plan_against_release(plan: dict[str, Any], release: dict[str, Any]) -> None:
    if plan.get("release_id") != release["release_id"] or plan.get("release_digest") != release["release_digest"]:
        raise ProbeRefusal("DeploymentPlan: Release identity mismatch")
    if set(plan.get("services", {})) != set(release["services"]):
        raise ProbeRefusal("DeploymentPlan.services: service topology changed")
    if plan.get("networks") != release["networks"]:
        raise ProbeRefusal("DeploymentPlan.networks: network topology changed")
    if plan.get("volumes") != release["volumes"]:
        raise ProbeRefusal("DeploymentPlan.volumes: managed volume topology changed")
    params = plan["environment_config_revision"]["parameters"]
    secrets = plan["environment_config_revision"]["secret_refs"]
    for service, original in release["services"].items():
        actual = plan["services"][service]
        if actual.get("image") != original.get("image"):
            raise ProbeRefusal(f"DeploymentPlan.services.{service}.image: image replacement requires a new Release")
        original_without_env = {k: v for k, v in original.items() if k != "environment"}
        actual_without_env = {k: v for k, v in actual.items() if k != "environment"}
        if actual_without_env != original_without_env:
            raise ProbeRefusal(f"DeploymentPlan.services.{service}: non-environment runtime contract changed")
        allowed_env = dict(original.get("environment", {}))
        for name, contract in release["parameter_contract"].items():
            if contract["service"] == service:
                allowed_env[name] = params[name]
        for name, contract in release["secret_reference_contract"].items():
            if contract["service"] == service:
                allowed_env[name] = secrets[name]
        if actual.get("environment", {}) != allowed_env:
            raise ProbeRefusal(f"DeploymentPlan.services.{service}.environment: unauthorized environment change")


def sample_source() -> str:
    doc = {
        "name": "cloudhelm-p0-compose-probe",
        "services": {
            "api": {
                "image": APP_IMAGE,
                "environment": {"APP_MODE": PARAM_MARKER, "API_TOKEN": SECRET_MARKER},
                "networks": ["internal"],
                "volumes": [{"type": "volume", "source": "runtime-state", "target": "/srv/state", "read_only": True}],
                "restart": "unless-stopped",
                "healthcheck": {"test": ["CMD", "true"], "interval": "5s", "timeout": "1s", "retries": 2},
            },
            "worker": {
                "image": WORKER_IMAGE,
                "environment": {"WORKER_KIND": "queue"},
                "networks": ["internal"],
            },
        },
        "networks": {"internal": {"internal": True}},
        "volumes": {"runtime-state": {}},
        "x-cloudhelm": {
            "contract": CONTRACT,
            "parameters": {
                "APP_MODE": {
                    "service": "api",
                    "target": "environment.APP_MODE",
                    "kind": "enum",
                    "allowed_values": ["staging", "production"],
                }
            },
            "secret_refs": {"API_TOKEN": {"service": "api", "target": "environment.API_TOKEN"}},
        },
    }
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)


def expect_refusal(label: str, action: Any, contains: str | None = None) -> str:
    try:
        action()
    except ProbeRefusal as exc:
        detail = str(exc)
        if contains and contains not in detail:
            raise AssertionError(f"{label}: refusal did not identify {contains!r}: {detail}") from exc
        return detail
    raise AssertionError(f"{label}: expected a refusal")


def run_refusal_cases(source: str) -> list[str]:
    base = yaml.safe_load(source)
    cases: list[tuple[str, str, str]] = [("duplicate-key", "services:\n  api: {}\n  api: {}\n", "duplicate YAML key")]
    cases.append(("interpolation", source.replace(APP_IMAGE, "${CLOUDHELM_IMAGE}"), "interpolation"))

    def changed(label: str, mutate: Any, reason: str) -> None:
        doc = copy.deepcopy(base)
        mutate(doc)
        cases.append((label, yaml.safe_dump(doc, sort_keys=False), reason))

    changed("include", lambda doc: doc.update({"include": ["./outside.yaml"]}), "include")
    changed("extends", lambda doc: doc["services"]["api"].update({"extends": {"service": "base"}}), "extends")
    changed("profiles", lambda doc: doc["services"]["api"].update({"profiles": ["prod"]}), "profiles")
    changed("env-file", lambda doc: doc["services"]["api"].update({"env_file": ["./outside.env"]}), "env_file")
    changed("build", lambda doc: doc["services"]["api"].update({"build": "."}), "build")
    changed("privileged", lambda doc: doc["services"]["api"].update({"privileged": True}), "privileged")
    changed("host-network", lambda doc: doc["services"]["api"].update({"network_mode": "host"}), "network_mode")
    changed("device", lambda doc: doc["services"]["api"].update({"devices": ["/dev/null:/dev/null"]}), "devices")
    changed("docker-socket", lambda doc: doc["services"]["worker"]["environment"].update({"DOCKER": "/var/run/docker.sock"}), "Docker socket")
    changed("docker-socket-mount", lambda doc: doc["services"]["worker"].update({"volumes": [{"type": "bind", "source": "/var/run/docker.sock", "target": "/var/run/docker.sock"}]}), "Docker socket")
    changed("bind-volume", lambda doc: doc["services"]["worker"].update({"volumes": [{"type": "bind", "source": "/tmp", "target": "/host"}]}), "bind mounts")
    changed("unknown-field", lambda doc: doc["services"]["api"].update({"container_name": "forbidden"}), "unknown or unsupported field")
    anchor = source.replace("    networks:\n    - internal\n    restart:", "    networks: &project_networks\n    - internal\n    restart:", 1)
    anchor = anchor.replace("    networks:\n    - internal\nnetworks:", "    networks: *project_networks\nnetworks:", 1)
    cases.append(("yaml-alias", anchor, "anchor/alias"))
    merge = source.replace("x-cloudhelm:\n  contract:", "x-cloudhelm:\n  <<: {unexpected: value}\n  contract:", 1)
    cases.append(("yaml-merge", merge, "merge inheritance"))
    outcomes = []
    for label, candidate, reason in cases:
        detail = expect_refusal(label, lambda candidate=candidate: parse_source(candidate), reason)
        outcomes.append(f"{label}@{detail.split(':', 1)[0]}")
    return outcomes


def main() -> int:
    started_at_utc = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    docker = shutil.which("docker")
    if docker is None:
        raise SystemExit("BLOCKED: docker CLI is unavailable; run this probe in the recorded WSL environment")
    version = compose_version(docker)
    source = sample_source()
    refusal_outcomes = run_refusal_cases(source)
    parsed = parse_source(source)
    result = compose_normalize(source, docker)
    release = build_release(parsed, result["normalized"], source, version)
    staging = make_plan(
        release,
        {"revision_id": "envcfg-p0-staging-r1", "parameters": {"APP_MODE": "staging"}, "secret_refs": {"API_TOKEN": SECRET_REF}},
    )
    production = make_plan(
        release,
        {"revision_id": "envcfg-p0-production-r1", "parameters": {"APP_MODE": "production"}, "secret_refs": {"API_TOKEN": SECRET_REF}},
    )
    expect_refusal("missing-parameter", lambda: make_plan(release, {"revision_id": "missing", "parameters": {}, "secret_refs": {"API_TOKEN": SECRET_REF}}), "missing")
    expect_refusal("out-of-contract-parameter", lambda: make_plan(release, {"revision_id": "bad", "parameters": {"APP_MODE": "debug"}, "secret_refs": {"API_TOKEN": SECRET_REF}}), "outside")
    expect_refusal("unauthorized-extra-parameter", lambda: make_plan(release, {"revision_id": "extra", "parameters": {"APP_MODE": "staging", "ROOT": "yes"}, "secret_refs": {"API_TOKEN": SECRET_REF}}), "unauthorized")
    expect_refusal("secret-value", lambda: make_plan(release, {"revision_id": "secret-value", "parameters": {"APP_MODE": "staging"}, "secret_refs": {"API_TOKEN": "super-secret"}}), "synthetic")
    tampered = json.loads(json.dumps(staging))
    tampered["services"]["api"]["image"] = WORKER_IMAGE
    expect_refusal("image-change", lambda: validate_plan_against_release(tampered, release), "image replacement")
    tampered = json.loads(json.dumps(staging))
    tampered["services"]["worker"]["environment"]["WORKER_KIND"] = "shell"
    expect_refusal("unauthorized-environment-change", lambda: validate_plan_against_release(tampered, release), "unauthorized")
    tampered = json.loads(json.dumps(staging))
    tampered["volumes"]["runtime-state"]["name"] = "unexpected-volume"
    expect_refusal("volume-topology-change", lambda: validate_plan_against_release(tampered, release), "volume topology")
    if staging["services"]["api"]["image"] != production["services"]["api"]["image"]:
        raise AssertionError("environment configuration changed the API image")
    if staging["services"]["worker"]["image"] != production["services"]["worker"]["image"]:
        raise AssertionError("environment configuration changed the worker image")
    if staging["networks"] != production["networks"]:
        raise AssertionError("environment configuration changed network topology")
    if staging["volumes"] != production["volumes"]:
        raise AssertionError("environment configuration changed managed-volume topology")
    if staging["services"]["api"]["environment"]["API_TOKEN"] != SECRET_REF:
        raise AssertionError("secret material was not kept as a synthetic versioned reference")
    summary = {
        "started_at_utc": started_at_utc,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "compose_version": version,
        "source_digest": release["source_digest"],
        "services": sorted(release["services"]),
        "release_digest": release["release_digest"],
        "environment_revisions": [staging["environment_config_revision"]["revision_digest"], production["environment_config_revision"]["revision_digest"]],
        "deployment_plan_digests": [staging["plan_digest"], production["plan_digest"]],
        "refusals": refusal_outcomes,
        "secret_material": "not supplied; synthetic reference only",
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
