"""Development evidence for fixed wheel acquisition and a fresh offline uv sync."""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import time
from dataclasses import replace
from datetime import datetime, timezone
from importlib import import_module
from pathlib import Path
from uuid import uuid4

from scripts.p1.probe_runner import save_json

policy = import_module("services.dev-runner.policy")
toolchain = import_module("services.dev-runner.toolchain")
images = import_module("services.dev-runner.offline_images")
dependencies = import_module("services.dev-runner.python_dependencies")
runtime = import_module("services.dev-runner.python_dependency_runtime")
ROOT = Path(__file__).resolve().parents[2]
METHOD_FILES = (
    "services/dev-runner/python_dependencies.py", "services/dev-runner/python_dependency_runtime.py",
    "infra/p1/reference-build/backend.offline.Dockerfile", "scripts/p1/check_python_dependencies.py",
    "services/dev-runner/offline_images.py", "services/dev-runner/offline_image_runtime.py",
    "services/dev-runner/capabilities.py", "services/dev-runner/policy.py",
    "services/dev-runner/toolchain.py", "scripts/p1/probe_runner.py",
)


def rejection_checks(seed: Path, inputs) -> dict[str, bool]:
    results = {}
    changes = {"lock": {"lock_digest": "sha256:" + "0" * 64},
        "platform": {"platform": "linux/arm64"}, "python": {"python": "3.12.12"},
        "uv": {"uv": "0.11.30"}, "project": {"project": "other-project"},
        "trust_domain": {"trust_domain": "other-domain"},
        "install_parameters": {"install_arguments": inputs.install_arguments + ("--compile-bytecode",)}}
    for name, change in changes.items():
        changed = replace(inputs, **change)
        if changed.cache_key == inputs.cache_key:
            raise toolchain.ProbeFailure("python_dependency_cache_identity_not_distinct")
        try:
            dependencies.verify_seed(seed, changed)
        except toolchain.ProbeFailure as failure:
            if failure.category != "python_dependency_input_not_supported":
                raise
            results[name + "_rejects_old_seed"] = True
        else:
            raise toolchain.ProbeFailure("python_dependency_incompatible_seed_accepted")
    for name, endpoint in (("sdist", "https://files.pythonhosted.org/packages/source.tar.gz"),
                           ("foreign_host", "https://example.com/dependency.whl")):
        try:
            dependencies._download(dependencies.UV_WHEEL | {"url": endpoint},
                                   seed / "must-not-be-created", time.monotonic())
        except toolchain.ProbeFailure as failure:
            if failure.category != "python_dependency_download_descriptor_rejected":
                raise
            results[name + "_rejected_before_io"] = True
        else:
            raise toolchain.ProbeFailure("python_dependency_untrusted_download_accepted")
    return results


