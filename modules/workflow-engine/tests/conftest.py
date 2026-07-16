"""Workflow Engine 真实 PostgreSQL 隔离测试夹具。"""

from __future__ import annotations

import os
import json
import re
import shutil
import sys
import tempfile
from collections.abc import Generator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session

from cloudhelm_platform_api.core.config import get_settings
from cloudhelm_platform_api.db.session import (
    reset_engine_cache as reset_platform_engine_cache,
)
from cloudhelm_platform_api.models.project import Project
from cloudhelm_platform_api.models.task import Task
from cloudhelm_platform_api.models.workflow_job import WorkflowJob
from cloudhelm_platform_api.main import create_app
from cloudhelm_platform_api.services.release_candidate_policy import (
    build_reconcile_job_spec,
)
from cloudhelm_workflow_engine.config import get_workflow_settings
from cloudhelm_workflow_engine.database import (
    get_engine,
    get_session_factory,
    reset_database_cache,
)

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+psycopg://cloudhelm:cloudhelm_dev@127.0.0.1:15432/"
    "cloudhelm_test"
)
_DATABASE_NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
WORKFLOW_ROOT = Path(__file__).resolve().parents[1]
PLATFORM_ROOT = WORKFLOW_ROOT.parent / "platform-api"
REPO_ROOT = WORKFLOW_ROOT.parents[1]
sys.path.insert(0, str(PLATFORM_ROOT / "tests"))


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> Generator[None, None, None]:
    """创建并迁移会话级临时数据库，绝不重置开发库。"""

    database_url, ephemeral = _create_ephemeral_database()
    os.environ["CLOUDHELM_DATABASE_URL"] = database_url
    default_broker_url = (
        "redis://127.0.0.1:16380/15"
        if os.environ.get("CLOUDHELM_RUN_WORKFLOW_INTEGRATION") == "1"
        else "redis://127.0.0.1:16379/15"
    )
    os.environ.setdefault(
        "CLOUDHELM_WORKFLOW_BROKER_URL",
        default_broker_url,
    )
    artifact_root = tempfile.mkdtemp(
        prefix="cloudhelm-workflow-test-artifacts-"
    )
    workspace_root = tempfile.mkdtemp(
        prefix="cloudhelm-workflow-test-workspaces-"
    )
    os.environ["CLOUDHELM_ARTIFACT_ROOT"] = artifact_root
    os.environ["CLOUDHELM_M6_WORKSPACE_ROOT"] = workspace_root
    os.environ["CLOUDHELM_M6_SAMPLE_REPO_ROOT"] = str(
        REPO_ROOT / "examples" / "sample-repo-python"
    )
    os.environ["CLOUDHELM_M6_RECIPE_ROOT"] = str(
        REPO_ROOT
        / "examples"
        / "sample-repo-python"
        / "demo-issues"
    )
    os.environ["CLOUDHELM_REPOSITORY_PROFILES"] = json.dumps(
        {
            "test-primary": {
                "provider": "gitea",
                "repository_external_id": "workflow-repo-42",
                "repository_owner": "CloudHelm",
                "repository_name": "Workflow-Sample",
                "clone_url": (
                    "https://gitea.example.test/CloudHelm/"
                    "Workflow-Sample.git"
                ),
                "default_branch": "dev",
                "credential_ref": "test/workflow/repository",
                "workflow_id": ".gitea/workflows/ci.yml",
                "release_ref_prefix": (
                    "refs/heads/cloudhelm/candidates"
                ),
            }
        }
    )
    os.environ["CLOUDHELM_REPOSITORY_CREDENTIALS"] = json.dumps(
        {"test/workflow/repository": "workflow-test-token"}
    )
    get_settings.cache_clear()
    get_workflow_settings.cache_clear()
    reset_platform_engine_cache()
    reset_database_cache()
    alembic_config = Config(str(PLATFORM_ROOT / "alembic.ini"))
    alembic_config.set_main_option(
        "script_location",
        str(PLATFORM_ROOT / "migrations"),
    )
    command.upgrade(alembic_config, "head")
    try:
        yield
    finally:
        reset_database_cache()
        reset_platform_engine_cache()
        get_workflow_settings.cache_clear()
        get_settings.cache_clear()
        shutil.rmtree(artifact_root, ignore_errors=True)
        shutil.rmtree(workspace_root, ignore_errors=True)
        _drop_ephemeral_database(*ephemeral)


