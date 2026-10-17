"""Fixed backend source -> offline rootless BuildKit -> independently checked OCI."""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import tarfile
import time
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path, PurePosixPath
from uuid import uuid4

from modules.artifacts.content_store import ArtifactStore
from modules.artifacts.errors import ArtifactContentError
from scripts.p1.check_python_dependencies import rejection_checks
from scripts.p1.probe_runner import save_json

policy = import_module("services.dev-runner.policy")
toolchain = import_module("services.dev-runner.toolchain")
images = import_module("services.dev-runner.offline_images")
inputs = import_module("services.dev-runner.backend_build_inputs")
boundary = import_module("services.dev-runner.backend_build_boundary")
runtime = import_module("services.dev-runner.backend_build_runtime")
dependencies = import_module("services.dev-runner.python_dependencies")
ROOT = Path(__file__).resolve().parents[2]
METHOD_FILES = (
    "services/dev-runner/backend_build_inputs.py", "services/dev-runner/backend_build_boundary.py",
    "services/dev-runner/backend_build_runtime.py", "infra/p1/reference-build/backend.offline.Dockerfile",
    "scripts/p1/check_backend_build.py", "scripts/p1/check_python_dependencies.py",
    "services/dev-runner/python_dependencies.py", "services/dev-runner/python_dependency_runtime.py",
    "services/dev-runner/offline_images.py", "services/dev-runner/offline_image_runtime.py",
    "services/dev-runner/capabilities.py", "services/dev-runner/policy.py", "services/dev-runner/toolchain.py",
    "scripts/p1/probe_runner.py", "modules/artifacts/content_store.py", "modules/artifacts/content_files.py",
    "modules/artifacts/oci_archive.py", "packages/contracts/p1/build_artifacts.py",
)


def source_refusals(source: dict) -> list[str]:
    checks = [("changed_source", source | {"app/main.py": source["app/main.py"] + b"\n"}),
              ("extra_source", source | {".env": b"rejected"}),
              ("missing_source", {name: raw for name, raw in source.items() if name != "uv.lock"})]
    result = []
    for name, changed in checks:
        try:
            inputs.verify_source(changed)
        except toolchain.ProbeFailure:
            result.append(name)
        else:
            raise toolchain.ProbeFailure("backend_source_refusal_not_observed")
    return result


def _layer_files(archive, receipt, expected: dict) -> dict[str, bytes]:
    actual = {}
    for layer in receipt.layers:
        if layer.media_type != "application/vnd.oci.image.layer.v1.tar+gzip":
            raise toolchain.ProbeFailure("backend_output_layer_not_gzip")
        updates, removals = {}, []
        with archive.extractfile("blobs/sha256/" + layer.digest[7:]) as blob:
            with tarfile.open(fileobj=blob, mode="r|gz") as files:
                for member in files:
                    name = member.name.removeprefix("./")
                    path = PurePosixPath(name)
                    if path.name.startswith(".wh."):
                        removed = str(path.parent) if path.name == ".wh..wh..opq" else str(path.with_name(path.name[4:]))
                        removals.extend(key for key in expected if key == removed or key.startswith(removed + "/"))
                    if name not in expected:
                        continue
                    if not member.isfile() or member.size > inputs.MAX_SOURCE_FILE_BYTES:
                        raise toolchain.ProbeFailure("backend_runtime_file_unsupported")
                    with files.extractfile(member) as source:
                        updates[name] = source.read(inputs.MAX_SOURCE_FILE_BYTES + 1)
        for name in removals:
            actual.pop(name, None)
        actual.update(updates)
    return actual


def image_files(store, receipt, runtime_checks: dict) -> dict:
    expected = {"app/" + name: inputs.SOURCE_DIGESTS[name] for name in inputs.RUNTIME_SOURCE}
    expected["backend-result.json"] = None
    with store.open_archive(receipt.storage_id) as stream, tarfile.open(fileobj=stream, mode="r:") as archive:
        configuration = json.load(archive.extractfile("blobs/sha256/" + receipt.config.digest[7:]))["config"]
        if (configuration.get("WorkingDir") != "/app"
                or configuration.get("Cmd") != ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
                or configuration.get("Entrypoint")
                or any(value.startswith("DATABASE_URL=") for value in configuration.get("Env", []))):
            raise toolchain.ProbeFailure("backend_runtime_configuration_mismatch")
        actual = _layer_files(archive, receipt, expected)
    if set(actual) != set(expected) or json.loads(actual["backend-result.json"]) != runtime_checks:
        raise toolchain.ProbeFailure("backend_runtime_evidence_or_members_mismatch")
    digests = {name: inputs.digest(raw) for name, raw in actual.items() if name != "backend-result.json"}
    if digests != {name: value for name, value in expected.items() if value is not None}:
        raise toolchain.ProbeFailure("backend_runtime_source_content_mismatch")
    return {"uvicorn_entrypoint_verified": True, "verified_runtime_source": digests,
        "runtime_checks_match_archive": True, "gzip_layers": len(receipt.layers), "attestations": False}


