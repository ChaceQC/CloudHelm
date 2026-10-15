"""Fixed Python base -> offline rootless BuildKit -> single-image OCI archive."""

from __future__ import annotations

import json
import platform
import time
from datetime import datetime, timezone
from importlib import import_module
from pathlib import Path
from uuid import uuid4

from modules.artifacts.content_store import ArtifactStore
from modules.artifacts.errors import ArtifactContentError
from scripts.p1.probe_runner import save_json

policy = import_module("services.dev-runner.policy")
toolchain = import_module("services.dev-runner.toolchain")
images = import_module("services.dev-runner.offline_images")
runtime = import_module("services.dev-runner.offline_image_runtime")
ROOT = Path(__file__).resolve().parents[2]
METHOD_FILES = (
    "services/dev-runner/offline_images.py", "services/dev-runner/offline_image_runtime.py",
    "scripts/p1/probe_offline_image.py", "services/dev-runner/capabilities.py",
    "services/dev-runner/policy.py", "services/dev-runner/toolchain.py", "scripts/p1/probe_runner.py",
    "modules/artifacts/content_store.py", "modules/artifacts/content_files.py",
    "modules/artifacts/oci_archive.py", "packages/contracts/p1/build_artifacts.py",
)


def main() -> int:
    policy.acquire_probe_lock()
    toolchain.private_directory(runtime.RUNTIME_ROOT)
    operation_id = "offline-image-probe-" + uuid4().hex
    directory = runtime.RUNTIME_ROOT / operation_id
    toolchain.private_directory(directory)
    client = toolchain.DockerClient.create(directory)
    started = datetime.now(timezone.utc)
    report = {"method_revision": runtime.METHOD, "operation_id": operation_id,
        "started_at": started.isoformat(), "environment": {"kernel": platform.release(),
        "executor": "ubuntu-24-04-wsl-maintenance", "platform": "linux/amd64"},
        "method_files": {name: toolchain.file_digest(ROOT / name) for name in METHOD_FILES},
        "support_scope": "fixed_python_base_offline_import_export_development_only",
        "failures": [], "all_required_verified": False}
    probe = None
    try:
        print(json.dumps({"stage": "fixed_public_source", "operation_id": operation_id}), flush=True)
        report["toolchain"] = toolchain.ensure_toolchain(client)
        report["source"] = images.prepare_python_layout(client, directory)
        save_json(directory / "registered-input.json", report)
        report["execution_started_at"] = datetime.now(timezone.utc).isoformat()
        probe = runtime.OfflineImageRuntime(client, operation_id, directory,
                                           report["toolchain"]["reference"], time.monotonic())
        print(json.dumps({"stage": "offline_rootless_build", "operation_id": operation_id}), flush=True)
        probe.create()
        report["limits"] = probe.observe_boundary()
        report["output"] = probe.export_image(report["source"]["manifest"]["digest"])
        content_root = directory / "content-store"
        toolchain.private_directory(content_root)
        with ArtifactStore(content_root) as store:
            receipt = store.publish(report["output"]["archive_path"],
                                    expected_archive_digest=report["output"]["archive_digest"])
            if (receipt.manifest.digest != report["output"]["exporter_manifest_digest"]
                    or receipt.config.digest != report["output"]["exporter_config_digest"]):
                raise toolchain.ProbeFailure("offline_exporter_and_archive_identity_mismatch")
            if store.query(receipt.storage_id) != receipt:
                raise toolchain.ProbeFailure("offline_published_content_query_mismatch")
            report["artifact"] = receipt.model_dump(mode="json")
    except toolchain.ProbeFailure as failure:
        report["failures"].append({"category": failure.category, "diagnostic": failure.diagnostic,
                                   "detail": failure.detail})
    except ArtifactContentError as failure:
        report["failures"].append({"category": str(failure)})
    except Exception as failure:
        report["failures"].append({"category": "offline_exception_" + type(failure).__name__})
    finally:
        if probe is not None:
            try:
                report["stop"] = probe.stopped_resources()
            except toolchain.ProbeFailure as failure:
                report["failures"].append({"category": failure.category, "detail": failure.detail})
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        report["all_required_verified"] = (not report["failures"] and "artifact" in report
            and report.get("stop", {}).get("process_resources_released") is True)
        report["retention"] = {"source_layout_bytes": report.get("source", {}).get("layout_bytes", 0),
            "collected_archive_bytes": report.get("output", {}).get("archive_bytes", 0),
            "published_archive_bytes": report.get("artifact", {}).get("archive_bytes", 0),
            "source_export_remaining": (directory / "source-export.tar").exists(),
            "host_retained_content_has_physical_quota": False}
        save_json(directory / "report.json", report)
        print(json.dumps({"report_path": str(directory / "report.json"), **report}, ensure_ascii=False), flush=True)
    return 0 if report["all_required_verified"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except toolchain.ProbeFailure as failure:
        print(json.dumps({"all_required_verified": False, "failure": failure.category,
                          "diagnostic": failure.diagnostic, "detail": failure.detail}), flush=True)
        raise SystemExit(1) from None
