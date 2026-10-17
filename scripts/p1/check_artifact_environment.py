"""Narrow contract guards or explicit three-artifact local environment validation."""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from importlib import import_module
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from modules.artifacts.content_store import ArtifactStore
from modules.projects.reference_assets import load_reference_assets
from packages.contracts.p0.engineering_contracts import EngineeringRef, InputSet, input_set_digest
from packages.contracts.p1.build_artifacts import ArtifactContent, OciDescriptor, OCI_CONFIG, OCI_MANIFEST, artifact_content_ref
from packages.contracts.p1.development_environment import (
    ArtifactEnvironmentObservation, ArtifactEnvironmentSpec, EnvironmentArtifactSet, POSTGRES_REFERENCE,
)
from packages.contracts.p1.development_storage import DevelopmentStorageRef
from scripts.p1.probe_runner import save_json

environment = import_module("services.dev-runner.artifact_environment")
storage = import_module("services.dev-runner.development_storage")
toolchain = import_module("services.dev-runner.toolchain")
docker_runtime = import_module("services.dev-runner.artifact_environment_docker")
ROOT = Path(__file__).resolve().parents[2]
METHOD_FILES = ("packages/contracts/p1/development_environment.py", "scripts/p1/check_artifact_environment.py",
    "services/dev-runner/artifact_environment.py", "services/dev-runner/artifact_environment_docker.py",
    "services/dev-runner/artifact_environment_images.py", "services/dev-runner/artifact_environment_runtime.py",
    "services/dev-runner/artifact_environment_proxy.py")


def _reference(kind, identity, digest):
    return EngineeringRef(kind=kind, object_id=identity, revision="r1", authority="controlled-wsl-maintenance",
                          digest=digest, digest_algorithm="sha256")


def contract_checks() -> dict:
    def rejected(action):
        try:
            action()
        except (ValidationError, toolchain.ProbeFailure):
            return
        raise RuntimeError("environment_contract_rejection_not_observed")

    digest = "sha256:" + "1" * 64
    reference = DevelopmentStorageRef(storage_id="dev-storage-" + "1" * 32, instance_revision="2" * 32, purpose="workspace")
    spec = ArtifactEnvironmentSpec(operation_id="artifact-env-" + "3" * 32, source_revision="4" * 40,
        input_set_ref=_reference("input_set", "environment-guards", digest), storage_ref=reference,
        acceptance_bundle_digest=digest, deadline=datetime.now(timezone.utc) + timedelta(minutes=1))
    rejected(lambda: ArtifactEnvironmentSpec.model_validate(spec.model_dump() | {"data_revision": "unversioned"}))
    rejected(lambda: ArtifactEnvironmentSpec.model_validate(spec.model_dump() | {
        "storage_ref": reference.model_dump() | {"purpose": "cache"}}))
    rejected(lambda: ArtifactEnvironmentObservation(spec=spec, state="ready", observed_at=datetime.now(timezone.utc), data_generation=0))
    rejected(lambda: ArtifactEnvironmentObservation(spec=spec, state="suspended", observed_at=datetime.now(timezone.utc),
                                                    data_generation=1, running_roles=("postgres",)))
    receipt = ArtifactContent(storage_id="oci-" + "1" * 64, archive_digest=digest, archive_bytes=10240,
        manifest=OciDescriptor(media_type=OCI_MANIFEST, digest="sha256:" + "2" * 64, size_bytes=512),
        config=OciDescriptor(media_type=OCI_CONFIG, digest="sha256:" + "3" * 64, size_bytes=512),
        image_id="sha256:" + "3" * 64, layers=())
    rejected(lambda: EnvironmentArtifactSet(postgres=receipt, backend=receipt, frontend=receipt))
    rejected(lambda: environment.ArtifactEnvironment(None, spec, {}, ROOT))
    return {"result": "passed", "contract_rejections": 6, "runtime_executed": False,
            "support_scope": "artifact_environment_contract_guards_only"}


