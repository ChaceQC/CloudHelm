"""Durable fixed-reference build execution and verified physical observations."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime

from modules.artifacts.content_store import ArtifactStore
from modules.workspaces.safe_paths import PrivateRoot, WorkspaceFileError, exists_at, read_regular, write_new_file
from packages.contracts.p0.engineering_contracts import EngineeringRef
from packages.contracts.p1.build_records import BuildExecutionArtifact, BuildExecutionObservation, BuildRunRecord
from packages.contracts.p1.resource_protocol import DEVELOPMENT_BACKEND, ExecutorReceipt, canonical_digest
from packages.contracts.p1.workspace_git import content_digest

from .artifact_environment_docker import engine
from .artifact_environment_images import export_postgres, load
from .engineering_definition import PreparedBuild
from .engineering_seeds import prepare_build_seeds
from .frontend_build_runtime import build_frontend
from .toolchain import DockerClient, ProbeFailure, private_directory

METHOD_DESCRIPTION = (b"p1-fixed-reference-build-r3: admitted immutable candidate, fixed offline recipes, "
    b"three OCI roles, exporter/load identities, actual builder stop reconciliation, verified local frontend "
    b"OCI layouts bound to their pinned raw indexes and linux/amd64 manifests before group start")
STOP_RECONCILIATION_METHOD = EngineeringRef(kind="method", object_id="controlled-reference-build-stop",
    revision="p1-build-stop-reconciliation-r1", authority="runner", digest_algorithm="sha256",
    digest=content_digest(b"p1-build-stop-reconciliation-r1: bound Runner group stop and tmpfs reclamation"))


def _bound_observation(value, record, executor_instance_id):
    if (value.operation_id != record.operation_id or value.request_digest != record.request_digest
            or value.build_input_digest != record.build_input_digest
            or value.executor_instance_id != executor_instance_id or value.executor_generation != 1):
        raise ProbeFailure("engineering_build_closed_observation_mismatch")
    return value


def _read_observation(root, record, name, executor_instance_id):
    if not exists_at(root.fd, name):
        return None
    value = BuildExecutionObservation.model_validate_json(read_regular(root.fd, name, 1024**2))
    return _bound_observation(value, record, executor_instance_id)


def _read_result(root):
    if not exists_at(root.fd, "result.json"):
        return None
    result = json.loads(read_regular(root.fd, "result.json", 1024**2))
    closure = result["closure"]
    if (closure not in {"closed_unstarted", "ended_reconciled", "safely_stopped", "unknown"}
            or (closure == "ended_reconciled") != (result["exit_code"] is not None)):
        raise ProbeFailure("engineering_build_closed_observation_mismatch")
    return result


def _check_stopped_observation(stopped, record, previous):
    if (stopped.observation_id != "engineering-build-stopped-" + record.command_id
            or stopped.closure != "safely_stopped" or stopped.artifacts
            or (stopped.previous_observation_id is None and stopped.method_ref != STOP_RECONCILIATION_METHOD)):
        raise ProbeFailure("engineering_build_closed_observation_mismatch")
    if previous is not None:
        if (stopped.previous_observation_id not in {None, previous.observation_id}
                or stopped.observed_at < previous.observed_at
                or (stopped.method_ref != STOP_RECONCILIATION_METHOD and stopped != previous.model_copy(update={
                    "observation_id": stopped.observation_id, "previous_observation_id": previous.observation_id,
                    "closure": "safely_stopped", "observed_at": stopped.observed_at,
                }))):
            raise ProbeFailure("engineering_build_closed_observation_mismatch")


def check_previous_builds(storage, record, registered):
    """Check incomplete journals before admitting another physical group."""
    parent = storage.archive_root / "build-operations"
    if not parent.exists():
        return
    executor = "controlled-" + storage.admission.snapshot.registration.storage_id
    for directory in parent.iterdir():
        if directory.name == record.command_id:
            continue
        root = PrivateRoot(directory)
        try:
            if not exists_at(root.fd, "intent.json"):
                continue
            previous = BuildRunRecord.model_validate_json(read_regular(root.fd, "intent.json", 1024**2))
            if previous.command_id != directory.name:
                raise ProbeFailure("engineering_previous_build_requires_reconciliation")
            result = _read_result(root)
            observation = _read_observation(root, previous, "observation.json", executor)
            stopped = _read_observation(root, previous, "observation-stopped.json", executor)
            if observation is not None and observation.closure not in {"unknown", "running"}:
                if stopped is None:
                    if result is None and registered(previous, observation):
                        continue
                    if (result is not None and (result["closure"], result["exit_code"])
                            == (observation.closure, observation.exit_code)):
                        continue
                raise ProbeFailure("engineering_previous_build_requires_reconciliation")
            if stopped is None or (observation is not None and (observation.closure != "unknown" or observation.artifacts)):
                raise ProbeFailure("engineering_previous_build_requires_reconciliation")
            _check_stopped_observation(stopped, previous, observation)
            if not registered(previous, stopped):
                raise ProbeFailure("engineering_previous_build_requires_reconciliation")
        finally:
            root.close()


class _GatedDockerClient:
    def __init__(self, client, gate):
        self._client, self._gate = client, gate
        self.config_directory = client.config_directory

    def run(self, *arguments, **kwargs):
        if arguments[0] in {"create", "start", "pull", "build", "cp", "exec", "manifest"}:
            self._gate()
        return self._client.run(*arguments, **kwargs)


class _GatedContentStore:
    def __init__(self, store, gate):
        self._store, self._gate = store, gate

    def publish(self, *arguments, **kwargs):
        self._gate()
        return self._store.publish(*arguments, **kwargs)

    def query(self, *arguments, **kwargs):
        return self._store.query(*arguments, **kwargs)

    def open_archive(self, *arguments, **kwargs):
        return self._store.open_archive(*arguments, **kwargs)


class ControlledBuildRunner:
    """Only the composition root supplies a gate and admitted roots, never HTTP DTOs.

    An existing intent is queried even after a worker restart. An incomplete
    journal never causes a second builder or source export to be launched.
    """

    def __init__(self, storage, record: BuildRunRecord, gate):
        self.storage, self.record, self.gate = storage, record, gate
        private_directory(storage.archive_root / "artifacts")
        private_directory(storage.archive_root / "build-operations")
        self.directory = storage.archive_root / "build-operations" / record.command_id
        private_directory(self.directory)
        self.root = PrivateRoot(self.directory)
        self.store = ArtifactStore(storage.archive_root / "artifacts")
        self.client = None
        self.previous_observation: BuildExecutionObservation | None = None
        self.recovered_stop_receipt: ExecutorReceipt | None = None
        self._executed = False

    def _read(self, name):
        return json.loads(read_regular(self.root.fd, name, 1024**2).decode("utf-8"))

    def _write(self, name, value):
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if len(raw) > 1024**2:
            raise ProbeFailure("engineering_build_journal_bound_exceeded")
        write_new_file(self.root.fd, name, raw)

    def exists(self):
        return exists_at(self.root.fd, "intent.json")

    def _operation_ids(self):
        return tuple("engineering-" + role + "-" + self.record.command_id for role in ("backend", "frontend"))

    def _containers(self):
        from .resource_context import current_group

        group = current_group()
        if group is not None and group.stopped:
            return []
        values = engine("GET", "/containers/json?all=1")
        operations = set(self._operation_ids())
        return [item for item in values if (item.get("Labels") or {}).get("cloudhelm.operation_id") in operations]

    def execute(self, prepared: PreparedBuild, frontend_bases: dict):
        if self.exists():
            return
        self.gate()
        self._write("intent.json", self.record.model_dump(mode="json"))
        reports, loaded, invoked = {}, {}, []
        closure, exit_code = "closed_unstarted", None
        failure = None
        try:
            self.gate()
            seeds = prepare_build_seeds(self.storage, backend_source=prepared.backend.inputs)
            client_directory = self.directory / "client"
            private_directory(client_directory)
            self.client = _GatedDockerClient(DockerClient.create(client_directory), self.gate)
            content = _GatedContentStore(self.store, self.gate)
            from .backend_build_runtime import build_backend

            for role in ("backend", "frontend"):
                self.gate()
                directory = self.directory / role
                private_directory(directory)
                operation = "engineering-" + role + "-" + self.record.command_id
                invoked.append(role)
                if role == "backend":
                    report = build_backend(self.client, operation, directory, seeds["python_root"],
                        seeds["python_manifest"], source=prepared.backend, recipe=prepared.backend_recipe,
                        source_ref=self.record.fixed_inputs.candidate.candidate_commit, content_store=content)
                else:
                    report = build_frontend(self.client, operation, directory, seeds["npm_root"],
                        seeds["npm_manifest"], source_inputs=prepared.frontend, recipe=prepared.frontend_recipe,
                        expected_source_manifest_digest=prepared.frontend.receipt["manifest_digest"],
                        content_store=content, seed_spec=seeds["npm_spec"], bases=frontend_bases)
                reports[role] = report
                self._write(role + ".json", report)
                if not report.get("all_required_verified"):
                    raise ProbeFailure("engineering_" + role + "_build_unverified")
            self.gate()
            postgres = self.directory / "postgres"
            private_directory(postgres)
            receipt = export_postgres(content, postgres, before_side_effect=self.gate)
            reports["postgres"] = {"artifact": receipt.model_dump(mode="json")}
            self._write("postgres.json", reports["postgres"])
            for role in ("backend", "frontend", "postgres"):
                self.gate()
                receipt = self.store.query(reports[role]["artifact"]["storage_id"])
                loaded[role] = load(self.store, receipt)
            closure, exit_code = "ended_reconciled", 0
        except Exception as error:
            failure = error.category if isinstance(error, ProbeFailure) else "engineering_build_" + type(error).__name__
            if invoked:
                stopped = all(reports.get(role, {}).get("stop", {}).get("confirmation", {}).get("status") == "verified"
                              for role in invoked)
                closure = "safely_stopped" if stopped and not self._containers() else "unknown"
        self._write("result.json", {"closure": closure, "exit_code": exit_code, "invoked": invoked,
            "loaded": loaded, "failure": failure, "observed_at": datetime.now(UTC).isoformat()})
        self._executed = True

    def _confirmed_stop(self, group):
        resource = group.request.resources
        registration = group.registration
        storage = self.storage.admission.snapshot.registration
        if (group.request.backend != DEVELOPMENT_BACKEND or registration.backend != DEVELOPMENT_BACKEND
                or registration.storage.storage_id != storage.storage_id
                or registration.storage.instance_revision != storage.instance_revision
                or group.dispatcher.runner.registration != registration):
            raise ProbeFailure("engineering_build_resource_binding_mismatch")
        reservation = "engineering-resource-" + canonical_digest({
            "key": self.record.operation_id, "storage": registration.storage.model_dump(mode="json"),
        })[7:47]
        if resource.identity.reservation_id != reservation or resource.identity.operation_id != reservation:
            raise ProbeFailure("engineering_build_resource_binding_mismatch")
        try:
            receipt = group.dispatcher.runner.query(reservation)
        except (OSError, TimeoutError):
            return None
        if receipt is None:
            return None
        if (receipt.identity != resource.identity or receipt.request_digest != resource.request_digest
                or (receipt.process_binding is not None and receipt.process_binding != group.binding)):
            raise ProbeFailure("engineering_build_resource_binding_mismatch")
        if (receipt.state == "stopped" and receipt.disk_reclaimed
                and receipt.evidence.get("process_group_removed") is True
                and receipt.evidence.get("runtime_tmpfs_reclaimed") is True):
            return receipt
        return None

    def _recover_observation(self, group, value, head, executor):
        if value is not None and (value.closure != "unknown" or value.artifacts):
            raise ProbeFailure("engineering_build_closed_observation_mismatch")
        stopped = _read_observation(self.root, self.record, "observation-stopped.json", executor)
        if head is not None and head.closure != "unknown":
            if stopped is not None and stopped != head:
                raise ProbeFailure("engineering_build_closed_observation_mismatch")
            candidate = head
            previous = value
        else:
            if head is not None and (head.artifacts or (value is not None and head != value)):
                raise ProbeFailure("engineering_build_closed_observation_mismatch")
            candidate = stopped
            previous = head or value
            if candidate is not None and candidate.previous_observation_id != (head.observation_id if head else None):
                raise ProbeFailure("engineering_build_closed_observation_mismatch")
        if candidate is not None:
            _check_stopped_observation(candidate, self.record, previous)

        released = candidate is not None and candidate == head and group is not None and group.stopped
        receipt = self._confirmed_stop(group) if group is not None and not released else None
        if not released and receipt is None:
            if candidate is not None and (head is None or head == candidate):
                # Registering anything here could strand a durable observation or regress the Hub head.
                raise ProbeFailure("engineering_build_observation_requires_reconciliation")
            if previous is not None:
                return previous

        if candidate is None:
            observed = datetime.now(UTC)
            if previous is not None and observed < previous.observed_at:
                raise ProbeFailure("engineering_build_observation_clock_regressed")
            candidate = BuildExecutionObservation(
                observation_id=("engineering-build-stopped-" if receipt is not None else "engineering-build-")
                + self.record.command_id,
                operation_id=self.record.operation_id, request_digest=self.record.request_digest,
                build_input_digest=self.record.build_input_digest, executor_instance_id=executor,
                executor_generation=1, previous_observation_id=head.observation_id if head else None,
                closure="safely_stopped" if receipt is not None else "unknown",
                method_ref=STOP_RECONCILIATION_METHOD, observed_at=observed,
            )
        if stopped is None:
            name = "observation-stopped.json" if candidate.closure == "safely_stopped" else "observation.json"
            self._write(name, candidate.model_dump(mode="json"))
            if _read_observation(self.root, self.record, name, executor) != candidate:
                raise ProbeFailure("engineering_build_closed_observation_mismatch")
        self.recovered_stop_receipt = receipt
        return candidate

    def read_verified_build_observation(self, operation_id):
        self.recovered_stop_receipt = None
        self.storage.observe()
        if operation_id != self.record.operation_id or not self.exists():
            raise ProbeFailure("engineering_build_operation_not_found")
        if BuildRunRecord.model_validate(self._read("intent.json")) != self.record:
            raise ProbeFailure("engineering_build_intent_mismatch")
        from .resource_context import current_group

        group = current_group()
        result = _read_result(self.root)
        executor = "controlled-" + self.storage.admission.snapshot.registration.storage_id
        value = _read_observation(self.root, self.record, "observation.json", executor)
        head = self.previous_observation
        if head is not None:
            _bound_observation(head, self.record, executor)
        released = group is not None and group.stopped
        missing = result is None or (value is None and not self._executed)
        if ((missing and not (released and value is not None and value == head))
                or (result is not None and result["closure"] == "unknown")
                or (value is not None and value.closure in {"unknown", "running"})):
            return self._recover_observation(group, value, head, executor)

        if ((head is not None and head != value) or exists_at(self.root.fd, "observation-stopped.json")
                or (result is not None and value is not None
                    and (value.closure, value.exit_code) != (result["closure"], result["exit_code"]))):
            raise ProbeFailure("engineering_build_closed_observation_mismatch")
        if released:
            if value is None:
                raise ProbeFailure("engineering_build_closed_observation_mismatch")
            for artifact in value.artifacts:
                receipt = self.store.query(artifact.storage_id)
                if receipt.manifest.digest != artifact.manifest_digest or receipt.config.digest != artifact.config_digest:
                    raise ProbeFailure("engineering_build_retained_artifact_mismatch")
            return value
        present = self._containers()
        closure, exit_code = result["closure"], result["exit_code"]
        artifacts = []
        if present:
            closure, exit_code = "unknown", None
        if closure == "ended_reconciled" and exit_code == 0:
            for role in ("backend", "frontend", "postgres"):
                report = self._read(role + ".json")
                receipt = self.store.query(report["artifact"]["storage_id"])
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
        name = "observation.json"
        if value is not None:
            if (value.closure != closure or value.exit_code != exit_code or value.artifacts != tuple(artifacts)):
                raise ProbeFailure("engineering_build_observation_requires_reconciliation")
            return value
        observed = datetime.fromisoformat(result["observed_at"])
        value = BuildExecutionObservation(
            observation_id="engineering-build-" + self.record.command_id,
            operation_id=operation_id, request_digest=self.record.request_digest,
            build_input_digest=self.record.build_input_digest,
            executor_instance_id="controlled-" + self.storage.admission.snapshot.registration.storage_id,
            executor_generation=1,
            closure=closure, exit_code=exit_code, artifacts=tuple(artifacts),
            method_ref=EngineeringRef(kind="method", object_id="controlled-reference-build",
                revision="p1-fixed-reference-build-r3", authority="runner",
                digest=content_digest(METHOD_DESCRIPTION), digest_algorithm="sha256"), observed_at=observed,
        )
        self._write(name, value.model_dump(mode="json"))
        return value

    def close(self):
        self.store.__exit__()
        self.root.close()
