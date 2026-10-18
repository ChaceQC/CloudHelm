"""Fixed backend source -> offline rootless BuildKit -> independently checked OCI."""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import time
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
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
cache_fixture = import_module("scripts.p1.backend_cache_fixture")
ROOT = Path(__file__).resolve().parents[2]
METHOD_REVISION = "p1-backend-source-input-cache-r2"
A_CONTEXT_NAME = "candidate-a"
METHOD_FILES = (
    "services/dev-runner/backend_build_inputs.py", "services/dev-runner/backend_build_boundary.py",
    "services/dev-runner/backend_build_runtime.py", "infra/p1/reference-build/backend.offline.Dockerfile",
    "scripts/p1/check_backend_build.py", "scripts/p1/backend_cache_fixture.py",
    "scripts/p1/check_python_dependencies.py",
    "services/dev-runner/python_dependencies.py", "services/dev-runner/python_dependency_runtime.py",
    "services/dev-runner/offline_images.py", "services/dev-runner/offline_image_runtime.py",
    "services/dev-runner/capabilities.py", "services/dev-runner/policy.py", "services/dev-runner/toolchain.py",
    "scripts/p1/probe_runner.py", "modules/artifacts/content_store.py", "modules/artifacts/content_files.py",
    "modules/artifacts/oci_archive.py", "packages/contracts/p1/build_artifacts.py",
)


def source_refusals(source: dict, fixture_source: dict | None = None) -> list[str]:
    checks = [("changed_source", source | {"app/main.py": source["app/main.py"] + b"\n"}),
              ("extra_source", source | {".env": b"rejected"}),
              ("missing_source", {name: raw for name, raw in source.items() if name != "uv.lock"})]
    if fixture_source is not None:
        checks.append(("allowlisted_cache_fixture", fixture_source))
    result = []
    for name, changed in checks:
        try:
            inputs.verify_source(changed)
        except toolchain.ProbeFailure:
            result.append(name)
        else:
            raise toolchain.ProbeFailure("backend_source_refusal_not_observed")
    return result


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


def _expect_same_builder(probe, identity: str) -> None:
    if cache_fixture.builder_identity(probe) != identity:
        raise toolchain.ProbeFailure("backend_private_builder_changed_during_sequence")


def _build_first_a(probe, store, report, manifest: str, input_key: str,
                   source_files: dict, builder_identity: str):
    output = probe.build(manifest, input_key=input_key, context_name=A_CONTEXT_NAME)
    report["output"] = output
    if output["runtime_check_cached"] or len(output["runtime_checks"]) != 1:
        raise toolchain.ProbeFailure("backend_first_build_execution_not_observed")
    receipt, contents = cache_fixture.publish_output(store, output, expected_source_files=source_files)
    report["runtime_image_contents"] = contents
    report["artifact"] = receipt.model_dump(mode="json")
    Path(output["archive_path"]).unlink()
    _expect_same_builder(probe, builder_identity)
    return receipt


def _build_repeat_a(probe, report, manifest: str, input_key: str, receipt, builder_identity: str) -> dict:
    output = probe.build(manifest, input_key=input_key, collect=False, context_name=A_CONTEXT_NAME)
    report["cache_hit"] = output
    if (not output["runtime_check_cached"] or output["input_key"] != input_key
            or output["exporter_manifest_digest"] != receipt.manifest.digest
            or output["exporter_config_digest"] != receipt.config.digest):
        raise toolchain.ProbeFailure("backend_build_cache_hit_not_verified")
    _expect_same_builder(probe, builder_identity)
    return output


def _build_b(probe, store, report, manifest: str, input_key: str, source_files: dict,
             receipt_a, directory: Path, builder_identity: str) -> tuple[object, dict]:
    output = probe.build(manifest, input_key=input_key, context_name=cache_fixture.CONTEXT_NAME)
    report["cache_invalidation"] = output
    if (output["input_key"] != input_key or output["runtime_check_cached"]
            or len(output["runtime_checks"]) != 1
            or output["exporter_manifest_digest"] == receipt_a.manifest.digest
            or output["exporter_config_digest"] == receipt_a.config.digest):
        raise toolchain.ProbeFailure("backend_build_cache_input_change_not_verified")
    _expect_same_builder(probe, builder_identity)
    receipt_b, contents = cache_fixture.publish_output(store, output, expected_source_files=source_files,
                                          fixture_runtime_root=directory)
    main_digest = contents["verified_runtime_source"]["app/app/main.py"]
    if (receipt_b.manifest.digest == receipt_a.manifest.digest
            or receipt_b.config.digest == receipt_a.config.digest
            or main_digest != report["cache_fixture_b"]["changed_source"]["sha256"]):
        raise toolchain.ProbeFailure("backend_build_fixture_artifact_change_not_verified")
    report["cache_invalidation_artifact"] = receipt_b.model_dump(mode="json")
    report["cache_invalidation_runtime_image_contents"] = contents
    Path(output["archive_path"]).unlink()
    return receipt_b, contents


