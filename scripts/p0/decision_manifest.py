"""Freeze or verify an explicit public P0.3 file set, without writing files."""

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_MODULES = (
    "decision_common", "engineering_contracts", "core_contracts", "delivery_contracts",
    "emergency_contracts", "identity_contracts", "migration_contracts",
    "resource_contracts", "task_control_contracts", "permit_contracts", "preview_contracts",
    "decision_schema",
)
CHECK_MODULES = (
    "core", "identity", "migrations", "resources", "task", "permits", "preview",
)
DECISION_DOCUMENTS = (
    "identity-permissions-migrations", "migration-contract", "resources-task-control",
    "task-control", "time-preview-access", "preview-access", "core-boundaries",
)
HISTORICAL_MANIFESTS = (
    "docs/acceptance/p0/input-set-r1.json",
    "docs/acceptance/p0/input-set-a01-r1.json",
    "docs/acceptance/p0/input-set-a02-r1.json",
    "docs/acceptance/reference/input-set-r1.json",
)
PUBLIC_FILES = tuple(sorted({
    ".python-version", "pyproject.toml", "uv.lock",
    "scripts/p0/decision_manifest.py", "scripts/p0/check_decisions.py",
    "docs/development/p0-decisions.md", "packages/contracts/p0/README.md",
    "docs/acceptance/support-matrix.md",
    "packages/contracts/p0/decisions-r1.schema.json",
    *(f"packages/contracts/p0/{name}.py" for name in CONTRACT_MODULES),
    *(f"scripts/p0/check_decision_{name}.py" for name in CHECK_MODULES),
    *(f"docs/decisions/p0/{name}.md" for name in DECISION_DOCUMENTS),
    "云舵 CloudHelm 毕设设计书 v4.7.md", "docs/design/README.md",
    "docs/design/01-domain-collaboration.md", "docs/design/02-execution-recovery.md",
    "docs/design/03-workspace-build-resources.md", "docs/design/04-release-deployment.md",
    "docs/design/05-security-sync-operations.md", "docs/design/06-implementation-validation.md",
    *(f"docs/acceptance/p0/SDK-0{number}.md" for number in range(1, 7)),
    "docs/acceptance/p0/A01.md", "docs/acceptance/p0/A02.md",
    "docs/acceptance/p0/compose-remote.md",
    "docs/decisions/p0/admitted-runtime.md", "docs/decisions/p0/component-baseline.md",
    "docs/decisions/p0/topology.md", "docs/implementation/reference-chain.md",
    "docs/implementation/reference-requirements-r1.md",
    "docs/acceptance/reference/validation-r1.md", *HISTORICAL_MANIFESTS,
}))


def _git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT)


def _files_at(source_commit: str) -> list[dict[str, str]]:
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("SOURCE_COMMIT_REQUIRED")
    files = []
    for name in PUBLIC_FILES:
        data = (ROOT / name).read_bytes()
        data.decode("utf-8")
        if data != _git("show", f"{source_commit}:{name}"):
            raise ValueError(f"PUBLIC_INPUT_DIFFERS_FROM_COMMIT: {name}")
        files.append({"path": name, "sha256": hashlib.sha256(data).hexdigest()})
    return files


def freeze(revision: str) -> dict:
    if not re.fullmatch(r"r[1-9][0-9]*", revision):
        raise ValueError("INVALID_INPUT_SET_REVISION")
    source_commit = _git("rev-parse", "HEAD").decode("ascii").strip()
    return {
        "revision": f"p0-decisions-input-set-{revision}",
        "protocol_revision": "p0-decisions-r1",
        "source_commit": source_commit,
        "frozen_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope": "public P0.3 contracts, decisions, method, locked dependencies and cited historical evidence",
        "files": _files_at(source_commit),
    }


def verify(path: str) -> dict:
    if not re.fullmatch(r"docs/acceptance/p0/input-set-decisions-r[1-9][0-9]*\.json", path):
        raise ValueError("EXPECTED_PUBLIC_DECISIONS_MANIFEST_PATH")
    manifest = json.loads((ROOT / path).read_text(encoding="utf-8"))
    expected_revision = "p0-decisions-input-set-" + Path(path).stem.removeprefix("input-set-decisions-")
    if manifest["revision"] != expected_revision or manifest["protocol_revision"] != "p0-decisions-r1":
        raise ValueError("INPUT_SET_PROTOCOL_MISMATCH")
    actual = _files_at(manifest["source_commit"])
    if manifest["files"] != actual:
        raise ValueError("INPUT_SET_CONTENT_MISMATCH")
    return {"input_set": path, "source_commit": manifest["source_commit"], "file_count": len(actual), "matches": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--revision", default="r1")
    parser.add_argument("--verify")
    arguments = parser.parse_args()
    result = verify(arguments.verify) if arguments.verify else freeze(arguments.revision)
    print(json.dumps(result, ensure_ascii=False, indent=2))
