"""Durable fixed-reference build execution and verified physical observations."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime

from modules.artifacts.content_store import ArtifactStore
from modules.workspaces.safe_paths import PrivateRoot, exists_at, read_regular
from packages.contracts.p0.engineering_contracts import EngineeringRef
from packages.contracts.p1.build_records import BuildExecutionObservation, BuildRunRecord
from packages.contracts.p1.workspace_git import content_digest

from .artifact_environment_docker import engine
from .artifact_environment_images import export_postgres, load
from .engineering_build_attempt import (
    BuildAttemptInspection, BuildAttemptIntent, build_resource, confirmed_stop, query_resource,
    read_attempt_intent, try_lock_intent, write_journal,
)
from .engineering_build_observation import (
    BUILD_METHOD, FINAL_OBSERVATION, UNKNOWN_OBSERVATION, check_previous_builds, read_observations, read_result,
    verify_build_artifacts,
)
from .engineering_definition import PreparedBuild
from .engineering_seeds import prepare_build_seeds
from .frontend_build_runtime import build_frontend
from .resource_context import current_group
from .toolchain import DockerClient, ProbeFailure, private_directory

STOP_RECONCILIATION_METHOD = EngineeringRef(kind="method", object_id="controlled-reference-build-stop",
    revision="p1-build-stop-reconciliation-r2", authority="runner", digest_algorithm="sha256",
    digest=content_digest(b"p1-build-stop-reconciliation-r2: bound Runner stop, start fence, and tmpfs reclamation"))


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
        self.storage, self.record, self._gate = storage, record, gate
        self.directory = storage.archive_root / "build-operations" / record.command_id
        self.root = None
        self._store = None
        self._last_inspection: BuildAttemptInspection | None = None

    def _open(self, *, create=False):
        if self.root is None:
            if create:
                private_directory(self.directory.parent)
                private_directory(self.directory)
            elif not self.directory.exists():
                return False
            self.root = PrivateRoot(self.directory)
        return True

    @property
    def store(self):
        if self._store is None:
            self._store = ArtifactStore(self.storage.archive_root / "artifacts")
        return self._store

    def _read(self, name):
        return json.loads(read_regular(self.root.fd, name, 1024**2))

    def _write(self, name, value):
        write_journal(self.root.fd, name, value)

    def exists(self):
        return self._open() and exists_at(self.root.fd, "intent.json")

    def _intent(self):
        value = read_attempt_intent(self.root.fd)
        if value is not None and value.record != self.record:
            raise ProbeFailure("engineering_build_intent_mismatch")
        return value

    def _bound_resource(self, intent, group):
        resource = build_resource(self.storage, self.record, group)
        if intent.resource != resource:
            raise ProbeFailure("engineering_build_resource_binding_mismatch")
        return resource

    def gate(self):
        self._gate()
        if exists_at(self.root.fd, "stop-request.json"):
            raise ProbeFailure("engineering_build_stop_requested")

    def _operation_ids(self):
        return tuple("engineering-" + role + "-" + self.record.command_id for role in ("backend", "frontend"))

    def _containers(self):
        group = current_group()
        if group is not None and group.stopped:
            return []
        values = engine("GET", "/containers/json?all=1")
        operations = set(self._operation_ids())
        return [item for item in values if (item.get("Labels") or {}).get("cloudhelm.operation_id") in operations]

    def submit(self, prepared: PreparedBuild | None, frontend_bases: dict | None, *, start_resource):
        """Accept only once, then execute synchronously on the admitted group."""
        self._open(create=True)
        lease = None
        with self.root.exclusive():
            if self._intent() is None:
                self.gate()
                group = current_group()
                resource = build_resource(self.storage, self.record, group)
                if group.stopped or prepared is None or prepared.definition != self.record.fixed_inputs.definition:
                    raise ProbeFailure("engineering_build_definition_or_admission_mismatch")
                intent = BuildAttemptIntent(record=self.record, resource=resource, accepted_at=datetime.now(UTC))
                self._write("intent.json", intent.model_dump(mode="json"))
                lease = try_lock_intent(self.root.fd)
        if lease is not None:
            try:
                # Serialize the resource start gate with the stop intent. The build itself
                # holds no journal lock, allowing independent stop while a builder runs.
                with self.root.exclusive():
                    self.gate()
                    self._write("resource-start.json", {"requested_at": datetime.now(UTC).isoformat()})
                    start_resource()
            except (OSError, ValueError, ProbeFailure):
                # A lost response is reconciled against this attempt, never retried.
                pass
            else:
                self._execute(prepared, frontend_bases)
            finally:
                os.close(lease)
        return self.inspect()

    def request_stop(self, operation_id, executor_generation):
        self.storage.observe()
        if operation_id != self.record.operation_id:
            raise ProbeFailure("engineering_build_operation_not_found")
        group = current_group()
        if group is None and not self.exists():
            return None
        self._open(create=group is not None)
        with self.root.exclusive():
            intent = self._intent()
            resource = (build_resource(self.storage, self.record, group) if intent is None
                        else self._bound_resource(intent, group))
            if resource.identity.resource_generation != executor_generation:
                raise ProbeFailure("engineering_build_resource_binding_mismatch")
            if intent is None:
                intent = BuildAttemptIntent(record=self.record, resource=resource, accepted_at=None,
                                            preaccept_stop_at=datetime.now(UTC))
                self._write("intent.json", intent.model_dump(mode="json"))
            elif intent.preaccept_stop_at is None and not exists_at(self.root.fd, "stop-request.json"):
                self._write("stop-request.json", {"requested_at": datetime.now(UTC).isoformat()})
            never_started = not exists_at(self.root.fd, "resource-start.json")
        if not group.stopped:
            try:
                reservation_id = resource.identity.reservation_id
                if never_started and query_resource(group, resource) is None:
                    # The stop intent fences the start marker. Deliver just the existing
                    # reservation to obtain the controller's durable never-start fence.
                    if group.path.exists() or group.socket.parent.exists():
                        return self.inspect()  # Local ledger absence does not prove old processes stopped.
                    group.dispatcher.deliver(reservation_id)
                group.dispatcher.stop(reservation_id)
            except (OSError, TimeoutError):
                pass  # The intent is durable. Only an original physical receipt settles it.
        return self.inspect()

    def _execute(self, prepared: PreparedBuild, frontend_bases: dict):
        reports, loaded, invoked = {}, {}, []
        closure, exit_code = "closed_unstarted", None
        failure = None
        try:
            self.gate()
            private_directory(self.storage.archive_root / "artifacts")
            seeds = prepare_build_seeds(self.storage, backend_source=prepared.backend.inputs)
            client_directory = self.directory / "client"
            private_directory(client_directory)
            client = _GatedDockerClient(DockerClient.create(client_directory), self.gate)
            content = _GatedContentStore(self.store, self.gate)
            from .backend_build_runtime import build_backend

            for role in ("backend", "frontend"):
                self.gate()
                directory = self.directory / role
                private_directory(directory)
                operation = "engineering-" + role + "-" + self.record.command_id
                invoked.append(role)
                if role == "backend":
                    report = build_backend(client, operation, directory, seeds["python_root"],
                        seeds["python_manifest"], source=prepared.backend, recipe=prepared.backend_recipe,
                        source_ref=self.record.fixed_inputs.candidate.candidate_commit, content_store=content)
                else:
                    report = build_frontend(client, operation, directory, seeds["npm_root"],
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
                receipt = self.store.query(reports[role]["artifact"]["storage_id"])
                self.gate()
                loaded[role] = load(self.store, receipt)
            closure, exit_code = "ended_reconciled", 0
        except Exception as error:
            failure = error.category if isinstance(error, ProbeFailure) else "engineering_build_" + type(error).__name__
            if invoked:
                closure = "unknown"
                stopped = all(reports.get(role, {}).get("stop", {}).get("confirmation", {}).get("status") == "verified"
                              for role in invoked)
                if stopped and not exists_at(self.root.fd, "stop-request.json"):
                    try:
                        if not self._containers():
                            closure = "safely_stopped"
                    except ProbeFailure:
                        pass  # A disconnected daemon is not stop evidence.
        self._write("result.json", {"closure": closure, "exit_code": exit_code, "invoked": invoked,
            "loaded": loaded, "failure": failure, "observed_at": datetime.now(UTC).isoformat()})

    @property
    def recovered_stop_receipt(self):
        return confirmed_stop(self._last_inspection.resource_receipt) if self._last_inspection else None

    def inspect(self) -> BuildAttemptInspection | None:
        """Inspect only the admitted, original attempt and its physical group."""
        self.storage.observe()
        if not self._open():
            return None
        group = current_group()
        with self.root.exclusive():
            intent = self._intent()
            if intent is None:
                return None
            resource = self._bound_resource(intent, group)
            receipt = query_resource(group, resource)
            stop_requested_at = intent.preaccept_stop_at
            if exists_at(self.root.fd, "stop-request.json"):
                stop_requested_at = datetime.fromisoformat(self._read("stop-request.json")["requested_at"])
            observation, predecessor = self._observation(intent, confirmed_stop(receipt), stop_requested_at is not None)
            identity = resource.identity
            self._last_inspection = BuildAttemptInspection(
                intent.accepted_at, identity.executor_instance_id, identity.resource_generation,
                stop_requested_at, observation, receipt, predecessor,
            )
        return self._last_inspection

    def read_verified_build_observation(self, operation_id, *, predecessor=False):
        if operation_id != self.record.operation_id:
            raise ProbeFailure("engineering_build_operation_not_found")
        inspection = self._last_inspection or self.inspect()
        if inspection is not None:
            observation = inspection.predecessor if predecessor else inspection.observation
            if observation is not None:
                return observation
        raise ProbeFailure("engineering_build_observation_unavailable")

    def _observation(self, intent, stop_receipt, stop_requested):
        unknown, final = read_observations(self.root.fd, intent)
        if final is not None:
            for artifact in final.artifacts:
                retained = self.store.query(artifact.storage_id)
                if retained.manifest.digest != artifact.manifest_digest or retained.config.digest != artifact.config_digest:
                    raise ProbeFailure("engineering_build_retained_artifact_mismatch")
            return final, unknown

        closure, exit_code, artifacts = "unknown", None, ()
        method = STOP_RECONCILIATION_METHOD
        if stop_receipt is not None:
            closure = "closed_unstarted" if stop_receipt.state == "closed_unstarted" else "safely_stopped"
        elif not stop_requested:
            result = read_result(self.root.fd)
            if result is not None and result["closure"] != "unknown":
                try:
                    if not self._containers():
                        if result["closure"] == "ended_reconciled" and result["exit_code"] == 0:
                            artifacts = verify_build_artifacts(self.root.fd, result, self.store)
                        closure, exit_code = result["closure"], result["exit_code"]
                        method = BUILD_METHOD
                except ProbeFailure as error:
                    if error.category != "artifact_environment_docker_unavailable":
                        raise

        if closure == "unknown":
            if unknown is not None:
                return unknown, None
            lease = try_lock_intent(self.root.fd)
            if lease is None:
                return None, None  # The synchronous caller still owns this attempt.
            os.close(lease)

        observed_at = datetime.now(UTC)
        if unknown is not None and observed_at < unknown.observed_at:
            raise ProbeFailure("engineering_build_observation_clock_regressed")
        identity = intent.resource.identity
        value = BuildExecutionObservation(
            observation_id=("engineering-build-unknown-" if closure == "unknown" else "engineering-build-")
            + self.record.command_id,
            operation_id=self.record.operation_id, request_digest=self.record.request_digest,
            build_input_digest=self.record.build_input_digest,
            executor_instance_id=identity.executor_instance_id, executor_generation=identity.resource_generation,
            previous_observation_id=unknown.observation_id if unknown is not None else None,
            closure=closure, exit_code=exit_code, artifacts=artifacts, method_ref=method, observed_at=observed_at,
        )
        self._write(UNKNOWN_OBSERVATION if closure == "unknown" else FINAL_OBSERVATION, value.model_dump(mode="json"))
        return value, unknown

    def close(self):
        if self._store is not None:
            self._store.close()
        if self.root is not None:
            self.root.close()