def _cleanup_layout(directory: Path) -> dict:
    if directory.parent != boundary.RUNTIME_ROOT or not directory.name.startswith("backend-build-"):
        raise toolchain.ProbeFailure("backend_cleanup_path_not_registered")
    layout = directory / "base-layout"
    files = [layout, *layout.rglob("*")]
    if any(item.is_symlink() for item in files):
        raise toolchain.ProbeFailure("backend_cleanup_symlink_rejected")
    size = sum(item.stat().st_size for item in files if item.is_file())
    for item in files:
        if item.is_dir():
            item.chmod(0o700)
    shutil.rmtree(layout)
    return {"source_layout_removed": not layout.exists(), "source_layout_removed_logical_bytes": size}


def run_build(probe, report, source_files, directory) -> None:
    manifest = report["base"]["manifest"]["digest"]
    primary = inputs.build_input_key(report["source"], report["seed"], manifest)
    changed = inputs.build_input_key(report["source"], report["seed"], manifest, generation="cache-invalidation-probe")
    report["output"] = probe.build(manifest, input_key=primary)
    if report["output"]["runtime_check_cached"] or len(report["output"]["runtime_checks"]) != 1:
        raise toolchain.ProbeFailure("backend_first_build_execution_not_observed")
    root = directory / "content-store"
    toolchain.private_directory(root)
    with ArtifactStore(root) as store:
        receipt = store.publish(report["output"]["archive_path"],
                                expected_archive_digest=report["output"]["archive_digest"])
        if (receipt.manifest.digest != report["output"]["exporter_manifest_digest"]
                or receipt.config.digest != report["output"]["exporter_config_digest"]
                or store.query(receipt.storage_id) != receipt):
            raise toolchain.ProbeFailure("backend_exporter_and_artifact_identity_mismatch")
        report["runtime_image_contents"] = image_files(store, receipt, report["output"]["runtime_checks"][0])
        report["artifact"] = receipt.model_dump(mode="json")
    Path(report["output"]["archive_path"]).unlink()
    report["cache_hit"] = probe.build(manifest, input_key=primary, collect=False)
    if (not report["cache_hit"]["runtime_check_cached"]
            or report["cache_hit"]["exporter_manifest_digest"] != receipt.manifest.digest):
        raise toolchain.ProbeFailure("backend_build_cache_hit_not_verified")
    report["cache_invalidation"] = probe.build(manifest, input_key=changed, collect=False)
    if (primary == changed or report["cache_invalidation"]["runtime_check_cached"]
            or report["cache_invalidation"]["exporter_config_digest"] == receipt.config.digest):
        raise toolchain.ProbeFailure("backend_build_cache_invalidation_not_verified")
    report["dependencies"] = probe.dependency_evidence(manifest, report["seed"]["distributions"], source_files=source_files)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--static-only", action="store_true", help="Verify local source/seed and context without Docker")
    parser.add_argument("--source-root", type=Path, default=inputs.BACKEND)
    parser.add_argument("--source-ref", default="fixed-reference-development")
    args = parser.parse_args()
    policy.acquire_probe_lock()
    toolchain.private_directory(boundary.RUNTIME_ROOT)
    operation_id = "backend-build-" + uuid4().hex
    directory = boundary.RUNTIME_ROOT / operation_id
    toolchain.private_directory(directory)
    report = {"method_revision": boundary.METHOD, "operation_id": operation_id,
        "started_at": datetime.now(UTC).isoformat(), "input_kind": "development_worktree",
        "environment": {"kernel": platform.release(), "executor": "ubuntu-24-04-wsl-maintenance",
                        "platform": "linux/amd64"},
        "method_files": {name: toolchain.file_digest(ROOT / name) for name in METHOD_FILES},
        "support_scope": "fixed_notes_backend_offline_oci_and_builder_imports_development_only",
        "failures": [], "all_required_verified": False, "static_only": args.static_only}
    probe = None
    try:
        source_files = inputs.reference_inputs(args.source_root)
        dependency_input = dependencies.PythonDependencyInput()
        if args.static_only:
            report["seed"] = dependencies.verify_seed(dependencies.CACHE_ROOT / dependency_input.cache_key,
                dependency_input, source_files=source_files) | {"cache_hit": True, "downloaded_bytes": 0}
        else:
            report["seed"] = dependencies.prepare_seed(dependency_input, source_files=source_files)
        seed = Path(report["seed"]["path"])
        report["source"] = inputs.prepare_context(directory, source_files, source_ref=args.source_ref,
                                                 distributions=report["seed"]["distributions"])
        report["source_refusals"] = source_refusals(source_files)
        report["dependency_refusals"] = rejection_checks(seed, dependency_input)
        if not args.static_only:
            client = toolchain.DockerClient.create(directory)
            print(json.dumps({"stage": "fixed_python_base", "operation_id": operation_id}), flush=True)
            report["toolchain"] = toolchain.ensure_toolchain(client)
            report["base"] = images.prepare_python_layout(client, directory)
            report["primary_build_input_key"] = inputs.build_input_key(
                report["source"], report["seed"], report["base"]["manifest"]["digest"])
            report["execution_started_at"] = datetime.now(UTC).isoformat()
            save_json(directory / "registered-input.json", report)
            probe = runtime.BackendBuildRuntime(client, operation_id, directory,
                report["toolchain"]["reference"], time.monotonic(), seed)
            print(json.dumps({"stage": "offline_backend_build", "operation_id": operation_id}), flush=True)
            probe.create()
            report["limits"] = probe.observe_boundary()
            run_build(probe, report, source_files, directory)
        else:
            save_json(directory / "registered-input.json", report)
        after = dependencies.verify_seed(seed, dependency_input, source_files=source_files)
        if after != {key: value for key, value in report["seed"].items() if key not in {"cache_hit", "downloaded_bytes"}}:
            raise toolchain.ProbeFailure("backend_seed_changed_after_build")
        if report["method_files"] != {name: toolchain.file_digest(ROOT / name) for name in METHOD_FILES}:
            raise toolchain.ProbeFailure("backend_method_changed_during_execution")
    except toolchain.ProbeFailure as failure:
        report["failures"].append({"category": failure.category, "diagnostic": failure.diagnostic, "detail": failure.detail})
    except ArtifactContentError as failure:
        report["failures"].append({"category": str(failure)})
    except Exception as failure:
        report["failures"].append({"category": "backend_exception_" + type(failure).__name__})
    finally:
        if probe is not None and probe.container_id is not None:
            try:
                report["stop"] = probe.stopped_resources()
                if report["stop"]["process_resources_released"] and (directory / "base-layout").exists():
                    report["cleanup"] = _cleanup_layout(directory)
            except toolchain.ProbeFailure as failure:
                report["failures"].append({"category": failure.category, "detail": failure.detail})
        report["finished_at"] = datetime.now(UTC).isoformat()
        report["static_preparation_verified"] = not report["failures"] and "source" in report
        report["all_required_verified"] = (not args.static_only and not report["failures"] and "dependencies" in report
            and "artifact" in report and report.get("stop", {}).get("process_resources_released") is True)
        report["retention"] = {"external_readonly_seed_bytes": report.get("seed", {}).get("retained_bytes", 0),
            "published_archive_bytes": report.get("artifact", {}).get("archive_bytes", 0),
            "collected_archive_remaining": (directory / "image.oci.tar").exists(),
            "source_layout_remaining": (directory / "base-layout").exists(),
            "source_export_remaining": (directory / "source-export.tar").exists(),
            "host_retained_content_has_physical_quota": False}
        save_json(directory / "report.json", report)
        print(json.dumps({"report_path": str(directory / "report.json"),
            **{key: report[key] for key in ("all_required_verified", "static_preparation_verified", "failures", "retention")},
            "artifact": report.get("artifact"), "stop": report.get("stop")}, ensure_ascii=False), flush=True)
    verified = report["static_preparation_verified"] if args.static_only else report["all_required_verified"]
    return 0 if verified else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except toolchain.ProbeFailure as failure:
        print(json.dumps({"all_required_verified": False, "failure": failure.category}), flush=True)
        raise SystemExit(1) from None
