"""Two-stage, bounded Compose parsing for the P1 delivery boundary.

The module accepts source text only. It never reads a caller-selected file,
dotenv value, process environment, Docker socket, or secret value. Stage one
creates an immutable Release specification; stage two binds only the declared
parameter slots and versioned secret references to that specification.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import PurePosixPath
from typing import Any

import rfc8785
import yaml
from yaml.nodes import MappingNode
from yaml.tokens import AliasToken, AnchorToken, TagToken

from packages.contracts.p1.compose_contracts import (
    COMPOSE_CONTRACT,
    PARSER_REVISION,
    ComposeDeploymentPlan,
    ComposeEnvironmentConfig,
    ComposeHealthcheck,
    ComposeNetwork,
    ComposeParameterSlot,
    ComposePort,
    ComposeReleaseSpec,
    ComposeSecretSlot,
    ComposeService,
    ComposeVolume,
    ComposeVolumeMount,
)


PARAMETER_MARKER = re.compile(r"^__CH_PARAMETER:([A-Z][A-Z0-9_]{0,63})__$")
SECRET_MARKER = re.compile(r"^__CH_SECRET_REF:([A-Z][A-Z0-9_]{0,63})__$")
SECRET_REF = re.compile(r"^secret://[A-Za-z0-9._/-]+@v[0-9]+$")
NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
DURATION = re.compile(r"^[1-9][0-9]*(?:ns|us|ms|s|m|h)$")
SECRET_NAME = re.compile(r"(?:PASSWORD|TOKEN|SECRET|PRIVATE_KEY|API_KEY|CREDENTIAL)")
INTERPOLATION = re.compile(r"\$(?:\$|\{|[A-Za-z_])")

ROOT_FIELDS = {"name", "services", "networks", "volumes", "x-cloudhelm"}
SERVICE_FIELDS = {"image", "environment", "networks", "volumes", "ports", "command", "restart", "healthcheck"}
EXTENSION_FIELDS = {"contract", "parameters", "secret_refs"}
DENIED_FIELDS = {
    "include", "extends", "profiles", "build", "privileged", "devices", "network_mode",
    "env_file", "volumes_from", "secrets", "configs", "external_links", "pid", "ipc",
    "cap_add", "cap_drop", "security_opt", "user", "working_dir", "logging", "deploy",
}


class ComposeParseError(ValueError):
    """Stable refusal without echoing input values or secret material."""

    def __init__(self, path: str, code: str):
        self.path, self.code = path, code
        super().__init__(f"{path}: {code}")


class _StrictLoader(yaml.SafeLoader):
    def construct_mapping(self, node: MappingNode, deep: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key_node, value_node in node.value:
            if key_node.tag == "tag:yaml.org,2002:merge":
                raise ComposeParseError("$", "yaml_merge_unsupported")
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str):
                raise ComposeParseError("$", "mapping_keys_must_be_strings")
            if key in result:
                raise ComposeParseError("$", "duplicate_yaml_key")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def _text_digest(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _fail(path: str, code: str) -> None:
    raise ComposeParseError(path, code)


def _mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        _fail(path, "object_required")
    return value


def _list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        _fail(path, "list_required")
    return value


def _string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value:
        _fail(path, "nonempty_string_required")
    if INTERPOLATION.search(value):
        _fail(path, "interpolation_unsupported")
    return value


def _reject_unknown(value: dict[str, Any], allowed: set[str], path: str) -> None:
    for key in value:
        if key in DENIED_FIELDS:
            _fail(f"{path}.{key}", "unsupported_compose_feature")
        if key not in allowed:
            _fail(f"{path}.{key}", "unknown_compose_field")


def _reject_interpolation(value: Any, path: str = "$") -> None:
    if isinstance(value, str) and INTERPOLATION.search(value):
        _fail(path, "interpolation_unsupported")
    if isinstance(value, dict):
        for key, child in value.items():
            _reject_interpolation(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_interpolation(child, f"{path}[{index}]")


def _reject_dangerous_values(value: Any, path: str) -> None:
    if isinstance(value, str):
        lowered = value.lower()
        if "docker.sock" in lowered or "/var/run/docker" in lowered:
            _fail(path, "docker_socket_unsupported")
    elif isinstance(value, dict):
        for key, child in value.items():
            _reject_dangerous_values(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_dangerous_values(child, f"{path}[{index}]")


def _parse_yaml(source_text: str) -> dict[str, Any]:
    if not isinstance(source_text, str) or not source_text.strip():
        _fail("$", "compose_source_required")
    try:
        for token in yaml.scan(source_text):
            if isinstance(token, (AnchorToken, AliasToken)):
                _fail("$", "yaml_anchor_alias_unsupported")
            if isinstance(token, TagToken):
                _fail("$", "yaml_tag_unsupported")
        document = yaml.load(source_text, Loader=_StrictLoader)
    except ComposeParseError:
        raise
    except yaml.YAMLError:
        _fail("$", "invalid_yaml")
    if not isinstance(document, dict):
        _fail("$", "compose_document_mapping_required")
    _reject_interpolation(document)
    return document


def _validate_networks(raw: Any) -> dict[str, ComposeNetwork]:
    networks = _mapping({} if raw is None else raw, "$.networks")
    if len(networks) > 32:
        _fail("$.networks", "too_many_networks")
    result = {}
    for name, value in networks.items():
        if not NAME.fullmatch(name):
            _fail(f"$.networks.{name}", "invalid_network_name")
        spec = _mapping({} if value is None else value, f"$.networks.{name}")
        _reject_unknown(spec, {"driver", "internal"}, f"$.networks.{name}")
        if spec.get("driver", "bridge") != "bridge" or spec.get("internal") is not True:
            _fail(f"$.networks.{name}", "only_internal_bridge_networks_supported")
        result[name] = ComposeNetwork()
    return result


def _validate_volumes(raw: Any) -> dict[str, ComposeVolume]:
    volumes = _mapping({} if raw is None else raw, "$.volumes")
    if len(volumes) > 32:
        _fail("$.volumes", "too_many_volumes")
    result = {}
    for name, value in volumes.items():
        if not NAME.fullmatch(name):
            _fail(f"$.volumes.{name}", "invalid_volume_name")
        spec = _mapping({} if value is None else value, f"$.volumes.{name}")
        _reject_unknown(spec, {"driver"}, f"$.volumes.{name}")
        if spec.get("driver", "local") != "local":
            _fail(f"$.volumes.{name}", "only_managed_local_volumes_supported")
        result[name] = ComposeVolume()
    return result


def _validate_mount(raw: Any, path: str, volumes: dict[str, ComposeVolume]) -> ComposeVolumeMount:
    mount = _mapping(raw, path)
    _reject_unknown(mount, {"type", "source", "target", "read_only"}, path)
    if mount.get("type") != "volume":
        _fail(f"{path}.type", "bind_mount_or_device_unsupported")
    source = _string(mount.get("source"), f"{path}.source")
    if source not in volumes or "/" in source or "\\" in source:
        _fail(f"{path}.source", "external_volume_unsupported")
    target = _string(mount.get("target"), f"{path}.target")
    target_path = PurePosixPath(target)
    if (not re.fullmatch(r"/[A-Za-z0-9][A-Za-z0-9._/-]*", target)
            or target in {"/", "/var/run/docker.sock"} or ".." in target_path.parts):
        _fail(f"{path}.target", "unsafe_container_path")
    if "docker.sock" in target.lower() or "/var/run/docker" in target.lower():
        _fail(path, "docker_socket_unsupported")
    read_only = mount.get("read_only", False)
    if type(read_only) is not bool:
        _fail(f"{path}.read_only", "boolean_required")
    return ComposeVolumeMount(source=source, target=target, read_only=read_only)


def _parse_port(raw: Any, path: str) -> ComposePort:
    if isinstance(raw, str):
        parts = raw.split(":")
        if len(parts) != 3 or parts[0] != "127.0.0.1":
            _fail(path, "loopback_port_required")
        host_ip, published, target = parts
        try:
            published_int, target_int = int(published), int(target)
        except ValueError:
            _fail(path, "port_number_required")
        return ComposePort(host_ip=host_ip, published=published_int, target=target_int)
    spec = _mapping(raw, path)
    _reject_unknown(spec, {"host_ip", "published", "target", "protocol"}, path)
    if spec.get("host_ip") != "127.0.0.1":
        _fail(f"{path}.host_ip", "loopback_port_required")
    if spec.get("protocol", "tcp") != "tcp":
        _fail(f"{path}.protocol", "only_tcp_ports_supported")
    try:
        return ComposePort(
            host_ip="127.0.0.1", published=spec.get("published"), target=spec.get("target"),
        )
    except ValueError:
        _fail(path, "port_bounds_invalid")


def _validate_healthcheck(raw: Any, path: str) -> ComposeHealthcheck:
    health = _mapping(raw, path)
    _reject_unknown(health, {"test", "interval", "timeout", "retries", "start_period", "disable"}, path)
    test = tuple(_string(item, f"{path}.test[{index}]") for index, item in enumerate(_list(health.get("test"), f"{path}.test")))
    values: dict[str, Any] = {"test": test}
    for key in ("interval", "timeout", "start_period"):
        value = health.get(key)
        if value is not None and (not isinstance(value, str) or not DURATION.fullmatch(value)):
            _fail(f"{path}.{key}", "duration_required")
        values[key] = value
    retries = health.get("retries")
    if retries is not None and (type(retries) is not int or not 0 <= retries <= 100):
        _fail(f"{path}.retries", "bounded_integer_required")
    values["retries"] = retries
    disable = health.get("disable", False)
    if type(disable) is not bool:
        _fail(f"{path}.disable", "boolean_required")
    values["disable"] = disable
    return ComposeHealthcheck(**values)


def _validate_slots(document: dict[str, Any], services: dict[str, ComposeService]) -> tuple[dict[str, ComposeParameterSlot], dict[str, ComposeSecretSlot]]:
    raw = document.get("x-cloudhelm")
    if raw is None:
        _check_marker_bindings(services, {}, {})
        return {}, {}
    extension = _mapping(raw, "$.x-cloudhelm")
    _reject_unknown(extension, EXTENSION_FIELDS, "$.x-cloudhelm")
    if extension.get("contract") != COMPOSE_CONTRACT:
        _fail("$.x-cloudhelm.contract", "compose_contract_revision_required")
    parameters = _mapping(extension.get("parameters", {}), "$.x-cloudhelm.parameters")
    secrets = _mapping(extension.get("secret_refs", {}), "$.x-cloudhelm.secret_refs")
    if set(parameters) & set(secrets):
        _fail("$.x-cloudhelm", "parameter_secret_name_collision")
    parameter_slots: dict[str, ComposeParameterSlot] = {}
    secret_slots: dict[str, ComposeSecretSlot] = {}
    for name, raw_slot in parameters.items():
        if not ENV_NAME.fullmatch(name):
            _fail(f"$.x-cloudhelm.parameters.{name}", "invalid_slot_name")
        slot = _mapping(raw_slot, f"$.x-cloudhelm.parameters.{name}")
        if set(slot) != {"service", "target", "kind", "allowed_values"}:
            _fail(f"$.x-cloudhelm.parameters.{name}", "incomplete_parameter_contract")
        service = _string(slot.get("service"), f"$.x-cloudhelm.parameters.{name}.service")
        if service not in services or slot.get("target") != f"environment.{name}" or slot.get("kind") != "enum":
            _fail(f"$.x-cloudhelm.parameters.{name}", "parameter_slot_binding_invalid")
        allowed = tuple(_string(value, f"$.x-cloudhelm.parameters.{name}.allowed_values") for value in _list(slot.get("allowed_values"), f"$.x-cloudhelm.parameters.{name}.allowed_values"))
        parameter_slots[name] = ComposeParameterSlot(service=service, target=f"environment.{name}", allowed_values=allowed)
    for name, raw_slot in secrets.items():
        if not ENV_NAME.fullmatch(name):
            _fail(f"$.x-cloudhelm.secret_refs.{name}", "invalid_slot_name")
        slot = _mapping(raw_slot, f"$.x-cloudhelm.secret_refs.{name}")
        if set(slot) != {"service", "target"}:
            _fail(f"$.x-cloudhelm.secret_refs.{name}", "incomplete_secret_contract")
        service = _string(slot.get("service"), f"$.x-cloudhelm.secret_refs.{name}.service")
        if service not in services or slot.get("target") != f"environment.{name}":
            _fail(f"$.x-cloudhelm.secret_refs.{name}", "secret_slot_binding_invalid")
        secret_slots[name] = ComposeSecretSlot(service=service, target=f"environment.{name}")
    _check_marker_bindings(services, parameter_slots, secret_slots)
    return parameter_slots, secret_slots


def _check_marker_bindings(services: dict[str, ComposeService], parameters: dict[str, ComposeParameterSlot], secrets: dict[str, ComposeSecretSlot]) -> None:
    declared = set(parameters) | set(secrets)
    for service, spec in services.items():
        for name, value in spec.environment.items():
            parameter = PARAMETER_MARKER.fullmatch(value)
            secret = SECRET_MARKER.fullmatch(value)
            if parameter and (parameter.group(1) not in parameters or parameters[parameter.group(1)].service != service):
                _fail(f"$.services.{service}.environment.{name}", "undeclared_parameter_marker")
            if secret and (secret.group(1) not in secrets or secrets[secret.group(1)].service != service):
                _fail(f"$.services.{service}.environment.{name}", "undeclared_secret_marker")
            if (value.startswith("__CH_PARAMETER:") or value.startswith("__CH_SECRET_REF:")) and value not in {
                f"__CH_PARAMETER:{item}__" for item in declared
            } | {f"__CH_SECRET_REF:{item}__" for item in declared}:
                _fail(f"$.services.{service}.environment.{name}", "malformed_slot_marker")
            if SECRET_NAME.search(name) and not secret:
                _fail(f"$.services.{service}.environment.{name}", "secret_value_must_be_reference")
    for name, slot in parameters.items():
        marker = f"__CH_PARAMETER:{name}__"
        if services[slot.service].environment.get(name) != marker:
            _fail(f"$.services.{slot.service}.environment.{name}", "parameter_marker_required")
    for name, slot in secrets.items():
        marker = f"__CH_SECRET_REF:{name}__"
        if services[slot.service].environment.get(name) != marker:
            _fail(f"$.services.{slot.service}.environment.{name}", "secret_marker_required")


def _validate_services(raw: Any, networks: dict[str, ComposeNetwork], volumes: dict[str, ComposeVolume]) -> dict[str, ComposeService]:
    services = _mapping(raw, "$.services")
    if not services or len(services) > 16:
        _fail("$.services", "service_count_out_of_bounds")
    result: dict[str, ComposeService] = {}
    for name, raw_spec in services.items():
        if not NAME.fullmatch(name):
            _fail(f"$.services.{name}", "invalid_service_name")
        spec = _mapping(raw_spec, f"$.services.{name}")
        _reject_unknown(spec, SERVICE_FIELDS, f"$.services.{name}")
        _reject_dangerous_values(spec, f"$.services.{name}")
        image = _string(spec.get("image"), f"$.services.{name}.image")
        if "@sha256:" not in image or not re.fullmatch(r".+@sha256:[0-9a-f]{64}", image):
            _fail(f"$.services.{name}.image", "digest_pinned_image_required")
        environment_raw = _mapping(spec.get("environment", {}), f"$.services.{name}.environment")
        if len(environment_raw) > 128:
            _fail(f"$.services.{name}.environment", "environment_count_out_of_bounds")
        environment = {}
        for env_name, value in environment_raw.items():
            if not ENV_NAME.fullmatch(env_name):
                _fail(f"$.services.{name}.environment", "invalid_environment_name")
            environment[env_name] = _string(value, f"$.services.{name}.environment.{env_name}")
        network_raw = spec.get("networks", [])
        if isinstance(network_raw, list):
            network_names = tuple(network_raw)
        else:
            network_mapping = _mapping(network_raw, f"$.services.{name}.networks")
            if any(value not in (None, {}) for value in network_mapping.values()):
                _fail(f"$.services.{name}.networks", "network_options_unsupported")
            network_names = tuple(network_mapping)
        if len(set(network_names)) != len(network_names):
            _fail(f"$.services.{name}.networks", "duplicate_network_reference")
        if any(not isinstance(item, str) or item not in networks for item in network_names):
            _fail(f"$.services.{name}.networks", "undeclared_network_reference")
        mount_raw = _list(spec.get("volumes", []), f"$.services.{name}.volumes")
        mounts = tuple(_validate_mount(item, f"$.services.{name}.volumes[{index}]", volumes) for index, item in enumerate(mount_raw))
        if len({mount.target for mount in mounts}) != len(mounts):
            _fail(f"$.services.{name}.volumes", "duplicate_mount_target")
        ports_raw = _list(spec.get("ports", []), f"$.services.{name}.ports")
        ports = tuple(_parse_port(item, f"$.services.{name}.ports[{index}]") for index, item in enumerate(ports_raw))
        if len({(port.published, port.target) for port in ports}) != len(ports):
            _fail(f"$.services.{name}.ports", "duplicate_port")
        command = spec.get("command")
        if command is not None:
            command_items = _list(command, f"$.services.{name}.command")
            if not 0 < len(command_items) <= 64:
                _fail(f"$.services.{name}.command", "command_count_out_of_bounds")
            command = tuple(_string(item, f"$.services.{name}.command[{index}]") for index, item in enumerate(command_items))
        restart = spec.get("restart", "no")
        if restart not in {"no", "always", "on-failure", "unless-stopped"}:
            _fail(f"$.services.{name}.restart", "unsupported_restart_policy")
        healthcheck = _validate_healthcheck(spec["healthcheck"], f"$.services.{name}.healthcheck") if "healthcheck" in spec else None
        result[name] = ComposeService(
            image=image, environment=environment, networks=network_names, volumes=mounts,
            ports=ports, command=command, restart=restart, healthcheck=healthcheck,
        )
    return result


def parse_release_source(source_text: str) -> ComposeReleaseSpec:
    """Stage one: parse a fixed, digest-pinned Compose source into a Release."""
    document = _parse_yaml(source_text)
    _reject_unknown(document, ROOT_FIELDS, "$")
    project_name = _string(document.get("name"), "$.name")
    if not NAME.fullmatch(project_name):
        _fail("$.name", "invalid_project_name")
    networks = _validate_networks(document.get("networks", {}))
    volumes = _validate_volumes(document.get("volumes", {}))
    services = _validate_services(document.get("services"), networks, volumes)
    parameters, secrets = _validate_slots(services=services, document=document)
    payload = {
        "contract": COMPOSE_CONTRACT, "parser_revision": PARSER_REVISION, "project_name": project_name,
        "source_digest": _text_digest(source_text), "services": {key: value.model_dump(mode="json") for key, value in services.items()},
        "networks": {key: value.model_dump(mode="json") for key, value in networks.items()},
        "volumes": {key: value.model_dump(mode="json") for key, value in volumes.items()},
        "parameter_contract": {key: value.model_dump(mode="json") for key, value in parameters.items()},
        "secret_reference_contract": {key: value.model_dump(mode="json") for key, value in secrets.items()},
    }
    release_digest = _digest(payload)
    return ComposeReleaseSpec(
        release_id=f"release-{release_digest[-24:]}", release_digest=release_digest,
        project_name=project_name, source_digest=payload["source_digest"], services=services,
        networks=networks, volumes=volumes, parameter_contract=parameters,
        secret_reference_contract=secrets,
    )


def _config_digest(config: ComposeEnvironmentConfig) -> str:
    return _digest(config.model_dump(mode="json"))


def _render_services(release: ComposeReleaseSpec, config: ComposeEnvironmentConfig) -> dict[str, ComposeService]:
    rendered = {name: service.model_copy(deep=True) for name, service in release.services.items()}
    for name, slot in release.parameter_contract.items():
        value = config.parameters[name]
        service = rendered[slot.service]
        environment = dict(service.environment)
        environment[name] = value
        rendered[slot.service] = service.model_copy(update={"environment": environment})
    for name, slot in release.secret_reference_contract.items():
        service = rendered[slot.service]
        environment = dict(service.environment)
        environment[name] = config.secret_refs[name]
        rendered[slot.service] = service.model_copy(update={"environment": environment})
    return rendered


def _plan_payload(plan: ComposeDeploymentPlan) -> dict[str, Any]:
    return {
        "contract": plan.contract, "parser_revision": plan.parser_revision,
        "release_id": plan.release_id, "release_digest": plan.release_digest,
        "config_revision_id": plan.config_revision_id, "config_digest": plan.config_digest,
        "services": {key: value.model_dump(mode="json") for key, value in plan.services.items()},
        "networks": {key: value.model_dump(mode="json") for key, value in plan.networks.items()},
        "volumes": {key: value.model_dump(mode="json") for key, value in plan.volumes.items()},
    }


def bind_environment_config(release: ComposeReleaseSpec | dict[str, Any], config: ComposeEnvironmentConfig | dict[str, Any]) -> ComposeDeploymentPlan:
    """Stage two: bind only declared values and versioned secret references."""
    if isinstance(config, dict):
        for field in ("parameters", "secret_refs"):
            values = config.get(field, {})
            if not isinstance(values, dict) or any(type(value) is not str for value in values.values()):
                _fail(f"$.{field}", "string_values_required")
    try:
        release_model = release if isinstance(release, ComposeReleaseSpec) else ComposeReleaseSpec.model_validate(release)
        config_model = config if isinstance(config, ComposeEnvironmentConfig) else ComposeEnvironmentConfig.model_validate(config)
    except ValueError:
        _fail("$", "compose_contract_invalid")
    parameters = set(release_model.parameter_contract)
    secrets = set(release_model.secret_reference_contract)
    if set(config_model.parameters) != parameters:
        _fail("$.parameters", "parameter_set_mismatch")
    if set(config_model.secret_refs) != secrets:
        _fail("$.secret_refs", "secret_reference_set_mismatch")
    for name, value in config_model.parameters.items():
        if value not in release_model.parameter_contract[name].allowed_values:
            _fail(f"$.parameters.{name}", "parameter_value_outside_contract")
    for name, value in config_model.secret_refs.items():
        if not SECRET_REF.fullmatch(value):
            _fail(f"$.secret_refs.{name}", "versioned_secret_reference_required")
    rendered = _render_services(release_model, config_model)
    config_digest = _config_digest(config_model)
    base = {
        "contract": COMPOSE_CONTRACT, "parser_revision": PARSER_REVISION,
        "release_id": release_model.release_id, "release_digest": release_model.release_digest,
        "config_revision_id": config_model.config_revision_id, "config_digest": config_digest,
        "services": {key: value.model_dump(mode="json") for key, value in rendered.items()},
        "networks": {key: value.model_dump(mode="json") for key, value in release_model.networks.items()},
        "volumes": {key: value.model_dump(mode="json") for key, value in release_model.volumes.items()},
    }
    plan_digest = _digest(base)
    plan = ComposeDeploymentPlan(
        plan_id=f"plan-{plan_digest[-24:]}", plan_digest=plan_digest, **base,
    )
    validate_deployment_plan(plan, release_model)
    return plan


def validate_deployment_plan(plan: ComposeDeploymentPlan | dict[str, Any], release: ComposeReleaseSpec | dict[str, Any]) -> None:
    """Ensure a stage-two plan changed only declared environment slots."""
    try:
        plan_model = plan if isinstance(plan, ComposeDeploymentPlan) else ComposeDeploymentPlan.model_validate(plan)
        release_model = release if isinstance(release, ComposeReleaseSpec) else ComposeReleaseSpec.model_validate(release)
    except ValueError:
        _fail("$", "compose_contract_invalid")
    if plan_model.release_id != release_model.release_id or plan_model.release_digest != release_model.release_digest:
        _fail("$.release", "release_identity_mismatch")
    expected_digest = _digest(_plan_payload(plan_model))
    if plan_model.plan_digest != expected_digest or plan_model.plan_id != f"plan-{expected_digest[-24:]}":
        _fail("$.plan_digest", "plan_digest_mismatch")
    if plan_model.networks != release_model.networks or plan_model.volumes != release_model.volumes:
        _fail("$", "topology_changed")
    if set(plan_model.services) != set(release_model.services):
        _fail("$.services", "service_topology_changed")
    allowed = set(release_model.parameter_contract) | set(release_model.secret_reference_contract)
    for service_name, original in release_model.services.items():
        actual = plan_model.services.get(service_name)
        if actual is None:
            _fail(f"$.services.{service_name}", "service_removed")
        original_payload = original.model_dump(mode="json")
        actual_payload = actual.model_dump(mode="json")
        original_environment = dict(original_payload.pop("environment"))
        actual_environment = dict(actual_payload.pop("environment"))
        if actual_payload != original_payload:
            _fail(f"$.services.{service_name}", "runtime_contract_changed")
        expected_environment = dict(original_environment)
        for name in allowed:
            slot = release_model.parameter_contract.get(name) or release_model.secret_reference_contract.get(name)
            if slot and slot.service == service_name:
                value = actual_environment.get(name)
                if name in release_model.parameter_contract and value not in release_model.parameter_contract[name].allowed_values:
                    _fail(f"$.services.{service_name}.environment.{name}", "parameter_value_outside_contract")
                if name in release_model.secret_reference_contract and (value is None or not SECRET_REF.fullmatch(value)):
                    _fail(f"$.services.{service_name}.environment.{name}", "versioned_secret_reference_required")
                expected_environment[name] = value
        if set(actual_environment) != set(expected_environment) or any(
            actual_environment[name] != expected_environment[name] for name in expected_environment
        ):
            _fail(f"$.services.{service_name}.environment", "environment_change_outside_contract")


# Friendly aliases for callers that use the domain wording.
parse_compose_source = parse_release_source
compile_deployment_plan = bind_environment_config