def run_build(probe, report, source_files, fixture_source_files, directory) -> None:
    manifest = report["base"]["manifest"]["digest"]
    primary = inputs.build_input_key(report["source"], report["seed"], manifest)
    changed = inputs.build_input_key(report["source_b"], report["seed"], manifest)
    if (primary == changed or report["source"]["source_ref"] == report["source_b"]["source_ref"]
            or report["source"]["manifest_digest"] == report["source_b"]["manifest_digest"]):
        raise toolchain.ProbeFailure("backend_cache_fixture_identity_not_independent")
    builder_identity = cache_fixture.builder_identity(probe)
    root = directory / "content-store"
    toolchain.private_directory(root)
    with ArtifactStore(root) as store:
        receipt_a = _build_first_a(probe, store, report, manifest, primary, source_files, builder_identity)
        repeat_a = _build_repeat_a(probe, report, manifest, primary, receipt_a, builder_identity)
        receipt_b, b_contents = _build_b(probe, store, report, manifest, changed, fixture_source_files,
                                         receipt_a, directory, builder_identity)
    report["cache_sequence"] = {
        "order": ["A", "A", "B"], "builder_boundary_revision": boundary.METHOD,
        "builder_cache_policy": "one_private_builder_per_operation",
        "builder_identity_sha256": builder_identity, "all_builds_used_same_private_builder": True,
        "development_dependency_cache_relation": "separate_private_wheel_seed_cache; not the builder cache under measurement",
        "candidate_a": {"source_ref": report["source"]["source_ref"],
            "source_manifest_digest": report["source"]["manifest_digest"], "build_input_key": primary},
        "candidate_b": {"fixture_id": cache_fixture.FIXTURE_ID,
            "source_ref": report["source_b"]["source_ref"],
            "source_manifest_digest": report["source_b"]["manifest_digest"], "build_input_key": changed},
        "a_first_executed": not report["output"]["runtime_check_cached"],
        "a_repeat_cached": repeat_a["runtime_check_cached"],
        "a_repeat_oci_identity_equal": (repeat_a["exporter_manifest_digest"] == receipt_a.manifest.digest
            and repeat_a["exporter_config_digest"] == receipt_a.config.digest),
        "b_source_manifest_changed": report["source"]["manifest_digest"] != report["source_b"]["manifest_digest"],
        "b_input_key_changed": primary != changed,
        "b_runtime_step_executed": not report["cache_invalidation"]["runtime_check_cached"],
        "b_oci_identity_changed": (receipt_b.manifest.digest != receipt_a.manifest.digest
            and receipt_b.config.digest != receipt_a.config.digest),
        "b_source_digest_verified_in_oci": (
            b_contents["verified_runtime_source"]["app/app/main.py"]
            == report["cache_fixture_b"]["changed_source"]["sha256"]),
        "b_route_function_called_from_oci_source": b_contents["cache_fixture_runtime_check"]["route_endpoint_called"],
    }
    report["dependencies"] = probe.dependency_evidence(manifest, report["seed"]["distributions"],
        source_files=source_files, context_name=A_CONTEXT_NAME)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--static-only", action="store_true", help="Verify local source/seed and context without Docker")
    parser.add_argument("--source-root", type=Path, default=inputs.BACKEND)
    parser.add_argument("--source-ref", default="fixed-reference-development")
    parser.add_argument("--input-set", help="Bind this method to a committed P1.2 candidate")
    args = parser.parse_args()
    policy.acquire_probe_lock()
    toolchain.private_directory(boundary.RUNTIME_ROOT)
    operation_id = "backend-build-" + uuid4().hex
    directory = boundary.RUNTIME_ROOT / operation_id
    toolchain.private_directory(directory)
    report = {"method_revision": METHOD_REVISION, "builder_boundary_revision": boundary.METHOD,
        "operation_id": operation_id,
        "started_at": datetime.now(UTC).isoformat(),
        "input_kind": "fixed_candidate" if args.input_set else "development_worktree",
        "human_acceptance": None,
        "environment": {"kernel": platform.release(), "executor": "ubuntu-24-04-wsl-maintenance",
                        "platform": "linux/amd64"},
        "method_files": {name: toolchain.file_digest(ROOT / name) for name in METHOD_FILES},
        "support_scope": "fixed_notes_backend_offline_oci_and_builder_imports_development_only",
        "cache_method_contract": {
            "sequence": ["A", "A", "B"],
            "builder_cache_policy": "one_private_builder_per_operation",
            "development_dependency_cache_relation": "separate_private_wheel_seed_cache; not the builder cache under measurement",
            "fixture_id": cache_fixture.FIXTURE_ID,
            "fixture_source_ref": cache_fixture.SOURCE_REF,
            "fixture_route": cache_fixture.ROUTE_PATH,
        },
        "failures": [], "all_required_verified": False, "static_only": args.static_only}
    probe = None
    try:
        if args.input_set:
            from scripts.p1.engineering_manifest import verify

            report["input_before"] = verify(args.input_set)
        source_files = inputs.reference_inputs(args.source_root)
        fixture_source_files = cache_fixture.create_candidate(source_files)
        dependency_input = dependencies.PythonDependencyInput()
        if args.static_only:
            report["seed"] = dependencies.verify_seed(dependencies.CACHE_ROOT / dependency_input.cache_key,
                dependency_input, source_files=source_files) | {"cache_hit": True, "downloaded_bytes": 0}
        else:
            report["seed"] = dependencies.prepare_seed(dependency_input, source_files=source_files)
        seed = Path(report["seed"]["path"])
        report["source"] = inputs.prepare_context(directory, source_files, source_ref=args.source_ref,
            distributions=report["seed"]["distributions"], context_name=A_CONTEXT_NAME, seal_bundle=False)
        report["cache_fixture_b"] = cache_fixture.summary(source_files, fixture_source_files)
        report["source_b"] = cache_fixture.prepare_context(directory, source_files,
            fixture_source_files, distributions=report["seed"]["distributions"])
        if report["source"]["source_ref"] == report["source_b"]["source_ref"]:
            raise toolchain.ProbeFailure("backend_cache_fixture_source_refs_not_independent")
        inputs.seal_context_bundle(directory)
        report["source_refusals"] = source_refusals(source_files, fixture_source_files)
        if args.static_only:
            report["cache_fixture_static_route_check"] = cache_fixture.invoke_route(
                {name: fixture_source_files[name] for name in inputs.RUNTIME_SOURCE}, directory,
                source_origin="fixed_fixture_candidate_prebuild")
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
            run_build(probe, report, source_files, fixture_source_files, directory)
        else:
            save_json(directory / "registered-input.json", report)
        after = dependencies.verify_seed(seed, dependency_input, source_files=source_files)
        if after != {key: value for key, value in report["seed"].items() if key not in {"cache_hit", "downloaded_bytes"}}:
            raise toolchain.ProbeFailure("backend_seed_changed_after_build")
        if report["method_files"] != {name: toolchain.file_digest(ROOT / name) for name in METHOD_FILES}:
            raise toolchain.ProbeFailure("backend_method_changed_during_execution")
        if args.input_set:
            report["input_after"] = verify(args.input_set)
            if report["input_before"] != report["input_after"]:
                raise toolchain.ProbeFailure("backend_fixed_candidate_changed_during_execution")
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
            and "artifact" in report and "cache_invalidation_artifact" in report and "cache_sequence" in report
            and report["cache_sequence"].get("a_repeat_cached") is True
            and report["cache_sequence"].get("a_repeat_oci_identity_equal") is True
            and report["cache_sequence"].get("b_source_manifest_changed") is True
            and report["cache_sequence"].get("b_input_key_changed") is True
            and report["cache_sequence"].get("b_runtime_step_executed") is True
            and report["cache_sequence"].get("b_oci_identity_changed") is True
            and report["cache_sequence"].get("b_source_digest_verified_in_oci") is True
            and report["cache_sequence"].get("b_route_function_called_from_oci_source") is True
            and report.get("stop", {}).get("process_resources_released") is True)
        report["retention"] = {"external_readonly_seed_bytes": report.get("seed", {}).get("retained_bytes", 0),
            "published_archive_bytes": report.get("artifact", {}).get("archive_bytes", 0),
            "collected_archive_remaining": (directory / "image.oci.tar").exists(),
            "source_layout_remaining": (directory / "base-layout").exists(),
            "source_context_bundle_remaining": (directory / "context").exists(),
            "source_context_variants": [A_CONTEXT_NAME, cache_fixture.CONTEXT_NAME],
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
