"""Durable fixed-reference build execution and verified physical observations."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime

from modules.artifacts.content_store import ArtifactStore
from modules.workspaces.safe_paths import PrivateRoot, WorkspaceFileError, exists_at, read_regular, write_new_file
from packages.contracts.p0.engineering_contracts import EngineeringRef
from packages.contracts.p1.build_records import BuildExecutionArtifact, BuildExecutionObservation, BuildRunRecord
from packages.contracts.p1.workspace_git import content_digest

from .artifact_environment_docker import engine
from .artifact_environment_images import export_postgres, load
from .engineering_definition import definition_and_frontend_for_candidate, split_sources
from .engineering_seeds import prepare_build_seeds
from .frontend_build_runtime import build_frontend
from .toolchain import DockerClient, ProbeFailure, private_directory

METHOD_DESCRIPTION = b"p1-fixed-reference-build-r1: admitted immutable candidate, fixed offline recipes, three OCI roles, exporter/load identities and actual builder stop reconciliation"


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
        self.previous_observation_id = None

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

    def execute(self, files):
        if self.exists():
            return
        self.gate()
        files = dict(files)
        definition, frontend = definition_and_frontend_for_candidate(
            files, self.record.fixed_inputs.definition.acceptance_assets_ref)
        if definition != self.record.fixed_inputs.definition:
            raise ProbeFailure("engineering_build_definition_mismatch")
        # A retained unknown build blocks another build group in this pool.
        for directory in self.directory.parent.iterdir():
            if directory == self.directory:
                continue
            root = PrivateRoot(directory)
            try:
                if exists_at(root.fd, "intent.json") and not exists_at(root.fd, "result.json"):
                    raise ProbeFailure("engineering_previous_build_requires_reconciliation")
                if exists_at(root.fd, "result.json") and json.loads(read_regular(root.fd, "result.json", 1024**2))["closure"] == "unknown":
                    raise ProbeFailure("engineering_previous_build_requires_reconciliation")
            finally:
                root.close()
        self._write("intent.json", self.record.model_dump(mode="json"))
        reports, loaded, invoked = {}, {}, []
        closure, exit_code = "closed_unstarted", None
        failure = None
        try:
            self.gate()
            backend = split_sources(files, "backend")
            seeds = prepare_build_seeds(self.storage, backend_source=backend)
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
                        seeds["python_manifest"], source_files=backend,
                        source_ref=self.record.fixed_inputs.candidate.candidate_commit, content_store=content)
                else:
                    report = build_frontend(self.client, operation, directory, seeds["npm_root"],
                        seeds["npm_manifest"], source_inputs=frontend,
                        expected_source_manifest_digest=frontend.receipt["manifest_digest"],
                        content_store=content, seed_spec=seeds["npm_spec"])
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

    def read_verified_build_observation(self, operation_id):
        self.storage.observe()
        if operation_id != self.record.operation_id or not self.exists():
            raise ProbeFailure("engineering_build_operation_not_found")
        if BuildRunRecord.model_validate(self._read("intent.json")) != self.record:
            raise ProbeFailure("engineering_build_intent_mismatch")
        from .resource_context import current_group

        group = current_group()
        if group is not None and group.stopped:
            value = BuildExecutionObservation.model_validate(self._read("observation.json"))
            if (value.operation_id != operation_id or value.request_digest != self.record.request_digest
                    or value.build_input_digest != self.record.build_input_digest or value.closure == "unknown"):
                raise ProbeFailure("engineering_build_closed_observation_mismatch")
            for artifact in value.artifacts:
                receipt = self.store.query(artifact.storage_id)
                if receipt.manifest.digest != artifact.manifest_digest or receipt.config.digest != artifact.config_digest:
                    raise ProbeFailure("engineering_build_retained_artifact_mismatch")
            return value
        present = self._containers()
        result = self._read("result.json") if exists_at(self.root.fd, "result.json") else None
        closure = "unknown" if result is None else result["closure"]
        exit_code = None if result is None else result["exit_code"]
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
        if exists_at(self.root.fd, name):
            value = BuildExecutionObservation.model_validate(self._read(name))
            if (value.closure != closure or value.exit_code != exit_code or value.artifacts != tuple(artifacts)):
                raise ProbeFailure("engineering_build_observation_requires_reconciliation")
            return value
        observed = datetime.now(UTC) if result is None else datetime.fromisoformat(result["observed_at"])
        value = BuildExecutionObservation(
            observation_id="engineering-build-" + self.record.command_id,
            operation_id=operation_id, request_digest=self.record.request_digest,
            build_input_digest=self.record.build_input_digest,
            executor_instance_id="controlled-" + self.storage.admission.snapshot.registration.storage_id,
            executor_generation=1, previous_observation_id=self.previous_observation_id,
            closure=closure, exit_code=exit_code, artifacts=tuple(artifacts),
            method_ref=EngineeringRef(kind="method", object_id="controlled-reference-build",
                revision="p1-fixed-reference-build-r1", authority="runner",
                digest=content_digest(METHOD_DESCRIPTION), digest_algorithm="sha256"), observed_at=observed,
        )
        self._write(name, value.model_dump(mode="json"))
        return value

    def close(self):
        self.store.__exit__()
        self.root.close()
