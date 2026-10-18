"""Freeze or verify public P1.2 inputs without persisting private runtime data."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
METHOD_REVISION = "p1-2-manifest-r1"
PREFIXES = (
    "database/", "modules/", "services/", "packages/contracts/p1/",
    "scripts/p1/", "infra/p1/", "examples/standalone-project/",
    "docs/acceptance/reference/r1/",
)
COMMON = frozenset({
    ".python-version", "pyproject.toml", "uv.lock", ".github/workflows/check.yml",
    "docs/implementation/p1-2-engineering.md",
    "docs/development/p1-hub.md", "docs/development/p1-engineering.md",
    "docs/implementation/reference-requirements-r1.md",
    "docs/decisions/p0/reference-applicability.md",
    "docs/design/01-domain-collaboration.md",
    "docs/design/02-execution-recovery.md",
    "docs/design/03-workspace-build-resources.md",
    "docs/design/04-release-deployment.md",
    "docs/design/05-security-sync-operations.md",
    "docs/design/06-implementation-validation.md",
})
MANIFEST_PATH = re.compile(r"docs/acceptance/p1/input-set-p1-2-r[1-9][0-9]*\.json")


def _git(*args: str, input_bytes: bytes | None = None) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT, timeout=30, input=input_bytes)


def _selected(name: str) -> bool:
    return (name in COMMON or name.startswith(PREFIXES)
            or (name.startswith("packages/contracts/p0/") and name.endswith(".py")))


def _safe_name(name: str) -> None:
    path = PurePosixPath(name)
    private = {".thesis-work", ".venv", "__pycache__", "node_modules",
               "runtime-data", "secrets", ".secrets", ".git"}
    templates = {".env.example", ".env.sample", ".env.template", ".env.schema"}
    if (path.is_absolute() or ".." in path.parts or private.intersection(path.parts)
            or (path.name.startswith(".env") and path.name not in templates)
            or path.suffix.lower() in {".key", ".pem", ".p12", ".pfx"}):
        raise ValueError("non_public_input_rejected")


def current_files() -> list[dict[str, str]]:
    """Development fingerprint only; it does not establish a committed candidate."""
    raw = _git("ls-files", "--cached", "--others", "--exclude-standard", "-z")
    names = sorted({name for name in raw.decode("utf-8").split("\0") if name and _selected(name)})
    files = []
    for name in names:
        _safe_name(name)
        path = ROOT / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("public_input_not_regular_file")
        data = path.read_bytes()
        data.decode("utf-8")
        files.append({"path": name, "sha256": hashlib.sha256(data).hexdigest()})
    return files


def _committed_files(source_commit: str) -> list[dict[str, str]]:
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("source_commit_required")
    raw = _git("ls-tree", "-r", "-z", source_commit)
    objects = {}
    for entry in raw.split(b"\0"):
        if not entry:
            continue
        metadata, path = entry.split(b"\t", 1)
        name = path.decode("utf-8")
        if _selected(name):
            objects[name] = metadata.split()[2].decode("ascii")
    names = sorted(objects)
    if not COMMON.issubset(names):
        raise ValueError("required_public_inputs_missing")
    files = current_files()
    if [item["path"] for item in files] != names:
        raise ValueError("candidate_file_set_changed")
    requests = "".join(objects[item["path"]] + "\n" for item in files).encode("ascii")
    stream = io.BytesIO(_git("cat-file", "--batch", input_bytes=requests))
    for item in files:
        header = stream.readline(256).split()
        if len(header) != 3 or header[0].decode("ascii") != objects[item["path"]] or header[1] != b"blob":
            raise ValueError("committed_public_blob_required")
        size = int(header[2])
        if size < 0:
            raise ValueError("committed_public_blob_size_invalid")
        committed = stream.read(size)
        if len(committed) != size or stream.read(1) != b"\n":
            raise ValueError("committed_public_blob_truncated")
        if hashlib.sha256(committed).hexdigest() != item["sha256"]:
            raise ValueError("public_input_differs_from_commit: " + item["path"])
    if stream.read(1):
        raise ValueError("committed_public_blob_set_mismatch")
    return files


def freeze(revision: str) -> dict:
    if not re.fullmatch(r"r[1-9][0-9]*", revision):
        raise ValueError("invalid_input_revision")
    source = _git("rev-parse", "HEAD").decode("ascii").strip()
    return {
        "revision": "p1-2-input-set-" + revision,
        "method_revision": METHOD_REVISION,
        "source_commit": source,
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope": "P1.2 public source, contracts, locked inputs and independent validation methods",
        "files": _committed_files(source),
    }


def verify(path: str) -> dict:
    if not MANIFEST_PATH.fullmatch(path):
        raise ValueError("expected_p1_2_public_manifest_path")
    content = (ROOT / path).read_bytes()
    manifest = json.loads(content.decode("utf-8"))
    revision = PurePosixPath(path).stem.removeprefix("input-set-p1-2-")
    if (manifest.get("revision") != "p1-2-input-set-" + revision
            or manifest.get("method_revision") != METHOD_REVISION):
        raise ValueError("manifest_revision_mismatch")
    files = _committed_files(manifest["source_commit"])
    if files != manifest.get("files"):
        raise ValueError("manifest_content_mismatch")
    return {"input_set": path, "source_commit": manifest["source_commit"],
            "sha256": hashlib.sha256(content).hexdigest(),
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