@pytest.fixture(autouse=True)
def clean_tables(migrated_database: None) -> Generator[None, None, None]:
    """每个测试清空业务数据。"""

    with get_engine().begin() as connection:
        connection.execute(
            text(
                """
                TRUNCATE TABLE
                  workflow_jobs,
                  release_candidates,
                  project_repository_bindings,
                  remote_agent_replay_nonces,
                  remote_agent_credentials,
                  remote_targets,
                  environments,
                  pull_request_records,
                  artifacts,
                  event_logs,
                  tool_calls,
                  agent_conversations,
                  development_plans,
                  technical_designs,
                  approval_requests,
                  requirement_specs,
                  agent_runs,
                  tasks,
                  projects
                RESTART IDENTITY CASCADE
                """
            )
        )
    yield


@pytest.fixture()
def session_factory(migrated_database: None):
    """暴露 Workflow Engine 短 Session 工厂。"""

    return get_session_factory()


@pytest.fixture()
def platform_client(migrated_database: None) -> Generator[TestClient, None, None]:
    """创建与 Workflow Engine 共享同一隔离数据库的 Platform API client。"""

    with TestClient(create_app()) as client:
        yield client


@pytest.fixture()
def seed_job(session_factory):
    """创建最小真实 Project/Task/pending reconcile job。"""

    def seed(
        *,
        task_status: str = "running",
        max_attempts: int = 3,
    ) -> dict[str, UUID]:
        candidate_id = uuid4()
        approval_id = uuid4()
        pull_request_id = uuid4()
        spec = build_reconcile_job_spec(
            candidate_id=candidate_id,
            approval_id=approval_id,
            pull_request_record_id=pull_request_id,
            candidate_request_hash="sha256:" + ("a" * 64),
            binding_snapshot_sha256="sha256:" + ("b" * 64),
        )
        with session_factory() as session:
            project = Project(
                name=f"workflow-{uuid4().hex[:8]}",
                repo_url="local://workflow-test",
                default_branch="main",
                provider="local",
            )
            session.add(project)
            session.flush()
            task = Task(
                project_id=project.id,
                title="Workflow Engine 测试",
                description="验证 dispatcher、worker 和 lease。",
                source_type="manual",
                status=task_status,
                risk_level="L1",
                current_phase="WaitingReleaseCandidateApproval",
                created_by="pytest",
            )
            session.add(task)
            session.flush()
            database_now = session.scalar(select(text("clock_timestamp()")))
            job = WorkflowJob(
                task_id=task.id,
                job_type="release_candidate_reconcile",
                resource_type="release_candidate",
                resource_id=candidate_id,
                side_effect_class="none",
                request_hash=spec.request_hash,
                idempotency_key=spec.idempotency_key,
                status="pending",
                attempt=0,
                max_attempts=max_attempts,
                enqueue_attempt=0,
                payload_json=spec.payload,
                created_at=database_now,
                updated_at=database_now,
                next_enqueue_at=database_now,
            )
            session.add(job)
            session.commit()
            return {
                "project_id": project.id,
                "task_id": task.id,
                "job_id": job.id,
                "candidate_id": candidate_id,
                "approval_id": approval_id,
                "pull_request_record_id": pull_request_id,
            }

    return seed


def _create_ephemeral_database() -> tuple[str, tuple[URL, str]]:
    """在本地 PostgreSQL 实例创建随机测试数据库。"""

    base_url = make_url(
        os.environ.get(
            "CLOUDHELM_WORKFLOW_TEST_DATABASE_URL",
            DEFAULT_TEST_DATABASE_URL,
        )
    )
    database_name = base_url.database or ""
    if (
        base_url.get_backend_name() != "postgresql"
        or not _DATABASE_NAME.fullmatch(database_name)
        or "test" not in database_name.split("_")
    ):
        raise RuntimeError("Workflow Engine 测试数据库名必须包含独立 test 段。")
    generated = f"{database_name}_{os.getpid()}_{uuid4().hex[:8]}"
    generated = generated[:63]
    admin_url = base_url.set(database="postgres")
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{generated}"')
    finally:
        admin_engine.dispose()
    test_url = base_url.set(database=generated)
    return (
        test_url.render_as_string(hide_password=False),
        (admin_url, generated),
    )


def _drop_ephemeral_database(admin_url: URL, database_name: str) -> None:
    """终止测试连接并删除随机数据库。"""

    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as connection:
            connection.execute(
                text(
                    """
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity
                    WHERE datname = :database_name
                      AND pid <> pg_backend_pid()
                    """
                ),
                {"database_name": database_name},
            )
            connection.exec_driver_sql(
                f'DROP DATABASE IF EXISTS "{database_name}"'
            )
    finally:
        admin_engine.dispose()
