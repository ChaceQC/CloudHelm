"""Check the original build journal and verified OCI output without executing work."""

import json

from modules.workspaces.safe_paths import PrivateRoot, exists_at, read_regular
from packages.contracts.p0.engineering_contracts import EngineeringRef
from packages.contracts.p1.build_records import BuildExecutionArtifact, BuildExecutionObservation
from packages.contracts.p1.workspace_git import content_digest

from .artifact_environment_docker import engine
from .engineering_build_attempt import MAX_JOURNAL_BYTES, read_attempt_intent
from .toolchain import ProbeFailure

UNKNOWN_OBSERVATION = "observation-unknown.json"
FINAL_OBSERVATION = "observation.json"
BUILD_METHOD = EngineeringRef(kind="method", object_id="controlled-reference-build",
    revision="p1-fixed-reference-build-r3", authority="runner", digest_algorithm="sha256",
    digest=content_digest(b"p1-fixed-reference-build-r3: admitted immutable candidate, fixed offline recipes, "
        b"three OCI roles, exporter/load identities, actual builder stop reconciliation, verified local frontend "
        b"OCI layouts bound to their pinned raw indexes and linux/amd64 manifests before group start"))


def read_result(root_fd):
    if not exists_at(root_fd, "result.json"):
        return None
    result = json.loads(read_regular(root_fd, "result.json", MAX_JOURNAL_BYTES))
    closure = result["closure"]
    if (closure not in {"closed_unstarted", "ended_reconciled", "safely_stopped", "unknown"}
            or (closure == "ended_reconciled") != (result["exit_code"] is not None)):
        raise ProbeFailure("engineering_build_closed_observation_mismatch")
    return result


def read_observations(root_fd, intent):
    record, identity = intent.record, intent.resource.identity
    values = []
    for name in (UNKNOWN_OBSERVATION, FINAL_OBSERVATION):
        if not exists_at(root_fd, name):
            values.append(None)
            continue
        value = BuildExecutionObservation.model_validate_json(read_regular(root_fd, name, MAX_JOURNAL_BYTES))
        if (value.operation_id != record.operation_id or value.request_digest != record.request_digest
                or value.build_input_digest != record.build_input_digest
                or value.executor_instance_id != identity.executor_instance_id
                or value.executor_generation != identity.resource_generation):
            raise ProbeFailure("engineering_build_closed_observation_mismatch")
        values.append(value)
    unknown, final = values
    if unknown is not None and (unknown.closure != "unknown" or unknown.artifacts
                                or unknown.previous_observation_id is not None):
        raise ProbeFailure("engineering_build_closed_observation_mismatch")
    if final is not None and (
            final.closure in {"unknown", "running"}
            or final.previous_observation_id != (unknown.observation_id if unknown is not None else None)
            or (unknown is not None and final.observed_at < unknown.observed_at)):
        raise ProbeFailure("engineering_build_closed_observation_mismatch")
    return unknown, final


def check_previous_builds(storage, record, registered):
    """Do not admit a new conflicting group while an earlier attempt is unresolved."""
    parent = storage.archive_root / "build-operations"
    if not parent.exists():
        return
    for directory in parent.iterdir():
        if directory.name == record.command_id:
            continue
        root = PrivateRoot(directory)
        try:
            intent = read_attempt_intent(root.fd)
            if intent is None:
                continue
            _, final = read_observations(root.fd, intent)
            if intent.record.command_id != directory.name or final is None:
                raise ProbeFailure("engineering_previous_build_requires_reconciliation")
            if final.method_ref == BUILD_METHOD:
                result = read_result(root.fd)
                if result is not None and (result["closure"], result["exit_code"]) == (final.closure, final.exit_code):
                    continue
            if not registered(intent.record, final):
                raise ProbeFailure("engineering_previous_build_requires_reconciliation")
        finally:
            root.close()


def verify_build_artifacts(root_fd, result, store):
    artifacts = []
    for role in ("backend", "frontend", "postgres"):
        report = json.loads(read_regular(root_fd, role + ".json", MAX_JOURNAL_BYTES))
        receipt = store.query(report["artifact"]["storage_id"])
        if receipt.model_dump(mode="json") != report["artifact"]:
            raise ProbeFailure("engineering_build_retained_artifact_mismatch")
        if role != "postgres" and (
                not report.get("all_required_verified")
                or report.get("stop", {}).get("confirmation", {}).get("status") != "verified"
                or report["output"]["exporter_manifest_digest"] != receipt.manifest.digest
                or report["output"]["exporter_config_digest"] != receipt.config.digest):
            raise ProbeFailure("engineering_build_export_or_stop_unverified")
        loaded = result["loaded"][role]
        if loaded.get("docker_identity_kind") != "oci_manifest":
            raise ProbeFailure("engineering_build_loader_identity_unsupported")
        actual = engine("GET", "/images/" + receipt.manifest.digest + "/json")
        if (actual.get("Id") != receipt.manifest.digest or actual.get("Os") != "linux"
                or actual.get("Architecture") != "amd64"
                or actual.get("Descriptor", {}).get("digest") != receipt.manifest.digest
                or loaded["actual_image_id"] != receipt.manifest.digest
                or loaded["manifest_digest"] != receipt.manifest.digest
                or loaded["config_digest"] != receipt.config.digest):
            raise ProbeFailure("engineering_build_loaded_image_mismatch")
        artifacts.append(BuildExecutionArtifact(role=role, storage_id=receipt.storage_id,
            manifest_digest=receipt.manifest.digest, config_digest=receipt.config.digest,
            loaded_image_id=actual["Id"], docker_identity_kind="oci_manifest"))
    return tuple(artifacts)