def _storage_ref(path: Path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        observed = os.fstat(descriptor)
        if (not stat.S_ISREG(observed.st_mode) or observed.st_uid != os.getuid()
                or observed.st_mode & 0o077 or observed.st_size > 4096):
            raise toolchain.ProbeFailure("artifact_environment_storage_reference_not_private")
        return DevelopmentStorageRef.model_validate_json(os.read(descriptor, 4097))
    finally:
        os.close(descriptor)


def run(admission, spec, applications, repository=ROOT, *, input_binding="development_worktree") -> dict:
    if input_binding not in {"development_worktree", "candidate_bound_build_input_set"}:
        raise toolchain.ProbeFailure("artifact_environment_input_binding_invalid")
    instance = environment.ArtifactEnvironment(admission, spec, applications, repository)
    report = {"result": "failed", "started_at": datetime.now(timezone.utc).isoformat(),
              "input_binding": input_binding, "human_acceptance": None}
    try:
        instance.prepare()
        report.update(instance.verify_lifecycle())
        report["result"] = "passed"
    except toolchain.ProbeFailure as failure:
        report["failure"] = failure.category
        report["diagnostic"] = failure.diagnostic
        if failure.category.startswith("artifact_environment_docker_"):
            report["public_runtime_error"] = failure.detail
    except Exception as failure:
        report["failure"] = "artifact_environment_" + type(failure).__name__
        trace = failure.__traceback__
        while trace.tb_next is not None:
            trace = trace.tb_next
        report["failure_location"] = Path(trace.tb_frame.f_code.co_filename).name + ":" + str(trace.tb_lineno)
    finally:
        instance.dispose()  # Unknown stop must raise and prevent a successful completion.
        report["disposed"] = instance.observation().model_dump(mode="json")
        report["evidence"] = instance.evidence
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        save_json(instance.directory / "report.json", report)
    return report | {"report_directory": str(instance.directory)}


def ephemeral_pool(arguments: list[str]) -> int:
    """Explicit root wrapper; preserve unknown resources instead of deleting them."""
    maintenance = import_module("services.dev-runner.development_storage_maintenance")
    docker_runtime.enter_docker_mount_namespace("scripts.p1.check_artifact_environment", arguments)
    created = maintenance.create_instance(4 * 1024**3, purposes=("workspace", "archive"))
    identity = created["storage_id"]
    operation = "artifact-env-" + uuid4().hex
    evidence = storage.ROOT / "evidence"
    reference_path = evidence / (identity + ".artifact-reference.json")
    save_json(reference_path, created["references"]["workspace"])
    os.chown(reference_path, storage.UID, storage.UID)
    child_arguments = [item for item in arguments if item != "--ephemeral-pool"]
    group = environment.EnvironmentGroup(identity)
    group.prepare_unit()
    result = subprocess.run(["/usr/sbin/runuser", "--user", "cloudhelm", "--", sys.executable, "-B", "-m",
        "scripts.p1.check_artifact_environment", *child_arguments, "--storage-ref", str(reference_path),
        "--operation-id", operation],
        stdin=subprocess.DEVNULL, capture_output=True, timeout=1000, check=False,
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PYTHONUTF8": "1"})
    try:
        summary = json.loads(result.stdout)
        report_path = Path(summary["report_directory"]) / "report.json"
        expected_root = storage.ROOT / identity / "data" / "workspace"
        if not report_path.is_relative_to(expected_root):
            raise ValueError("unexpected report location")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if report["disposed"]["state"] != "disposed" or report["disposed"]["running_roles"]:
            raise ValueError("environment stop not confirmed")
    except (OSError, ValueError, KeyError):
        summary = {"result": "unknown", "failure": "artifact_environment_child_stop_or_report_unconfirmed"}
        report = {"child_exit_code": result.returncode}
    wrapper = {"created": created, "environment": report, "summary": summary,
               "root_wrapper_observed_at": datetime.now(timezone.utc).isoformat()}
    # A retained report is outside the disposable filesystem and contains no secrets.
    retained = evidence / (identity + ".artifact-environment.json")
    if summary["result"] != "unknown":
        wrapper["parent_stop"] = group.dispose()
        wrapper["cleanup"] = maintenance.change_fixture(identity, "remove")
    else:
        wrapper["retained_for_reconciliation"] = True
    save_json(retained, wrapper)
    os.chown(retained, storage.UID, storage.UID)
    print(json.dumps({"result": summary["result"], "failure": summary.get("failure"),
        "diagnostic": report.get("diagnostic"),
        "retained_report": str(retained), "storage_id": identity,
        "pool_removed": "cleanup" in wrapper, "human_acceptance": None}), flush=True)
    return 0 if result.returncode == 0 and summary["result"] == "passed" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contracts-only", action="store_true")
    parser.add_argument("--ephemeral-pool", action="store_true")
    parser.add_argument("--storage-ref", type=Path)
    parser.add_argument("--source-revision")
    parser.add_argument("--operation-id")
    for role in ("backend", "frontend", "postgres"):
        parser.add_argument("--" + role + "-store", type=Path)
        parser.add_argument("--" + role + "-storage-id")
    args = parser.parse_args()
    if args.contracts_only:
        print(json.dumps(contract_checks()))
        return 0
    if args.ephemeral_pool:
        if args.storage_ref is not None:
            parser.error("ephemeral pool cannot override an existing storage reference")
        return ephemeral_pool(sys.argv[1:])
    if not all((args.storage_ref, args.source_revision, args.backend_store, args.backend_storage_id,
                args.frontend_store, args.frontend_storage_id)):
        parser.error("explicit storage registration, source revision and two trusted application stores are required")
    if bool(args.postgres_store) != bool(args.postgres_storage_id):
        parser.error("PostgreSQL store and storage identity must be supplied together")
    reference = _storage_ref(args.storage_ref)
    operation = args.operation_id or "artifact-env-" + uuid4().hex
    assets = load_reference_assets(ROOT)
    with ExitStack() as stack:
        applications = {}
        for role in ("backend", "frontend", "postgres"):
            path = getattr(args, role + "_store")
            if path:
                content = stack.enter_context(ArtifactStore(path))
                applications[role] = (content, content.query(getattr(args, role + "_storage_id")))
        refs = tuple(artifact_content_ref(receipt) for _, receipt in applications.values()) + tuple(
            _reference("method", name.replace("/", ":"), toolchain.file_digest(ROOT / name)) for name in METHOD_FILES)
        refs += (_reference("acceptance_assets", "reference-r1", assets.bundle_digest),)
        if "postgres" not in applications:
            refs += (_reference("artifact", "fixed-postgres-dependency", POSTGRES_REFERENCE.rsplit("@", 1)[1]),)
        inputs = InputSet(input_set_id=operation + "-input", references=refs, set_digest=input_set_digest(refs))
        spec = ArtifactEnvironmentSpec(operation_id=operation, source_revision=args.source_revision,
            storage_ref=reference, input_set_ref=_reference("input_set", inputs.input_set_id, inputs.set_digest),
            acceptance_bundle_digest=assets.bundle_digest, deadline=datetime.now(timezone.utc) + timedelta(minutes=15))
        with storage.DevelopmentStorage(reference.storage_id).admit_ref(reference, requested_bytes=2 * 1024**3) as admission:
            report = run(admission, spec, applications)
            save_json(Path(report["report_directory"]) / "input-set.json", inputs.model_dump(mode="json"))
    print(json.dumps({"result": report["result"], "report_directory": report["report_directory"],
                      "failure": report.get("failure"), "human_acceptance": None}))
    return 0 if report["result"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
