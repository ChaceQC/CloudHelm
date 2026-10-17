"""One fixed notes frontend -> offline rootless BuildKit -> verified Nginx OCI."""

from __future__ import annotations

import argparse
import json
import platform
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from uuid import uuid4

from modules.artifacts.content_store import ArtifactStore
from modules.artifacts.errors import ArtifactContentError
from packages.contracts.p1.npm_cache import NpmDownloadSpec
from scripts.p1.check_npm_downloads import checks as cache_checks
from scripts.p1.probe_runner import save_json

policy = import_module("services.dev-runner.policy")
toolchain = import_module("services.dev-runner.toolchain")
inputs = import_module("services.dev-runner.frontend_build_inputs")
boundary = import_module("services.dev-runner.frontend_build_boundary")
runtime = import_module("services.dev-runner.frontend_build_runtime")
downloads = import_module("services.dev-runner.npm_downloads")
ROOT = Path(__file__).resolve().parents[2]
METHOD_FILES = (
    "services/dev-runner/frontend_images.py", "services/dev-runner/frontend_build_inputs.py",
    "services/dev-runner/frontend_build_boundary.py", "services/dev-runner/frontend_build_runtime.py",
    "infra/p1/reference-build/frontend.offline.Dockerfile", "scripts/p1/check_frontend_build.py",
    "services/dev-runner/npm_downloads.py", "services/dev-runner/npm_download_io.py",
    "packages/contracts/p1/npm_cache.py", "scripts/p1/check_npm_downloads.py",
    "services/dev-runner/offline_images.py",
    "services/dev-runner/offline_image_runtime.py", "services/dev-runner/capabilities.py",
    "services/dev-runner/policy.py", "services/dev-runner/toolchain.py", "scripts/p1/probe_runner.py",
    "modules/artifacts/content_store.py", "modules/artifacts/content_files.py",
    "modules/artifacts/oci_archive.py", "packages/contracts/p1/build_artifacts.py",
    "pyproject.toml", "uv.lock",
)


def refusals(store, spec, source) -> list[str]:
    changed = source | {"src/main.tsx": source["src/main.tsx"] + b"\n"}
    checks = [
        ("changed_source", lambda: inputs.verify_source(changed)),
        ("extra_source", lambda: inputs.verify_source(source | {".env": b"rejected"})),
        ("different_source_manifest", lambda: inputs.verify_source(source, "sha256:" + "0" * 64)),
        ("different_cache_key", lambda: store.verify(spec, "npm-seed-" + "0" * 64)),
        ("different_manifest", lambda: store.verify(spec, expected_manifest_digest="sha256:" + "0" * 64)),
        ("different_install_options", lambda: store.verify(spec.model_copy(update={"install_options": ("--offline",)}))),
    ]
    passed = []
    for name, check in checks:
        try:
            check()
        except (toolchain.ProbeFailure, downloads.NpmDownloadError):
            passed.append(name)
        else:
            raise toolchain.ProbeFailure("frontend_required_refusal_not_observed")
    return passed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed-root", type=Path, required=True)
    parser.add_argument("--seed-manifest-digest", required=True)
    parser.add_argument("--source-root", type=Path, default=inputs.FRONTEND,
                        help="Controlled frontend subtree; may be an independent fixed candidate view.")
    args = parser.parse_args()
    policy.acquire_probe_lock()
    toolchain.private_directory(boundary.RUNTIME_ROOT)
    operation_id = "frontend-build-" + uuid4().hex
    directory = boundary.RUNTIME_ROOT / operation_id
    toolchain.private_directory(directory)
    client = toolchain.DockerClient.create(directory)
    report = {"method_revision": boundary.METHOD, "operation_id": operation_id,
        "started_at": datetime.now(UTC).isoformat(), "input_kind": "development_worktree",
        "environment": {"kernel": platform.release(), "executor": "ubuntu-24-04-wsl-maintenance",
                        "platform": "linux/amd64", "python": platform.python_version()},
        "method_files": {name: toolchain.file_digest(ROOT / name) for name in METHOD_FILES},
        "support_scope": "fixed_notes_frontend_offline_nginx_oci_development_only",
        "failures": [], "all_required_verified": False}
    try:
        source = inputs.reference_inputs(args.source_root)
        report["source"] = inputs.verify_source(source)
        report["source"]["recipe_digest"] = toolchain.file_digest(inputs.RECIPE)
        report["source_api"] = "explicit_candidate_bytes"
        spec = NpmDownloadSpec(project_id="reference-notes", trust_domain="controlled-development")
        with downloads.NpmDownloadStore(args.seed_root) as seeds:
            seed = seeds.verify(spec, expected_manifest_digest=args.seed_manifest_digest)
            report["seed"] = seed.model_dump(mode="json")
            report["refusals"] = refusals(seeds, spec, source)
            report["cache_checks"] = cache_checks(seeds, spec, seed, args.seed_root, args.source_root)
        save_json(directory / "registered-input.json", report)
        report["execution_started_at"] = datetime.now(UTC).isoformat()
        print(json.dumps({"stage": "fixed_bases_then_offline_frontend", "operation_id": operation_id}), flush=True)
        content_root = directory / "content-store"
        toolchain.private_directory(content_root)
        with ArtifactStore(content_root) as store:
            report.update(runtime.build_frontend(client, operation_id, directory, args.seed_root,
                args.seed_manifest_digest, source_inputs=source,
                expected_source_manifest_digest=report["source"]["manifest_digest"],
                content_store=store, seed_spec=spec))
        if (inputs.verify_source(inputs.reference_inputs(args.source_root)) != {key: report["source"][key]
                for key in ("files", "manifest_digest", "file_count", "bytes")}
                or report["method_files"] != {name: toolchain.file_digest(ROOT / name) for name in METHOD_FILES}):
            raise toolchain.ProbeFailure("frontend_inputs_changed_after_build")
    except toolchain.ProbeFailure as failure:
        report["failures"].append({"category": failure.category, "diagnostic": failure.diagnostic,
                                   "detail": failure.detail})
    except (ArtifactContentError, downloads.NpmDownloadError) as failure:
        report["failures"].append({"category": str(failure)})
    except Exception as failure:
        report["failures"].append({"category": "frontend_exception_" + type(failure).__name__})
    finally:
        report["finished_at"] = datetime.now(UTC).isoformat()
        report["all_required_verified"] = (not report["failures"] and "artifact" in report
            and report.get("stop", {}).get("process_resources_released") is True)
        report["retention"] = {"source_layout_bytes": sum(item["layout_bytes"]
                for item in report.get("bases", {}).values()),
            "external_readonly_seed_bytes": report.get("seed", {}).get("seed_bytes", 0),
            "published_archive_bytes": report.get("content_receipt", {}).get("archive_bytes", 0),
            "collected_archive_remaining": (directory / "image.oci.tar").exists(),
            "source_exports_remaining": any(directory.glob("*-export.tar")),
            "host_retained_content_has_physical_quota": False}
        save_json(directory / "report.json", report)
        print(json.dumps({"report_path": str(directory / "report.json"),
            "all_required_verified": report["all_required_verified"], "failures": report["failures"],
            "artifact": report.get("artifact"), "stop": report.get("stop"),
            "retention": report["retention"]}, ensure_ascii=False), flush=True)
    return 0 if report["all_required_verified"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except toolchain.ProbeFailure as failure:
        print(json.dumps({"all_required_verified": False, "failure": failure.category}), flush=True)
        raise SystemExit(1) from None
