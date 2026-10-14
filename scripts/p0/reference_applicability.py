"""Inspect the frozen reference and the unchanged parser; never compile or deploy it."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import platform
import re
import subprocess
import sys
import tomllib
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from importlib.metadata import version
from pathlib import Path

import yaml

from packages.contracts.p0.delivery_contracts import (
    DeploymentPlanBinding, EnvironmentConfigRevision, ReleaseManifest,
)
from packages.contracts.p0.permit_contracts import PermitBinding, PlanStep
from packages.contracts.p0.resource_contracts import AllocationIdentity, ResourceVector
from scripts.p0 import compose_probe


ROOT = Path(__file__).resolve().parents[2]
METHOD = "p0-reference-applicability-r1"
INPUT_SET = "docs/acceptance/reference/input-set-r1.json"
INPUT_SET_SHA256 = "119053f06e8adb7f56a19b1c7622e5f9249f40697029a6a3c673f7ebc88e43d0"
SOURCE_COMMIT = "6dd8b605a5cc4b7b641cc0f9b4f2633614c6e757"
COMPOSE = "examples/standalone-project/compose.yaml"
PARSER = "scripts/p0/compose_probe.py"
PARSER_SHA256 = "e3e64ab0b0ded0defc823103286191d415ee09b3d97f8c05a5f26ae744c101b5"
HISTORY_COMMIT = "3293a09c2501ee5bace398c6214dfcb7016c0824"
HISTORY_PATH = "examples/sample-repo-python"
HISTORY_TREE = "b765b5f8ee988cd1d95f8a45dd6960597d047573"
EXPECTED_REFUSAL = "$.services.postgres.mem_limit: unknown or unsupported field"

# Rules describe the P1 boundary, not fields accepted by today's parser.
RULES = {
    "name": ("controlled_compile", "installation_namespace"),
    "services": ("reuse", "fixed_service_keys"),
    "services.*": ("reuse", "fixed_service_keys"),
    "services.*.image": ("controlled_compile", "build_artifact_identity"),
    "services.*.build": ("controlled_compile", "restricted_build_only"),
    "services.*.build.context": ("controlled_compile", "restricted_build_only"),
    "services.*.build.args": ("controlled_compile", "fixed_build_variant"),
    "services.*.build.args.PYTHON_BASE_IMAGE": ("controlled_compile", "fixed_build_variant"),
    "services.*.build.args.NODE_IMAGE": ("controlled_compile", "fixed_build_variant"),
    "services.*.build.args.NGINX_IMAGE": ("controlled_compile", "fixed_build_variant"),
    "services.*.environment": ("controlled_compile", "explicit_configuration_schema"),
    "services.*.environment.POSTGRES_DB": ("controlled_compile", "explicit_configuration_schema"),
    "services.*.environment.POSTGRES_USER": ("controlled_compile", "authenticated_database_roles"),
    "services.*.environment.POSTGRES_HOST_AUTH_METHOD": ("reject", "development_trust_authentication"),
    "services.*.environment.DATABASE_URL": ("controlled_compile", "versioned_secret_reference"),
    "services.*.volumes": ("controlled_compile", "managed_long_syntax_volume"),
    "services.*.healthcheck": ("reuse", "fixed_health_contract"),
    "services.*.healthcheck.test": ("reuse", "fixed_health_contract"),
    "services.*.healthcheck.interval": ("reuse", "fixed_health_contract"),
    "services.*.healthcheck.timeout": ("reuse", "fixed_health_contract"),
    "services.*.healthcheck.retries": ("reuse", "fixed_health_contract"),
    "services.*.mem_limit": ("controlled_compile", "group_memory_accounting"),
    "services.*.cpus": ("controlled_compile", "group_cpu_accounting"),
    "services.*.dns_opt": ("controlled_compile", "bounded_dns_behavior"),
    "services.*.depends_on": ("controlled_compile", "finite_step_dependencies"),
    "services.*.depends_on.postgres": ("controlled_compile", "finite_step_dependencies"),
    "services.*.depends_on.postgres.condition": ("controlled_compile", "finite_step_dependencies"),
    "services.*.depends_on.backend": ("controlled_compile", "finite_step_dependencies"),
    "services.*.depends_on.backend.condition": ("controlled_compile", "finite_step_dependencies"),
    "services.*.read_only": ("controlled_compile", "preserve_read_only_root"),
    "services.*.tmpfs": ("controlled_compile", "require_bounded_tmpfs"),
    "services.*.ports": ("controlled_compile", "loopback_port_reservation"),
    "volumes": ("controlled_compile", "managed_volume_identity_and_quota"),
    "volumes.reference_db": ("controlled_compile", "managed_volume_identity_and_quota"),
}


class CheckFailure(ValueError):
    """A safe reason code, never source configuration or subprocess output."""


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise CheckFailure(reason)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def git_bytes(repository: Path, *arguments: str) -> bytes:
    result = subprocess.run(
        ["/usr/bin/git", "-C", str(repository), *arguments],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30, check=False,
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "GIT_OPTIONAL_LOCKS": "0",
             "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"},
    )
    require(result.returncode == 0, "REQUIRED_LOCAL_GIT_OBJECT_UNAVAILABLE")
    return result.stdout


def verify_reference() -> tuple[dict, bytes]:
    manifest_bytes = (ROOT / INPUT_SET).read_bytes()
    require(sha256(manifest_bytes) == INPUT_SET_SHA256, "REFERENCE_INPUT_SET_CHANGED")
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    require(manifest["source_commit"] == SOURCE_COMMIT, "REFERENCE_SOURCE_COMMIT_CHANGED")
    paths = [entry["path"] for entry in manifest["files"]]
    require(len(paths) == len(set(paths)) == 36 and COMPOSE in paths, "REFERENCE_FILE_SET_CHANGED")
    for entry in manifest["files"]:
        path = ROOT / entry["path"]
        require(path.resolve().is_relative_to(ROOT), "REFERENCE_PATH_OUTSIDE_REPOSITORY")
        current = path.read_bytes()
        historical = git_bytes(ROOT, "cat-file", "blob", f"{SOURCE_COMMIT}:{entry['path']}")
        require(sha256(current) == entry["sha256"], "REFERENCE_WORKTREE_BYTES_CHANGED")
        require(sha256(historical) == entry["sha256"], "REFERENCE_SOURCE_BLOB_MISMATCH")
        current.decode("utf-8")
    return {
        "input_set_revision": manifest["revision"], "input_set_sha256": INPUT_SET_SHA256,
        "source_commit": SOURCE_COMMIT, "verified_file_count": len(paths),
        "current_and_historical_bytes_match": True,
    }, (ROOT / COMPOSE).read_bytes()


def verify_history(repository: Path) -> dict:
    kind = git_bytes(repository, "cat-file", "-t", HISTORY_COMMIT).decode("utf-8").strip()
    require(kind == "commit", "HISTORICAL_SOURCE_IS_NOT_A_COMMIT")
    tree = git_bytes(repository, "rev-parse", f"{HISTORY_COMMIT}:{HISTORY_PATH}").decode().strip()
    require(tree == HISTORY_TREE, "HISTORICAL_SUBTREE_MISMATCH")
    listing = git_bytes(repository, "ls-tree", "-r", "--name-only", tree).decode("utf-8").splitlines()
    entrypoint = git_bytes(repository, "cat-file", "blob", f"{tree}:src/sample_service/main.py")
    parsed = ast.parse(entrypoint.decode("utf-8"))
    routes = sorted(node.args[0].value for node in ast.walk(parsed)
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "get" and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "application" and node.args
                    and isinstance(node.args[0], ast.Constant))
    project = tomllib.loads(git_bytes(repository, "cat-file", "blob", f"{tree}:pyproject.toml").decode("utf-8"))
    dependencies = sorted(re.split(r"[\[<=>]", item)[0] for item in project["project"]["dependencies"])
    require(routes == ["/health", "/metrics"], "HISTORICAL_ROUTE_BOUNDARY_CHANGED")
    require(dependencies == ["fastapi", "prometheus-client", "uvicorn"], "HISTORICAL_STACK_CHANGED")
    require(len(listing) == 14 and not any(
        path.endswith("package.json") or "migration" in path for path in listing
    ), "HISTORICAL_FILE_BOUNDARY_CHANGED")
    return {"commit": HISTORY_COMMIT, "subtree": tree, "verified_file_count": len(listing),
            "entrypoint_sha256": sha256(entrypoint), "get_routes": routes,
            "runtime_dependencies": dependencies, "scope": "health_and_metrics_only"}


def field_inventory(document: dict, prefix: tuple[str, ...] = ()) -> list[dict]:
    fields = []
    for key, value in document.items():
        parts = (*prefix, key)
        normalized = (parts[0], "*", *parts[2:]) if len(parts) >= 2 and parts[0] == "services" else parts
        rule = RULES.get(".".join(normalized))
        require(rule is not None, "UNCLASSIFIED_REFERENCE_FIELD")
        if parts == ("services", "postgres", "image"):
            rule = ("reuse", "fixed_database_image_identity")
        category, boundary = rule
        fields.append({"path": "$." + ".".join(parts), "category": category, "boundary": boundary})
        if isinstance(value, dict):
            fields.extend(field_inventory(value, parts))
    return fields


def reference_facts(document: dict) -> dict:
    services = document["services"]
    require(set(services) == {"postgres", "backend", "frontend"}, "REFERENCE_SERVICES_CHANGED")
    require("networks" not in document and not any(k.startswith("x-") for k in document),
            "REFERENCE_ABSENCE_BOUNDARY_CHANGED")
    require(services["backend"]["build"]["context"] == "./backend"
            and services["frontend"]["build"]["context"] == "./frontend", "BUILD_CONTEXT_CHANGED")
    require(services["backend"]["read_only"] is True and services["backend"]["tmpfs"] == ["/tmp"],
            "READ_ONLY_TMPFS_BOUNDARY_CHANGED")
    require(services["frontend"]["ports"] == ["127.0.0.1:58080:80"], "LOOPBACK_BINDING_CHANGED")
    require(services["postgres"]["environment"]["POSTGRES_HOST_AUTH_METHOD"] == "trust",
            "DEVELOPMENT_AUTHENTICATION_CHANGED")
    amounts = {}
    for name, service in services.items():
        require(re.fullmatch(r"[0-9]+m", service["mem_limit"]) is not None, "MEMORY_UNIT_CHANGED")
        cpu = Decimal(str(service["cpus"])) * 1000
        require(cpu == int(cpu), "NONINTEGRAL_CPU_MILLICORES")
        amounts[name] = {"memory_mib": int(service["mem_limit"][:-1]), "cpu_millicores": int(cpu)}
    return {"top_level_fields": list(document),
            "service_fields": {name: list(service) for name, service in services.items()},
            "extension_fields": [], "explicit_networks": False,
            "declared_service_limits": amounts,
            "declared_service_limit_sum": {k: sum(v[k] for v in amounts.values())
                                           for k in ("memory_mib", "cpu_millicores")},
            "complete_resource_request": False,
            "missing_bindings": ["group_hard_limits", "pids", "disk_peak_and_retention",
                                 "slot_allocation", "host_pool_identity", "port_and_volume_ownership",
                                 "explicit_internal_network", "descriptor_and_configuration_schema",
                                 "authenticated_database_and_secret_versions", "bounded_tmpfs_size"]}


def inspect_reference(history_repository: Path) -> dict:
    require(sys.platform == "linux" and "microsoft" in platform.release().lower(), "WSL_LINUX_REQUIRED")
    fixed, source_bytes = verify_reference()
    history = verify_history(history_repository)
    require(sha256((ROOT / PARSER).read_bytes()) == PARSER_SHA256, "LEGACY_PARSER_CHANGED")
    try:
        compose_probe.parse_source(source_bytes.decode("utf-8"))
    except compose_probe.ProbeRefusal as exc:
        refusal = str(exc)
        require(refusal == EXPECTED_REFUSAL, "LEGACY_REJECTION_CHANGED")
    else:
        raise CheckFailure("ORIGINAL_REFERENCE_WAS_NOT_REJECTED")
    # Inventory the same bytes only after observing rejection; no fields are stripped.
    document = yaml.load(source_bytes.decode("utf-8"), Loader=compose_probe.StrictLoader)
    fields = field_inventory(document)
    models = (ReleaseManifest, EnvironmentConfigRevision, DeploymentPlanBinding,
              PlanStep, PermitBinding, AllocationIdentity, ResourceVector)
    return {
        "reference": {**fixed, "compose_sha256": sha256(source_bytes)}, "historical_source": history,
        "legacy_parser": {"path": PARSER, "sha256": PARSER_SHA256, "entrypoint": "parse_source",
                          "input": "unmodified_frozen_reference_bytes", "accepted": False,
                          "observed_refusal": refusal, "compose_cli_executed": False},
        "fields": fields, "field_count": len(fields),
        "classification_counts": dict(sorted(Counter(f["category"] for f in fields).items())),
        "facts": reference_facts(document),
        "contract_field_shapes": {model.__name__: list(model.model_fields) for model in models},
        "contract_instances_created": False, "compiled_runtime_spec_created": False,
        "product_deployment_supported": False,
        "runtime_gate": "closed_until_P1_implementation_and_current_environment_evidence",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--historical-repository", required=True, type=Path)
    args = parser.parse_args()
    report = {"method": METHOD, "started_at_utc": utc_now(),
              "method_sha256": sha256(Path(__file__).read_bytes()),
              "environment": {"system": platform.system(), "kernel": platform.release(),
                              "python": platform.python_version(),
                              "packages": {name: version(name) for name in ("pydantic", "PyYAML", "rfc8785")}}}
    try:
        report.update(inspect_reference(args.historical_repository))
        report["result"] = "passed"
        code = 0
    except Exception as exc:
        report["result"] = "failed"
        report["reason"] = str(exc) if isinstance(exc, CheckFailure) else type(exc).__name__
        code = 1
    report["finished_at_utc"] = utc_now()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
