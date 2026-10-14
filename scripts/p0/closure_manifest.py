"""Freeze or verify the public P0 closure inputs; never read runtime configuration."""

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from scripts.p0.decision_manifest import HISTORICAL_MANIFESTS, PUBLIC_FILES as DECISION_FILES

ROOT = Path(__file__).resolve().parents[2]
HISTORY = (*HISTORICAL_MANIFESTS, "docs/acceptance/p0/input-set-decisions-r1.json")
PUBLIC_FILES = tuple(sorted({
    *DECISION_FILES, *HISTORY,
    "scripts/p0/closure_manifest.py", "scripts/p0/topology_snapshot.py",
    "scripts/p0/reference_applicability.py", "scripts/p0/compose_probe.py",
    "scripts/p0/remote_probe.py", "packages/contracts/p0/remote-plan.schema.json",
    "docs/decisions/p0/s2413-development-envelope.md",
    "docs/decisions/p0/reference-applicability.md",
    "docs/acceptance/p0/topology-s2413-r2.md",
    "docs/acceptance/p0/remaining-scope-review-r1.md",
    "docs/acceptance/p0/validation-decisions-r1.json",
    "docs/development/p0-seams.md",
}))


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT, stderr=subprocess.PIPE)


def commit_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("SOURCE_COMMIT_REQUIRED")
    return value


def public_path(name: str) -> Path:
    path = ROOT / name
    if (Path(name).is_absolute() or ".." in Path(name).parts
            or not path.resolve().is_relative_to(ROOT)
            or any(part.is_symlink() for part in (path, *path.parents) if part != ROOT)):
        raise ValueError("PUBLIC_INPUT_PATH_REJECTED")
    return path


def files_at(source_commit: str) -> list[dict[str, str]]:
    source_commit = commit_id(source_commit)
    result = []
    for name in PUBLIC_FILES:
        data = public_path(name).read_bytes()
        data.decode("utf-8")
        if data != git("show", f"{source_commit}:{name}"):
            raise ValueError(f"PUBLIC_INPUT_DIFFERS_FROM_COMMIT: {name}")
        result.append({"path": name, "sha256": hashlib.sha256(data).hexdigest()})
    return result


def historical_bindings() -> list[dict]:
    results = []
    for name in HISTORY:
        original = json.loads(public_path(name).read_text(encoding="utf-8"))
        source = original.get("source_commit")
        if source is None:
            results.append({"input_set": name, "source_commit": None,
                            "status": "source_commit_unrecorded_manifest_preserved",
                            "recorded_file_count": len(original["sha256"])})
            continue
        source = commit_id(source)
        for item in original["files"]:
            public_path(item["path"])
            recorded = git("show", f"{source}:{item['path']}")
            if hashlib.sha256(recorded).hexdigest() != item["sha256"]:
                raise ValueError(f"HISTORICAL_SOURCE_HASH_MISMATCH: {name}")
        results.append({"input_set": name, "source_commit": source,
                        "status": "matches_historical_source",
                        "file_count": len(original["files"])})
    return results


def freeze(revision: str) -> dict:
    if not re.fullmatch(r"r[1-9][0-9]*", revision):
        raise ValueError("INVALID_INPUT_SET_REVISION")
    destination = ROOT / f"docs/acceptance/p0/input-set-closure-{revision}.json"
    if destination.exists():
        raise ValueError("INPUT_SET_ALREADY_EXISTS_USE_NEW_REVISION")
    source = git("rev-parse", "HEAD").decode("ascii").strip()
    return {"revision": f"p0-closure-input-set-{revision}",
            "method_revision": "p0-closure-binding-r1", "source_commit": source,
            "frozen_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "scope": "public closure methods, decisions, topology observations and cited historical inputs; no runtime state or secrets",
            "files": files_at(source)}


def verify(name: str) -> dict:
    if not re.fullmatch(r"docs/acceptance/p0/input-set-closure-r[1-9][0-9]*\.json", name):
        raise ValueError("EXPECTED_PUBLIC_CLOSURE_MANIFEST_PATH")
    manifest = json.loads(public_path(name).read_text(encoding="utf-8"))
    revision = Path(name).stem.removeprefix("input-set-closure-")
    if (manifest["revision"] != f"p0-closure-input-set-{revision}"
            or manifest["method_revision"] != "p0-closure-binding-r1"):
        raise ValueError("INPUT_SET_REVISION_MISMATCH")
    actual = files_at(manifest["source_commit"])
    if manifest["files"] != actual:
        raise ValueError("INPUT_SET_CONTENT_MISMATCH")
    return {"method_revision": "p0-closure-binding-r1", "input_set": name,
            "source_commit": manifest["source_commit"], "file_count": len(actual),
            "verified_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "matches": True, "historical_inputs": historical_bindings(),
            "scope": "public bytes and historical provenance only; no repeated SDK, database, model, deployment or human acceptance"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", default="r1")
    parser.add_argument("--verify")
    args = parser.parse_args()
    value = verify(args.verify) if args.verify else freeze(args.revision)
    print(json.dumps(value, ensure_ascii=False, indent=2))
