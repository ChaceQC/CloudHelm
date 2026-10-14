"""Run the bounded P1.1 integration groups against one isolated PostgreSQL fixture."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import platform
import sys
import traceback
from dataclasses import asdict
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

from scripts.p1.check_public_contracts import check as check_public_contracts
from scripts.p1.database_fixture import database_fixture
from scripts.p1.input_manifest import ROOT, verify

GROUPS = ("database", "identity", "tasks", "runtime")
METHOD_REVISION = "p1-foundation-r1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def emit(record: dict) -> None:
    print(json.dumps(record, ensure_ascii=False, sort_keys=True), flush=True)


def failure_details(failure: Exception) -> dict:
    """Keep locations and fixed categories, never exception payloads or local values."""
    frames = []
    for frame in traceback.extract_tb(failure.__traceback__)[-8:]:
        path = Path(frame.filename)
        try:
            name = path.relative_to(ROOT).as_posix()
        except ValueError:
            name = path.name
        frames.append({"file": name, "line": frame.lineno, "function": frame.name})
    return {"error_type": type(failure).__name__, "frames": frames}


def input_binding(path: str | None, development: bool) -> dict:
    if path:
        binding = verify(path)
        binding["sha256"] = hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        return binding
    if not development:
        raise ValueError("fixed_input_set_required")
    return {"mode": "development_worktree", "matches": False}


def environment() -> dict:
    return {
        "system": platform.system(), "kernel": platform.release(),
        "python": platform.python_version(),
        "dbos": version("dbos"), "sqlalchemy": version("sqlalchemy"),
        "psycopg": version("psycopg"), "fastapi": version("fastapi"),
        "pydantic": version("pydantic"), "uvicorn": version("uvicorn"),
    }


def run_groups(groups: tuple[str, ...], report: dict) -> Exception | None:
    problem = None
    with database_fixture() as fixture:
        report["fixture_id"] = fixture.project_name
        report["baseline"] = asdict(fixture.baseline)
        for group in groups:
            report["active_group"] = group
            emit({"status": "checking", "group": group, "at_utc": utc_now()})
            try:
                module = importlib.import_module(f"scripts.p1.check_{group}")
                checks = module.run_checks(fixture)
                if not isinstance(checks, dict) or not checks:
                    raise TypeError("nonempty_check_mapping_required")
                if any(type(value) is not bool for value in checks.values()):
                    raise TypeError("boolean_check_results_required")
                report["checks"][group] = checks
                if not all(checks.values()):
                    raise AssertionError("integration_group_failed")
            except Exception as failure:
                problem = failure
                break
    report["cleanup"] = "complete"
    if problem is None:
        report.pop("active_group", None)
    return problem


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    binding = parser.add_mutually_exclusive_group(required=True)
    binding.add_argument("--input-set", help="Fixed public P1.1 candidate manifest")
    binding.add_argument("--development", action="store_true", help="Unfrozen worktree check; not final candidate evidence")
    parser.add_argument("--group", action="append", choices=GROUPS)
    args = parser.parse_args()
    chosen = tuple(group for group in GROUPS if not args.group or group in args.group)
    report = {
        "method_revision": METHOD_REVISION, "started_at_utc": utc_now(),
        "groups": chosen, "complete_scope": chosen == GROUPS, "checks": {},
        "cleanup": "not_started",
        "scope": "WSL development integration; Task completion uses controlled synthetic domain facts",
        "human_acceptance": "not_performed", "independent_delivery": "not_performed",
    }
    emit({"status": "running", "method_revision": METHOD_REVISION, "groups": chosen})
    try:
        report["input_binding"] = input_binding(args.input_set, args.development)
        report["environment"] = environment()
        report["public_contracts"] = check_public_contracts()
        failure = run_groups(chosen, report)
        if failure is not None:
            report.update(status="failed", **failure_details(failure))
        else:
            if args.input_set:
                verify(args.input_set)
            report["status"] = "passed"
    except Exception as failure:
        report.update(status="failed", **failure_details(failure))
    report["finished_at_utc"] = utc_now()
    emit(report)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
