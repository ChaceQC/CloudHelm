"""M7-2D Alembic upgrade/downgrade 独立数据库往返测试。"""

import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]


def test_m7_ci_deployment_migration_roundtrip() -> None:
    """0008 -> head -> 0008 -> head/check 不破坏旧 M7 数据底座。"""

    base_url = make_url(os.environ["CLOUDHELM_DATABASE_URL"])
    database_name = f"cloudhelm_test_m7_2d_roundtrip_{uuid4().hex[:10]}"
    admin_url = base_url.set(database="postgres")
    target_url = base_url.set(database=database_name)
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    target_engine = None
    try:
        with admin_engine.connect() as connection:
            connection.exec_driver_sql(
                f'CREATE DATABASE "{database_name}"'
            )

        _alembic(target_url, "upgrade", "20260716_0008")
        target_engine = create_engine(target_url)
        assert _tables(target_engine).isdisjoint(
            {"ci_runs", "deployments", "service_instances"}
        )
        assert "ck_approval_requests_release_candidate" in _constraints(
            target_engine
        )
        assert "ck_approval_requests_deployment" not in _constraints(
            target_engine
        )

        _alembic(target_url, "upgrade", "head")
        assert {
            "ci_runs",
            "deployments",
            "service_instances",
        }.issubset(_tables(target_engine))
        assert "ck_approval_requests_deployment" in _constraints(
            target_engine
        )
        assert (
            "ck_approval_requests_m7_resource_action_group"
            in _constraints(target_engine)
        )

        _alembic(target_url, "downgrade", "20260716_0008")
        assert _tables(target_engine).isdisjoint(
            {"ci_runs", "deployments", "service_instances"}
        )
        constraints = _constraints(target_engine)
        assert "ck_approval_requests_release_candidate" in constraints
        assert "ck_approval_requests_deployment" not in constraints
        assert (
            "ck_approval_requests_m7_resource_action_group"
            not in constraints
        )
        assert {
            "project_repository_bindings",
            "release_candidates",
            "workflow_jobs",
        }.issubset(_tables(target_engine))

        _alembic(target_url, "upgrade", "head")
        _alembic(target_url, "check")
    finally:
        if target_engine is not None:
            target_engine.dispose()
        with admin_engine.connect() as connection:
            connection.exec_driver_sql(
                f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)'
            )
        admin_engine.dispose()


def _alembic(target_url, *arguments: str) -> None:
    """在独立子进程中对指定测试数据库执行 Alembic。"""

    environment = os.environ.copy()
    environment["CLOUDHELM_DATABASE_URL"] = target_url.render_as_string(
        hide_password=False
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            str(ROOT / "alembic.ini"),
            *arguments,
        ],
        cwd=ROOT,
        env=environment,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"Alembic {' '.join(arguments)} failed\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def _tables(engine) -> set[str]:
    """读取 public schema 表名。"""

    with engine.connect() as connection:
        return {
            row.table_name
            for row in connection.execute(
                text(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                    """
                )
            )
        }


def _constraints(engine) -> set[str]:
    """读取 public schema 约束名。"""

    with engine.connect() as connection:
        return {
            row.conname
            for row in connection.execute(
                text(
                    """
                    SELECT conname
                    FROM pg_constraint
                    WHERE connamespace = 'public'::regnamespace
                    """
                )
            )
        }
