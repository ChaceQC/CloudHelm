"""One bounded P0.3 check: syntax, schema parity and explicit contract cases."""

import argparse
import ast
import hashlib
import importlib
import importlib.metadata
import json
import platform
from datetime import datetime, timezone

from packages.contracts.p0.decision_schema import decision_schema
from scripts.p0.decision_manifest import CHECK_MODULES, CONTRACT_MODULES, ROOT, verify


def check(input_set: str | None = None) -> dict:
    if not __debug__:
        raise RuntimeError("CONTRACT_CHECKS_REQUIRE_ASSERTIONS_ENABLED")
    binding = verify(input_set) if input_set else None
    paths = [ROOT / "packages/contracts/p0" / f"{name}.py" for name in CONTRACT_MODULES]
    paths.extend(ROOT / "scripts/p0" / f"check_decision_{name}.py" for name in CHECK_MODULES)
    paths.extend(ROOT / "scripts/p0" / name for name in ("decision_manifest.py", "check_decisions.py"))
    for path in paths:
        ast.parse(path.read_text(encoding="utf-8"), filename=path.relative_to(ROOT).as_posix())
    schema_bytes = (ROOT / "packages/contracts/p0/decisions-r1.schema.json").read_bytes()
    schema = json.loads(schema_bytes.decode("utf-8"))
    if schema != decision_schema():
        raise ValueError("DECISION_SCHEMA_SNAPSHOT_STALE")
    groups = {}
    for name in CHECK_MODULES:
        module = importlib.import_module(f"scripts.p0.check_decision_{name}")
        result = module.run_checks()
        if not result or any(value is not True for value in result.values()):
            raise AssertionError(f"DECISION_CHECK_FAILED: {name}")
        groups[name] = result
    return {
        "method_revision": "p0-decisions-check-r1",
        "verified_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "environment": {
            "system": platform.system(), "kernel": platform.release(),
            "python": platform.python_version(),
            "pydantic": importlib.metadata.version("pydantic"),
            "rfc8785": importlib.metadata.version("rfc8785"),
        },
        "input_binding": binding,
        "syntax_file_count": len(paths),
        "schema_sha256": hashlib.sha256(schema_bytes).hexdigest(),
        "schema_matches": True,
        "groups": groups,
        "group_count": len(groups),
        "check_count": sum(len(group) for group in groups.values()),
        "scope": "types, fixed public contract cases and pure arithmetic only; no product, database, network or human acceptance",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-set")
    arguments = parser.parse_args()
    print(json.dumps(check(arguments.input_set), ensure_ascii=False, indent=2, sort_keys=True))
