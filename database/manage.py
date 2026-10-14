"""Controlled initialization/status CLI; credentials never enter argv or output."""

import argparse
import json
import sys
from dataclasses import asdict

from sqlalchemy import inspect, select

from database.connection import create_engine_from_settings
from database.maintenance import MaintenanceError, initialize_database
from database.readiness import DatabaseNotReady, assert_schema_ready, require_maintenance_role
from database.settings import DatabaseConfigurationError, DatabaseSettings, load_database_settings
from database.tables import runtime_baseline
from database.uow import DatabaseFailure, UnitOfWork


def _status(settings: DatabaseSettings) -> dict[str, object]:
    engine = create_engine_from_settings(settings, purpose="maintenance")
    try:
        with UnitOfWork(engine) as uow:
            require_maintenance_role(uow.connection)
            if not inspect(uow.connection).has_table("runtime_baseline", schema="cloudhelm"):
                return {"status": "not_initialized"}
            row = uow.connection.execute(select(runtime_baseline)).mappings().one_or_none()
            if row is None:
                return {"status": "unknown", "reason": "installation_provenance_missing"}
            if row["mode"] == "ready":
                return {"status": "ready", **asdict(assert_schema_ready(uow.connection))}
            return {"status": row["mode"], "installation_id": row["installation_id"],
                    "initialization_operation_id": row["initialization_operation_id"]}
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="CloudHelm controlled database maintenance")
    parser.add_argument("action", choices=("initialize", "status"))
    parser.add_argument("--operation-id", help="Stable identity when resuming interrupted initialization")
    args = parser.parse_args()
    try:
        settings = load_database_settings("migrator")
        if args.action == "initialize":
            baseline = initialize_database(settings, operation_id=args.operation_id)
            result = {"status": "ready", **asdict(baseline)}
        else:
            result = _status(settings)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (MaintenanceError, DatabaseNotReady, DatabaseConfigurationError, DatabaseFailure) as failure:
        print(json.dumps({"status": "rejected", "reason": str(failure)}), file=sys.stderr)
        return 1
    except Exception:
        print('{"status":"rejected","reason":"maintenance_unavailable"}', file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
