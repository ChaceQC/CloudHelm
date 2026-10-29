"""Fixed notes candidate preview inside an already admitted resource group.

The caller owns the business authorization, storage lifetime and resource release.
This is an internal Runner API, not a client-supplied Docker or upstream interface.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat

from modules.artifacts.content_store import ArtifactStore
from modules.delivery.queries import _loaded_content_matches
from packages.contracts.p1.build_records import BuildView, build_artifact_record, build_digest
from packages.contracts.p1.development_environment import POSTGRES_MANIFEST
from packages.contracts.p1.workspace_git import content_digest
from packages.contracts.p2.candidates import FixedCandidateRecord

from .artifact_environment_images import load
from .backend_build_inputs import SOURCE_DIGESTS
from .candidate_preview_docker import CandidatePreviewDocker
from .candidate_preview_journal import read, write
from .development_storage import StorageAdmission
from .engineering_definition import _controlled
from .resource_context import current_group
from .resource_development import PREVIEW_ENVELOPE
from .toolchain import ProbeFailure

PROFILE = "notes-fixed-candidate-preview-r1"

class CandidatePreview:
    """One immutable candidate and one stable physical execution identity."""

    def __init__(self, *, operation_id: str, candidate: FixedCandidateRecord, build: BuildView,
                 store: ArtifactStore, admission: StorageAdmission, start_gate=None):
        group = current_group()
        if (not re.fullmatch(r"candidate-preview-[0-9a-f]{32}", operation_id)
                or type(candidate) is not FixedCandidateRecord or type(build) is not BuildView
                or type(store) is not ArtifactStore or type(admission) is not StorageAdmission or group is None):
            raise ProbeFailure("candidate_preview_trusted_inputs_required")
        resources = group.request.resources
        if (resources.request_vector != PREVIEW_ENVELOPE or resources.accounted_vector != PREVIEW_ENVELOPE
                or resources.hard_limits != PREVIEW_ENVELOPE
                or group.registration.storage.storage_id != admission.snapshot.registration.storage_id
                or group.registration.storage.instance_revision != admission.snapshot.registration.instance_revision
                or admission.snapshot.purpose != "workspace"):
            raise ProbeFailure("candidate_preview_resource_binding_mismatch")
        record, content, execution = build.record, build.content, build.execution
        if (build.state != "succeeded" or not build.content_verified or content is None or execution is None
                or not content.applicable or not execution.applicable
                or record.operation_id != candidate.build_operation_id or record.task_id != candidate.task_id
                or record.project_id != candidate.project_id
                or record.fixed_inputs.source_input_set_ref != candidate.source_input_set_ref
                or content.operation_id != record.operation_id or content.build_input_digest != record.build_input_digest
                or execution.observation.operation_id != record.operation_id
                or execution.observation.request_digest != record.request_digest
                or execution.observation.build_input_digest != record.build_input_digest
                or execution.observation.closure != "ended_reconciled" or execution.observation.exit_code != 0
                or not _loaded_content_matches(content, execution.observation)):
            raise ProbeFailure("candidate_preview_successful_build_required")
        refs = candidate.input_set.references
        build_refs = [item for item in refs if item.kind == "build" and item.object_id == record.build_run_id]
        artifacts = {item.role: item for item in content.artifacts}
        runtime = record.fixed_inputs.definition.runtime_contract_ref
        migration_inputs = {item.path.removeprefix("backend/"): item.digest
                            for item in record.fixed_inputs.definition.migrations}
        migrations = {name: digest for name, digest in SOURCE_DIGESTS.items() if name.startswith("migrations/")}
        evidence = {item.scope: item for item in candidate.evidence}
        if (len(build_refs) != 1 or build_refs[0].authority != "delivery"
                or build_refs[0].digest != build_digest(record)
                or any(item not in refs for item in record.fixed_inputs.input_set.references)
                or evidence["build_execution"].subject_ref != build_refs[0]
                or evidence["build_execution"].evidence_ref.digest != build_digest(execution)
                or evidence["artifact_content"].subject_ref != build_refs[0]
                or evidence["artifact_content"].evidence_ref.digest != build_digest(content)
                or set(artifacts) != {"frontend", "backend", "postgres"}
                or any(item.content_ref not in refs for item in artifacts.values())
                or artifacts["postgres"].manifest_digest != POSTGRES_MANIFEST
                or runtime.object_id != "reference-local-artifact-verification"
                or runtime.revision != "p1-reference-runtime-r1" or runtime.authority != "runner"
                or runtime.digest != content_digest(_controlled("runtime.compose.yaml"))
                or migration_inputs != migrations):
            raise ProbeFailure("candidate_preview_fixed_profile_or_inputs_unsupported")
        self.operation_id, self.candidate, self.build = operation_id, candidate, build
        self.store, self.admission, self.group, self.artifacts = store, admission, group, artifacts
        self.start_gate = start_gate
        self.directory = admission.directory / ("candidate-preview-" + hashlib.sha256(operation_id.encode()).hexdigest()[:32])
        self.binding = {"profile": PROFILE, "operation_id": operation_id, "candidate_id": candidate.candidate_id,
                        "input_set_digest": candidate.input_set.set_digest, "build_input_digest": record.build_input_digest,
                        "resource_binding": group.binding,
                        "artifacts": {role: item.model_dump(mode="json") for role, item in sorted(artifacts.items())}}
        self.binding_digest = content_digest(json.dumps(self.binding, sort_keys=True, separators=(",", ":")).encode())
        self.runtime = CandidatePreviewDocker(operation_id, self.binding_digest, group, self.directory, artifacts)

    def _gate(self):
        if self.group.stopped or not callable(self.start_gate):
            raise ProbeFailure("candidate_preview_current_authorization_required")
        self.start_gate()
        self.admission.observe()
        self.group.observe()

    def _check_directory(self):
        self.admission.observe()
        info = self.directory.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077
                or info.st_dev != os.fstat(self.admission.directory_fd).st_dev):
            raise ProbeFailure("candidate_preview_directory_invalid")
        if read(self.directory / "binding.json") != self.binding:
            raise ProbeFailure("candidate_preview_operation_identity_conflict")

    def prepare(self):
        self._gate()
        try:
            os.mkdir(self.directory, 0o700)
        except FileExistsError:
            raise ProbeFailure("candidate_preview_existing_operation_requires_reconciliation") from None
        write(self.directory / "binding.json", self.binding)
        write(self.directory / "execution.json", {"binding_digest": self.binding_digest,
              "attempted_roles": [], "stop_facts": {}})
        self._gate()
        receipts = {}
        for role, item in self.artifacts.items():
            receipt = self.store.query(item.storage_id)
            if build_artifact_record(role, receipt) != item:
                raise ProbeFailure("candidate_preview_artifact_content_changed")
            receipts[role] = receipt
        for role, receipt in receipts.items():
            self._gate()
            load(self.store, receipt)
        self.runtime.prepare(self._gate)
        return self.runtime.wait_ready(self._gate) | self._identity()

    def _identity(self):
        return {"operation_id": self.operation_id, "candidate_id": self.candidate.candidate_id,
                "input_set_digest": self.candidate.input_set.set_digest, "profile": PROFILE,
                "build_operation_id": self.build.record.operation_id,
                "artifact_manifests": {role: item.manifest_digest for role, item in self.artifacts.items()}}

    def observe(self):
        self._check_directory()
        marker = self.directory / "stopped.json"
        if marker.exists():
            result = read(marker)
            if result.get("binding_digest") != self.binding_digest:
                raise ProbeFailure("candidate_preview_stop_identity_conflict")
            return self._identity() | result
        if self.group.stopped:
            raise ProbeFailure("candidate_preview_physical_observation_unavailable")
        return self._identity() | self.runtime.observe()

    def stop(self):
        self._check_directory()
        marker = self.directory / "stopped.json"
        if marker.exists():
            return self.observe()
        if self.group.stopped:
            raise ProbeFailure("candidate_preview_physical_stop_unavailable")
        facts = self.runtime.stop()
        for name in ("database", "secrets", "docker-public"):
            target = self.directory / name
            if target.exists():
                if target.is_symlink() or not target.is_dir():
                    raise ProbeFailure("candidate_preview_cleanup_directory_invalid")
                shutil.rmtree(target)
        self.admission.observe()
        result = {"binding_digest": self.binding_digest, "state": "stopped", "stop_facts": facts,
                  "data_removed": True, "backing_pool_retained": True, "resource_release_confirmed": False}
        write(marker, result)
        return self._identity() | result
