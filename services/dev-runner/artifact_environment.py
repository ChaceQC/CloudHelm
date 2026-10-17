"""A callable, bounded local artifact environment and versioned synthetic dataset."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from modules.artifacts.content_store import ArtifactStore
from modules.projects.reference_assets import ACCEPTANCE_ROOT, _read_public_file, load_reference_assets
from modules.workspaces.reference_seed import _seed_root
from packages.contracts.p1.development_environment import (
    ArtifactEnvironmentObservation, ArtifactEnvironmentSpec, EnvironmentArtifactSet, MIGRATION_REVISION, ROLES,
)

from .artifact_environment_docker import EnvironmentGroup, command, engine, metadata
from .artifact_environment_images import export_postgres, intake, load, verify_postgres_receipt
from .artifact_environment_runtime import ArtifactRuntime
from .toolchain import ProbeFailure


class ArtifactEnvironment:
    """Internal maintenance API; the caller owns business gates and storage admission.

    Keep the admission scope open until dispose() confirms all writers stopped.
    Unknown cleanup raises; callers must retain the pool and reconcile the original
    operation rather than opening another execution or releasing its storage.
    """

    def __init__(self, admission, spec: ArtifactEnvironmentSpec, applications: dict,
                 repository: Path):
        if (type(spec) is not ArtifactEnvironmentSpec
                or set(applications) not in ({"backend", "frontend"}, set(ROLES))
                or admission.snapshot.registration.storage_id != spec.storage_ref.storage_id
                or admission.snapshot.registration.instance_revision != spec.storage_ref.instance_revision
                or admission.snapshot.registration.scope != "local_controlled_development"
                or admission.snapshot.purpose != "workspace"):
            raise ProbeFailure("artifact_environment_registration_or_roles_invalid")
        admission.observe()
        if admission.snapshot.allocatable_bytes < 2 * 1024**3:
            raise ProbeFailure("artifact_environment_storage_headroom_insufficient")
        self.admission, self.spec, self.applications = admission, spec, applications
        self.repository = Path(repository)
        self.assets = load_reference_assets(self.repository)
        if self.assets.bundle_digest != spec.acceptance_bundle_digest:
            raise ProbeFailure("artifact_environment_acceptance_assets_mismatch")
        self.directory = admission.directory / spec.operation_id
        os.mkdir(spec.operation_id, mode=0o700, dir_fd=admission.directory_fd)
        descriptor = os.open(spec.operation_id, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                             dir_fd=admission.directory_fd)
        try:
            observed = os.fstat(descriptor)
            if observed.st_dev != os.fstat(admission.directory_fd).st_dev or observed.st_mode & 0o077:
                raise ProbeFailure("artifact_environment_directory_boundary_mismatch")
        finally:
            os.close(descriptor)
        self.store: ArtifactStore | None = None
        self.runtime: ArtifactRuntime | None = None
        self.group = EnvironmentGroup(spec.storage_ref.storage_id)
        self.state, self.data_generation = "preparing", 0
        self.artifacts, self.migration_observed = None, None
        self.evidence: dict = {"http": [], "stop_confirmations": [], "data": [], "loaded": {}}
        self._save()

    def _gate(self):
        if datetime.now(timezone.utc) >= self.spec.deadline:
            raise ProbeFailure("artifact_environment_deadline_exceeded")
        self.admission.observe()

    def observation(self) -> ArtifactEnvironmentObservation:
        running = ()
        entrance = None
        if self.runtime is not None:
            running = tuple(role for role in ROLES if role in self.runtime.containers and
                metadata(self.runtime.containers[role], self.spec.operation_id)["State"]["Running"])
            entrance = self.runtime.entrance if self.state == "ready" else None
        return ArtifactEnvironmentObservation(spec=self.spec, state=self.state,
            observed_at=datetime.now(timezone.utc), data_generation=self.data_generation,
            artifacts=self.artifacts, entrance=entrance, running_roles=running,
            migration_observed=self.migration_observed, process_and_readiness_verified=self.state == "ready")

    def _save(self):
        payload = self.observation().model_dump(mode="json")
        temporary = self.directory / ".environment-next.json"
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(payload, output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, self.directory / "environment.json")
        return self.observation()

    def _transition(self, state: str):
        self.state = state
        return self._save()

    def prepare(self):
        if self.state != "preparing" or self.runtime is not None:
            raise ProbeFailure("artifact_environment_already_prepared")
        try:
            self._gate()
            self.group.acquire()
            self.evidence["stage"] = "trusted_application_intake"
            content = self.directory / "content-store"
            content.mkdir(mode=0o700)
            self.store = ArtifactStore(content)
            receipts = {role: intake(self.store, source, receipt, self.directory)
                        for role, (source, receipt) in self.applications.items()}
            self.evidence["stage"] = "fixed_postgres_dependency"
            if "postgres" in receipts:
                verify_postgres_receipt(receipts["postgres"])
            else:
                receipts["postgres"] = export_postgres(self.store, self.directory)
            self.artifacts = EnvironmentArtifactSet(**receipts)
            self._gate()
            self.evidence["stage"] = "parent_group_preparation"
            self.evidence["parent_limits"] = self.group.create()
            self.evidence["stage"] = "exact_artifact_load"
            self.evidence["loaded"] = {role: load(self.store, getattr(self.artifacts, role)) for role in ROLES}
            self.runtime = ArtifactRuntime(self.directory, self.spec.operation_id, self.group, self.artifacts,
                {role: item["actual_image_id"] for role, item in self.evidence["loaded"].items()})
            self.evidence["stage"] = "database_preparation"
            self.runtime.prepare()
            self.runtime.create("postgres")
            self.runtime.start("postgres")
            self.runtime.wait_database()
            self.runtime.sql("CREATE ROLE reference_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD '"
                             + self.runtime.app_password + "';")
            self._initialize_data(reset=False)
            self.evidence["stage"] = "application_readiness"
            for role in ("backend", "frontend"):
                self.runtime.create(role)
                self.runtime.start(role)
            return self._ready()
        except Exception:
            self._transition("failed")
            raise

    def _initialize_data(self, *, reset: bool):
        self._gate()
        if reset:
            self.runtime.sql("DROP SCHEMA public CASCADE; CREATE SCHEMA public AUTHORIZATION reference_owner;")
        self.runtime.migrate()
        self.runtime.sql("GRANT CONNECT ON DATABASE reference_notes TO reference_app; "
            "GRANT USAGE ON SCHEMA public TO reference_app; "
            "GRANT SELECT,INSERT,UPDATE,DELETE ON notes TO reference_app; "
            "GRANT SELECT ON alembic_version TO reference_app; "
            "GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO reference_app; "
            "INSERT INTO notes(title,body,created_at,updated_at) VALUES "
            "('CloudHelm synthetic dataset r1','Synthetic data only','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z');")
        observed = self.runtime.sql("SELECT version_num FROM alembic_version;").stdout.decode("utf-8").strip()
        auth = self.runtime.sql("SELECT count(*) = 0 FROM pg_hba_file_rules WHERE error IS NOT NULL OR auth_method = 'trust';").stdout.strip()
        role = self.runtime.sql("SELECT NOT (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication) "
                                "FROM pg_roles WHERE rolname='reference_app';").stdout.strip()
        seed = self.runtime.sql("SELECT count(*) FROM notes WHERE title='CloudHelm synthetic dataset r1' "
                               "AND body='Synthetic data only';").stdout.strip()
        if observed != MIGRATION_REVISION or auth != b"t" or role != b"t" or seed != b"1":
            raise ProbeFailure("artifact_environment_data_or_authentication_mismatch")
        self.migration_observed = observed
        self.data_generation += 1
        self.evidence["data"].append({"revision": self.spec.data_revision, "generation": self.data_generation,
            "migration_revision": observed, "reset": reset, "synthetic_seed_verified": True,
            "trust_authentication_absent": True, "application_role_unprivileged": True})

    def _ready(self):
        self._gate()
        self.runtime.wait_ready()
        self.evidence["runtime"] = {role: self.runtime.observe(role) for role in ROLES}
        self.evidence["parent_limits"] = self.group.observe()
        return self._transition("ready")

    def suspend(self):
        if self.state != "ready":
            raise ProbeFailure("artifact_environment_suspend_requires_ready")
        self._transition("preparing")
        for role in ("frontend", "backend", "postgres"):
            self.evidence["stop_confirmations"].append(self.runtime.stop(role))
        self.evidence["suspended_storage"] = self.admission.observe().model_dump(mode="json")
        return self._transition("suspended")

    def resume(self):
        if self.state != "suspended":
            raise ProbeFailure("artifact_environment_resume_requires_suspended")
        self._gate()
        for role in ROLES:
            if metadata(self.runtime.containers[role], self.spec.operation_id)["State"]["Running"]:
                raise ProbeFailure("artifact_environment_resume_found_running_process")
        self._transition("preparing")
        try:
            self.runtime.start("postgres")
            self.runtime.wait_database()
            head = self.runtime.sql("SELECT version_num FROM alembic_version;").stdout.decode("utf-8").strip()
            if head != MIGRATION_REVISION:
                raise ProbeFailure("artifact_environment_resume_data_revision_mismatch")
            for role in ("backend", "frontend"):
                self.runtime.start(role)
            return self._ready()
        except Exception:
            self._transition("failed")
            raise

    def reset_data(self):
        if self.state != "ready":
            raise ProbeFailure("artifact_environment_reset_requires_ready")
        self._transition("preparing")
        try:
            for role in ("frontend", "backend"):
                self.evidence["stop_confirmations"].append(self.runtime.stop(role))
            self._initialize_data(reset=True)
            for role in ("backend", "frontend"):
                self.runtime.start(role)
            return self._ready()
        except Exception:
            self._transition("failed")
            raise

    def http_check(self, phase: str) -> dict:
        self._gate()
        allowed_state = "preparing" if phase == "not-ready" else "ready"
        if self.state != allowed_state or phase not in {"baseline", "seed", "verify-persisted", "not-ready"}:
            raise ProbeFailure("artifact_environment_http_phase_invalid")
        assets = load_reference_assets(self.repository)
        if assets.bundle_digest != self.spec.acceptance_bundle_digest:
            raise ProbeFailure("artifact_environment_acceptance_assets_changed")
        path = ACCEPTANCE_ROOT + "verify_http.py"
        with _seed_root(self.repository) as root:
            script = _read_public_file(root, path)
        if "sha256:" + hashlib.sha256(script).hexdigest() != dict(assets.file_digests)[path]:
            raise ProbeFailure("artifact_environment_http_method_changed")
        # Execute the exact verified bytes via stdin; no candidate path is imported.
        result = command([sys.executable, "-I", "-B", "-", "--base-url", self.runtime.entrance,
                          "--phase", phase], input_bytes=script, timeout=90, required=False)
        try:
            report = json.loads(result.stdout)
        except (ValueError, UnicodeError):
            raise ProbeFailure("artifact_environment_http_result_invalid") from None
        if (result.returncode or report.get("passed") is not True
                or report.get("method_revision") != assets.method_revision or report.get("phase") != phase):
            raise ProbeFailure("artifact_environment_independent_http_failed")
        self.evidence["http"].append(report)
        return report

    def verify_reference_http(self) -> list[dict]:
        """Independent original-byte assertions plus bounded physical fault setup."""
        self.http_check("baseline")
        self.http_check("seed")
        self._transition("preparing")
        self.evidence["stop_confirmations"].append(self.runtime.stop("backend"))
        self.runtime.start("backend")
        self._ready()
        self.http_check("verify-persisted")
        self._transition("preparing")
        self.evidence["stop_confirmations"].append(self.runtime.stop("postgres"))
        self.http_check("not-ready")
        self.runtime.start("postgres")
        self.runtime.wait_database()
        self._ready()
        return list(self.evidence["http"])

    def verify_lifecycle(self) -> dict:
        """One narrow development run; no browser or human acceptance is produced."""
        self.evidence["stage"] = "independent_http_and_restart_fault_checks"
        self.verify_reference_http()
        self.evidence["stage"] = "suspend_resume"
        self.suspend()
        self.resume()
        self.http_check("baseline")
        self.evidence["stage"] = "versioned_data_reset"
        self.reset_data()
        self.http_check("baseline")
        self.evidence["stage"] = "verified"
        return {"artifact_set": self.artifacts.model_dump(mode="json"), "evidence": self.evidence,
                "observation": self.observation().model_dump(mode="json"), "human_acceptance": None,
                "support_scope": "controlled_wsl_artifact_http_environment_only"}

    def dispose(self):
        self.state = "preparing"
        if self.runtime is not None:
            for role in ("frontend", "backend", "migrate", "postgres"):
                if role in self.runtime.containers:
                    self.evidence["stop_confirmations"].append(self.runtime.remove(role))
            if self.runtime.network_id is not None:
                engine("DELETE", "/networks/" + self.runtime.network_id, expected=(204,))
                self.runtime.network_id = None
            secret = self.directory / ".secrets"
            for name in ("owner", "owner.pgpass"):
                (secret / name).unlink(missing_ok=True)
            self.runtime.owner_password = self.runtime.app_password = ""
            self.runtime.close_mount_descriptors()
        self.evidence["parent_stop"] = self.group.dispose()
        self.evidence["retained_storage"] = self.admission.observe().model_dump(mode="json")
        if self.store is not None:
            self.store.close()
            self.store = None
        return self._transition("disposed")
