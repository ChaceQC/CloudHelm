"""Print a public-file InputSet; never inspect configuration or runtime secrets."""

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMMON = {"pyproject.toml", "uv.lock", ".python-version"}
A01 = {
    "integrations/model_pricing.py", "integrations/seam_admission.py",
    "integrations/seam_checkpoint.py", "integrations/seam_continuation.py",
    "integrations/seam_gateway.py", "integrations/seam_stream.py",
    "scripts/p0/model_boundary.py", "scripts/p0/gateway_probe.py",
    "scripts/p0/check_pricing.py", "scripts/p0/check_admission.py",
    "scripts/p0/check_checkpoint.py", "scripts/p0/check_continuation.py",
    "scripts/p0/probe_admitted_stream.py", "scripts/p0/connect_live_continuation.py",
    "scripts/p0/freeze_inputs.py",
    "infra/p0/compose.yaml", "packages/contracts/p0/official-model-prices-r1.json",
}
A02 = A01 | {
    "scripts/p0/admitted_path_fixtures.py",
    "scripts/p0/admitted_recovery_workflows.py",
    "scripts/p0/probe_admitted_recovery.py",
    "scripts/p0/check_admitted_paths.py",
    "scripts/p0/check_stream_assertions.py",
}


def manifest(kind: str, revision: str = "r1") -> dict:
    if not re.fullmatch(r"r[1-9][0-9]*", revision):
        raise ValueError("InputSet revision must be r followed by a positive integer")
    if kind != "a02" and revision != "r1":
        raise ValueError("historical InputSet kinds retain their r1 revision")
    public = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT,
    ).decode("utf-8").split("\0")
    names = COMMON | (A01 if kind == "a01" else A02) if kind in {"a01", "a02"} else {
        name for name in public if name.startswith("examples/standalone-project/")
        or name.startswith("docs/acceptance/reference/r1/")
    } | {"docs/implementation/reference-requirements-r1.md"}
    source_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
    files = []
    for name in sorted(names):
        data = (ROOT / name).read_bytes()
        committed = subprocess.check_output(["git", "show", f"{source_commit}:{name}"], cwd=ROOT)
        if data != committed:
            raise ValueError(f"public input differs from source commit: {name}")
        files.append({"path": name, "sha256": hashlib.sha256(data).hexdigest()})
    return {
        "revision": f"p0-{kind}-input-set-{revision}" if kind in {"a01", "a02"} else "p0-reference-input-set-r1",
        "source_commit": source_commit,
        "frozen_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope": "public source, locks and independent method; runtime state and credentials excluded",
        "files": files,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=("a01", "a02", "reference"))
    parser.add_argument("--revision", default="r1")
    args = parser.parse_args()
    print(json.dumps(manifest(args.kind, args.revision), ensure_ascii=False, indent=2))
