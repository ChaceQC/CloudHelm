"""Check or print the API schema without entering the database-backed lifespan."""

import argparse
import importlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / "packages/contracts/p1/hub-openapi.json"
REMOTE_SNAPSHOT = ROOT / "packages/contracts/p1/remote-openapi.json"


def check() -> dict[str, object]:
    create_app = importlib.import_module("services.hub-api.app").create_app
    schema = create_app().openapi()
    frozen = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    if schema != frozen:
        raise ValueError("hub_openapi_snapshot_mismatch")
    from modules.delivery.remote_http import create_app as remote_app

    remote_schema = remote_app().openapi()
    if remote_schema != json.loads(REMOTE_SNAPSHOT.read_text(encoding="utf-8")):
        raise ValueError("remote_openapi_snapshot_mismatch")
    methods = {"get", "post", "put", "patch", "delete", "options", "head"}
    return {
        "method_revision": "p1-public-contracts-r1",
        "schema_revision": schema["x-cloudhelm-schema-revision"],
        "path_count": len(schema["paths"]),
        "operation_count": sum(len(methods.intersection(path)) for path in schema["paths"].values()),
        "schema_count": len(schema.get("components", {}).get("schemas", {})),
        "snapshot_match": True,
        "remote_path_count": len(remote_schema["paths"]),
        "remote_snapshot_match": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", action="store_true", help="Print the current public schema without writing files")
    args = parser.parse_args()
    if args.export:
        create_app = importlib.import_module("services.hub-api.app").create_app
        result = create_app().openapi()
    else:
        result = check()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