def _cleanup_layout(directory: Path) -> dict:
    layout = directory / "base-layout"
    if directory.parent != runtime.RUNTIME_ROOT or not directory.name.startswith("python-dependencies-"):
        raise toolchain.ProbeFailure("python_dependency_cleanup_path_not_registered")
    released = sum(item.stat().st_size for item in layout.rglob("*") if item.is_file())
    for item in [layout, *layout.rglob("*")]:
        if item.is_symlink():
            raise toolchain.ProbeFailure("python_dependency_cleanup_symlink_rejected")
        if item.is_dir():
            item.chmod(0o700)
    shutil.rmtree(layout)
    return {"source_layout_removed": not layout.exists(), "source_layout_removed_logical_bytes": released}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true", help="Acquire and verify the fixed seed; do not start a builder")
    options = parser.parse_args()
    policy.acquire_probe_lock()
    toolchain.private_directory(runtime.RUNTIME_ROOT)
    operation_id = "python-dependencies-" + uuid4().hex
    directory = runtime.RUNTIME_ROOT / operation_id
    toolchain.private_directory(directory)
    started = datetime.now(timezone.utc)
    inputs = dependencies.PythonDependencyInput()
    report = {"method_revision": runtime.METHOD, "operation_id": operation_id,
        "started_at": started.isoformat(), "input_state": "development_worktree",
        "input_identity": json.loads(dependencies._encoded(dependencies.asdict(inputs))),
        "derived_preparation": {"variant": "linux-amd64-wheelhouse-r1",
            "project_digest": dependencies._digest(dependencies.derived_project()),
            "environment": dependencies.DERIVED_ENVIRONMENT, "lock_arguments": dependencies.LOCK_ARGUMENTS},
        "environment": {"kernel": platform.release(), "executor": "ubuntu-24-04-wsl-maintenance",
                        "platform": "linux/amd64", "python": platform.python_version()},
        "method_files": {name: toolchain.file_digest(ROOT / name) for name in METHOD_FILES},
        "support_scope": "fixed_reference_python_wheels_and_offline_dependency_imports_only",
        "failures": [], "all_required_verified": False, "prepare_only": options.prepare_only}
    probe = None
    try:
        print(json.dumps({"stage": "fixed_wheel_acquisition", "operation_id": operation_id}), flush=True)
        report["seed"] = dependencies.prepare_seed(inputs)
        seed = Path(report["seed"]["path"])
        report["cache_reuse"] = dependencies.prepare_seed(inputs)
        if not report["cache_reuse"]["cache_hit"] or report["cache_reuse"]["downloaded_bytes"]:
            raise toolchain.ProbeFailure("python_dependency_seed_reuse_not_observed")
        report["rejections"] = rejection_checks(seed, inputs)
        save_json(directory / "registered-input.json", report)
        if not options.prepare_only:
            client = toolchain.DockerClient.create(directory)
            report["toolchain"] = toolchain.ensure_toolchain(client)
            report["source"] = images.prepare_python_layout(client, directory)
            report["execution_started_at"] = datetime.now(timezone.utc).isoformat()
            probe = runtime.PythonDependencyRuntime(client, operation_id, directory,
                report["toolchain"]["reference"], time.monotonic(), seed)
            print(json.dumps({"stage": "offline_dependency_install", "operation_id": operation_id}), flush=True)
            probe.create()
            report["limits"] = probe.observe_boundary()
            report["installation"] = probe.install(report["source"]["manifest"]["digest"],
                                                  report["seed"]["distributions"])
    except toolchain.ProbeFailure as failure:
        report["failures"].append({"category": failure.category, "diagnostic": failure.diagnostic,
                                   "detail": failure.detail})
    except Exception as failure:
        report["failures"].append({"category": "python_dependency_exception_" + type(failure).__name__})
    finally:
        if probe is not None:
            try:
                report["stop"] = probe.stopped_resources()
                if report["stop"]["process_resources_released"] and (directory / "base-layout").exists():
                    report["cleanup"] = _cleanup_layout(directory)
            except toolchain.ProbeFailure as failure:
                report["failures"].append({"category": failure.category, "detail": failure.detail})
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        report["seed_preparation_verified"] = (report.get("cache_reuse", {}).get("cache_hit") is True
            and bool(report.get("rejections")) and all(report["rejections"].values()))
        report["all_required_verified"] = (not options.prepare_only and not report["failures"]
            and "installation" in report and report.get("stop", {}).get("process_resources_released") is True)
        retained = [item for item in directory.rglob("*") if item.is_file()]
        report["retention"] = {"seed_logical_bytes": report.get("seed", {}).get("retained_bytes", 0),
            "operation_input_logical_bytes_before_report": sum(item.stat().st_size for item in retained),
            "operation_input_allocated_bytes_before_report": sum(item.stat().st_blocks * 512 for item in retained),
            "source_layout_remaining": (directory / "base-layout").exists(),
            "source_export_remaining": (directory / "source-export.tar").exists(),
            "host_retained_content_has_physical_quota": False}
        save_json(directory / "report.json", report)
        print(json.dumps({"report_path": str(directory / "report.json"), **report}, ensure_ascii=False), flush=True)
    return 0 if (report["seed_preparation_verified"] if options.prepare_only else report["all_required_verified"]) else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except toolchain.ProbeFailure as failure:
        print(json.dumps({"all_required_verified": False, "failure": failure.category,
                          "diagnostic": failure.diagnostic, "detail": failure.detail}), flush=True)
        raise SystemExit(1) from None
