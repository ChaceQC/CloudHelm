"""Focused P0 contract checks; no InputSet freezing or product acceptance."""

import ast
import importlib
import json
from pathlib import Path

from packages.contracts.p0.decision_schema import decision_schema

ROOT = Path(__file__).resolve().parents[2]
CHECKS = ("core", "identity", "migrations", "resources", "task", "permits", "preview")


def check() -> dict:
    if not __debug__:
        raise RuntimeError("CONTRACT_CHECKS_REQUIRE_ASSERTIONS_ENABLED")
    sources = [*ROOT.joinpath("packages/contracts/p0").glob("*.py")]
    sources.extend(ROOT / f"scripts/p0/check_decision_{name}.py" for name in CHECKS)
    sources.append(Path(__file__))
    for path in sources:
        ast.parse(path.read_text(encoding="utf-8"), filename=path.relative_to(ROOT).as_posix())

    snapshot = json.loads((ROOT / "packages/contracts/p0/decisions-r1.schema.json").read_text(encoding="utf-8"))
    if snapshot != decision_schema():
        raise ValueError("DECISION_SCHEMA_SNAPSHOT_STALE")

    groups = {}
    for name in CHECKS:
        results = importlib.import_module(f"scripts.p0.check_decision_{name}").run_checks()
        if not results or any(result is not True for result in results.values()):
            raise AssertionError(f"DECISION_CHECK_FAILED: {name}")
        groups[name] = results
    return {"method_revision": "p0-decisions-check-r2", "schema_matches": True, "groups": groups}


if __name__ == "__main__":
    print(json.dumps(check(), ensure_ascii=False, indent=2, sort_keys=True))
