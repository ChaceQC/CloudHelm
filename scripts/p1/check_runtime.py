"""Runtime lifecycle checks on the caller's fixture; no synthetic business workflow."""

from __future__ import annotations

import ast
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from dbos import DBOSClient, DBOSPortableJSONSerializer
from sqlalchemy import select, text, update

from database.connection import create_engine_from_settings
from database.readiness import ROLE_CONNECTION_LIMITS, ROLE_NAMES
from database.tables import runtime_baseline
from database.uow import UnitOfWork
from modules.workflow.version import APPLICATION_NAME, DBOS_SCHEMA
from scripts.p1.database_fixture import DatabaseFixture
from scripts.p1.runtime_processes import (
    EXIT_TIMEOUT, RuntimeProcessError, api_process, api_running, worker_process, worker_running,
)

_ROOT = Path(__file__).resolve().parents[2]


class RuntimeCheckFailure(AssertionError):
    """Only a fixed scene classification is returned to the outer report."""


def _connection_counts(engine) -> dict[str, int]:
    with UnitOfWork(engine) as uow:
        rows = uow.connection.execute(text(
            "SELECT usename, count(*) AS connections FROM pg_stat_activity "
            "WHERE datname = current_database() AND usename IN (:api, :worker, :migrator) "
            "GROUP BY usename"
        ), ROLE_NAMES).mappings().all()
    observed = {row["usename"]: row["connections"] for row in rows}
    counts = {role: observed.get(name, 0) for role, name in ROLE_NAMES.items()}
    if any(counts[role] > maximum for role, maximum in ROLE_CONNECTION_LIMITS.items()):
        raise RuntimeCheckFailure("runtime_role_connection_budget_exceeded")
    return counts


def _api_client_source() -> None:
    """A separate static boundary check complements real liveness/connection samples."""
    for path in (_ROOT / "services/hub-api").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "dbos":
                if any(alias.name == "DBOS" for alias in node.names):
                    raise RuntimeCheckFailure("api_imports_worker_runtime")
            if isinstance(node, ast.Call):
                name = node.func.id if isinstance(node.func, ast.Name) else None
                attribute = node.func.attr if isinstance(node.func, ast.Attribute) else None
                if name == "DBOS" or attribute in {"DBOS", "launch", "launch_async"}:
                    raise RuntimeCheckFailure("api_calls_worker_runtime")


def _api_instances(fixture: DatabaseFixture, engine, client: DBOSClient) -> None:
    _api_client_source()
    versions = client.list_application_versions()
    with api_running(fixture, instance="runtime1"):
        with api_running(fixture, instance="runtime2"):
            counts = _connection_counts(engine)
            if counts["api"] < 2 or counts["worker"] != 0:
                raise RuntimeCheckFailure("api_instance_connection_boundary_failed")
            if client.list_application_versions() != versions:
                raise RuntimeCheckFailure("api_changed_workflow_application_versions")


def _worker_lifecycle(fixture: DatabaseFixture, engine) -> None:
    with worker_process(fixture) as first:
        first.wait_ready()
        if _connection_counts(engine)["worker"] < 1:
            raise RuntimeCheckFailure("runtime_worker_database_connections_missing")
        with worker_process(fixture) as second:
            second.expect_rejected("worker_already_running")
        first.process.terminate()
        try:
            code = first.process.wait(timeout=EXIT_TIMEOUT)
        except Exception:
            raise RuntimeCheckFailure("worker_sigterm_exit_not_confirmed") from None
        if code != 0:
            raise RuntimeCheckFailure("worker_sigterm_returned_failure")
    with worker_running(fixture):
        if _connection_counts(engine)["worker"] < 1:
            raise RuntimeCheckFailure("runtime_worker_database_connections_missing")


@contextmanager
def _baseline_override(fixture: DatabaseFixture, engine, **changes) -> Iterator[None]:
    if fixture.baseline is None or set(changes) - {"mode", "application_version"}:
        raise RuntimeCheckFailure("runtime_fixture_baseline_invalid")
    identity = runtime_baseline.c.installation_id == fixture.baseline.installation_id
    with UnitOfWork(engine) as uow:
        row = uow.connection.execute(select(runtime_baseline).where(identity).with_for_update()).mappings().one_or_none()
        if row is None:
            raise RuntimeCheckFailure("runtime_fixture_identity_mismatch")
        original = {key: row[key] for key in changes}
        uow.connection.execute(update(runtime_baseline).where(identity).values(**changes))
    try:
        yield
    finally:
        with UnitOfWork(engine) as uow:
            restored = uow.connection.execute(update(runtime_baseline).where(
                identity, *(runtime_baseline.c[key] == value for key, value in changes.items())
            ).values(**original))
            if restored.rowcount != 1:
                raise RuntimeCheckFailure("runtime_fixture_baseline_restore_failed")


def _rejected_baselines(fixture: DatabaseFixture, engine) -> None:
    scenes = (
        ({"mode": "recovery_required"}, "database_recovery_gate_closed", "recovery"),
        ({"application_version": "runtime-check-incompatible"}, "database_baseline_incompatible", "version"),
    )
    for changes, reason, instance in scenes:
        with _baseline_override(fixture, engine, **changes):
            with worker_process(fixture) as worker:
                worker.expect_rejected(reason)
            with api_process(fixture, instance=instance) as api:
                api.expect_rejected()
    _connection_counts(engine)


def run_checks(fixture: DatabaseFixture) -> dict[str, bool]:
    """Run after other groups have closed their pools/processes; history may remain."""
    engine = create_engine_from_settings(fixture.settings("migrator"), purpose="maintenance")
    client = None
    scene = "runtime_database_observer_failed"
    try:
        client = DBOSClient(
            system_database_engine=engine, dbos_system_schema=DBOS_SCHEMA,
            application_name=APPLICATION_NAME, serializer=DBOSPortableJSONSerializer(),
            use_listen_notify=False, retry_connection_errors=False,
        )
        scene = "runtime_api_instance_checks_failed"
        _api_instances(fixture, engine, client)
        scene = "runtime_worker_lifecycle_checks_failed"
        _worker_lifecycle(fixture, engine)
        scene = "runtime_baseline_rejection_checks_failed"
        _rejected_baselines(fixture, engine)
        return {"api_liveness_two_instances": True, "api_source_client_only": True,
                "api_no_worker_connections_or_version_changes": True,
                "worker_single_instance_and_sigterm_restart": True,
                "role_connection_samples_within_budget": True,
                "recovery_and_version_gates_rejected": True,
                "fixture_baseline_restored": True}
    except (RuntimeCheckFailure, RuntimeProcessError):
        raise
    except Exception:
        raise RuntimeCheckFailure(scene) from None
    finally:
        try:
            try:
                if client is not None:
                    client.destroy()
            finally:
                engine.dispose()
        except Exception:
            raise RuntimeCheckFailure("runtime_observer_cleanup_failed") from None
