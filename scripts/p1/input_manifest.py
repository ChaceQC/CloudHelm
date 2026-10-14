"""Print or verify the public inputs of a committed P1.1 candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
PREFIXES = (
    "database/", "modules/", "services/hub-api/", "services/hub-worker/",
    "packages/contracts/p1/", "scripts/p1/", "tests/p1/", "infra/p1/",
)
COMMON = {
    ".python-version", "pyproject.toml", "uv.lock", ".github/workflows/check.yml",
    "docs/implementation/p1-1-foundation.md", "docs/development/p1-hub.md",
    "docs/design/01-domain-collaboration.md", "docs/design/02-execution-recovery.md",
    "docs/design/05-security-sync-operations.md", "docs/design/06-implementation-validation.md",
    "docs/decisions/p0/identity-permissions-migrations.md",
    "docs/decisions/p0/task-control.md", "docs/decisions/p0/migration-contract.md",
}
MANIFEST_PATH = re.compile(r"docs/acceptance/p1/input-set-p1-1-r[1-9][0-9]*\.json")


def _git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT)


def _selected(name: str) -> bool:
    path = PurePosixPath(name)
    return (name in COMMON or name.startswith(PREFIXES)
            or (name.startswith("packages/contracts/p0/") and path.suffix == ".py"))


def _public_names(source_commit: str) -> list[str]:
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("source_commit_required")
    all_names = _git("ls-tree", "-r", "--name-only", "-z", source_commit).decode("utf-8").split("\0")
    names = sorted(name for name in all_names if name and _selected(name))
    missing = COMMON - set(names)
    if missing:
        raise ValueError("required_public_inputs_missing: " + ", ".join(sorted(missing)))
    for name in names:
        path = PurePosixPath(name)
        forbidden = {".thesis-work", ".venv", "__pycache__", "runtime-data", "secrets"}
        env_templates = {".env.example", ".env.sample", ".env.template", ".env.schema"}
        private_env = path.name.startswith(".env") and path.name not in env_templates
        if (forbidden.intersection(path.parts) or private_env
                or path.suffix.lower() in {".pem", ".key", ".p12", ".pfx"}):
            raise ValueError("non_public_input_rejected")
    return names


def _files(source_commit: str) -> list[dict[str, str]]:
    names = _public_names(source_commit)
    current_names = _git("ls-files", "--cached", "--others", "--exclude-standard", "-z")
    current = sorted(name for name in current_names.decode("utf-8").split("\0") if name and _selected(name))
    if current != names:
        raise ValueError("candidate_file_set_changed")
    files = []
    for name in names:
        data = (ROOT / name).read_bytes()
        data.decode("utf-8")
        if data != _git("show", f"{source_commit}:{name}"):
            raise ValueError("public_input_differs_from_commit: " + name)
        files.append({"path": name, "sha256": hashlib.sha256(data).hexdigest()})
    return files


def freeze(revision: str) -> dict:
    if not re.fullmatch(r"r[1-9][0-9]*", revision):
        raise ValueError("invalid_input_revision")
    source = _git("rev-parse", "HEAD").decode("ascii").strip()
    return {
        "revision": "p1-1-input-set-" + revision,
        "method_revision": "p1-1-manifest-r1",
        "source_commit": source,
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope": "P1.1 public implementation, contracts, locked dependencies and validation methods",
        "files": _files(source),
    }


def verify(path: str) -> dict:
    if not MANIFEST_PATH.fullmatch(path):
        raise ValueError("expected_p1_1_public_manifest_path")
    manifest = json.loads((ROOT / path).read_text(encoding="utf-8"))
    revision = PurePosixPath(path).stem.removeprefix("input-set-p1-1-")
    if (manifest.get("revision") != "p1-1-input-set-" + revision
            or manifest.get("method_revision") != "p1-1-manifest-r1"):
        raise ValueError("manifest_revision_mismatch")
    files = _files(manifest["source_commit"])
    if files != manifest.get("files"):
        raise ValueError("manifest_content_mismatch")
    return {"input_set": path, "source_commit": manifest["source_commit"],
            "file_count": len(files), "matches": True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", default="r1")
    parser.add_argument("--verify")
    args = parser.parse_args()
    result = verify(args.verify) if args.verify else freeze(args.revision)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
