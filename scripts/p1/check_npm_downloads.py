"""One real seed acquisition and narrow cache checks; no npm/Docker/project code."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from packages.contracts.p1.npm_cache import NpmDownloadSpec

downloads = import_module("services.dev-runner.npm_downloads")
ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "examples/standalone-project/frontend"
RUNTIME = Path("/home/cloudhelm/.local/state/cloudhelm/npm-download-seed")
METHOD_FILES = ("packages/contracts/p1/npm_cache.py", "services/dev-runner/npm_download_io.py",
                "services/dev-runner/npm_downloads.py", "scripts/p1/check_npm_downloads.py",
                "modules/artifacts/content_files.py")


def require(value: bool, code: str) -> None:
    if not value:
        raise RuntimeError(code)


def rejected(call, code: str) -> None:
    try:
        call()
    except downloads.NpmDownloadError as error:
        require(str(error) == code, "npm_unexpected_rejection")
    else:
        raise RuntimeError("npm_expected_rejection_missing")


def checks(store, spec, receipt, cache: Path, frontend: Path = FRONTEND) -> dict:
    result = {}
    with patch.object(downloads, "RegistryDownloads", side_effect=RuntimeError("network_forbidden")):
        hit = store.prepare(spec, frontend)
    require(hit.cache_hit and hit.manifest_digest == receipt.manifest_digest, "npm_cache_hit_identity_changed")
    require(store.verify(spec, expected_manifest_digest=receipt.manifest_digest) == hit,
            "npm_seed_readback_changed")
    result["network_free_verified_cache_hit"] = True
    seed = cache / receipt.manifest.cache_id
    require(seed.stat().st_mode & 0o777 == 0o500, "npm_seed_directory_writable")
    require(all(item.stat().st_mode & 0o777 == 0o400 for item in seed.iterdir()),
            "npm_seed_file_writable")
    require(len(list(seed.iterdir())) == receipt.manifest.file_count, "npm_seed_file_count_wrong")
    require(sum(item.stat().st_size for item in seed.iterdir()) == receipt.seed_bytes,
            "npm_seed_retained_bytes_wrong")
    result["readonly_file_count_and_logical_bytes"] = True
    entry = min(receipt.manifest.tarballs, key=lambda item: item.bytes)
    target = seed / entry.filename
    original = target.read_bytes()
    try:
        target.chmod(0o600)
        target.write_bytes(bytes([original[0] ^ 1]) + original[1:])
        target.chmod(0o400)
        rejected(lambda: store.prepare(spec, frontend), "npm_cache_tarball_content_mismatch")
    finally:
        target.chmod(0o600)
        target.write_bytes(original)
        target.chmod(0o400)
    require(store.verify(spec).manifest_digest == receipt.manifest_digest, "npm_seed_restore_failed")
    result["tampered_tarball_rejected_then_restored"] = True
    changed = spec.model_copy(update={"project_id": "different-project"})
    rejected(lambda: store.verify(changed, receipt.manifest.cache_id), "npm_cache_key_mismatch")
    result["different_project_key_rejected"] = True
    for field, value in (("node_version", "22.0.0"), ("platform", "linux/arm64"),
                         ("lock_digest", "sha256:" + "0" * 64)):
        changed = spec.model_copy(update={field: value})
        rejected(lambda: store.verify(changed, receipt.manifest.cache_id), "npm_cache_spec_unsupported")
        result[field + "_mismatch_rejected"] = True
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, default=RUNTIME)
    arguments = parser.parse_args()
    arguments.runtime_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if arguments.runtime_root.lstat().st_mode & 0o077:
        raise RuntimeError("npm_check_runtime_must_be_private")
    run = arguments.runtime_root / ("npm-check-" + uuid4().hex)
    run.mkdir(mode=0o700)
    cache = run / "cache"
    cache.mkdir(mode=0o700)
    started = datetime.now(UTC)
    report = {"method_revision": "p1-npm-download-check-r1", "started_at": started.isoformat(),
        "input_status": "development_worktree", "environment": {"kernel": platform.release(),
        "machine": platform.machine(), "python": platform.python_version()},
        "method_files": {name: "sha256:" + hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                         for name in METHOD_FILES},
        "support_scope": "fixed_frontend_raw_tarball_seed_only", "all_required_verified": False}
    try:
        spec = NpmDownloadSpec(project_id="reference-notes", trust_domain="controlled-development")
        print(json.dumps({"stage": "fixed_npm_download", "run": str(run)}), flush=True)
        with downloads.NpmDownloadStore(cache) as store:
            receipt = store.prepare(spec, FRONTEND)
            report["receipt"] = receipt.model_dump(mode="json")
            report["checks"] = checks(store, spec, receipt, cache)
        report["seed_path"] = str(cache / receipt.manifest.cache_id)
        report["retention"] = {"seed_bytes": receipt.seed_bytes,
            "tarball_bytes": receipt.manifest.tarball_bytes, "file_count": receipt.manifest.file_count,
            "private_stage_remaining": any(item.name.startswith("npm-stage-") for item in cache.iterdir()),
            "host_physical_quota": False}
        report["all_required_verified"] = all(report["checks"].values())
    except Exception as error:
        report["failure"] = (str(error) if isinstance(error, downloads.NpmDownloadError)
                             else "npm_check_exception_" + type(error).__name__)
    report["finished_at"] = datetime.now(UTC).isoformat()
    raw = json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    fd = os.open(run / "report.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps({"report_path": str(run / "report.json"), "started_at": report["started_at"],
        "finished_at": report["finished_at"], "all_required_verified": report["all_required_verified"],
        "failure": report.get("failure"), "seed_path": report.get("seed_path"),
        "cache_id": report.get("receipt", {}).get("manifest", {}).get("cache_id"),
        "manifest_digest": report.get("receipt", {}).get("manifest_digest"),
        "retention": report.get("retention"), "checks": report.get("checks")}, ensure_ascii=False), flush=True)
    return 0 if report["all_required_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
