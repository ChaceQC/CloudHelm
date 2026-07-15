"""M2 API 测试夹具。

测试通过真实 PostgreSQL 和 Alembic 迁移验证，不在生产代码路径引入
mock/stub/fake。默认连接本地开发 PostgreSQL 实例，但为每个 pytest 会话创建
独立临时数据库，禁止重置开发库 `public` schema。
"""

import os
import json
import re
import shutil
import tempfile
from collections.abc import Generator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session

from cloudhelm_platform_api.core.config import get_settings
from cloudhelm_platform_api.db.session import get_engine, reset_engine_cache
from cloudhelm_platform_api.main import create_app
from cloudhelm_platform_api.models.agent_run import AgentRun
from cloudhelm_platform_api.schemas.common import AgentRunStatus

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+psycopg://cloudhelm:cloudhelm_dev@127.0.0.1:15432/cloudhelm_test"
)
ALLOW_SCHEMA_RESET_ENV = "CLOUDHELM_TEST_ALLOW_SCHEMA_RESET"
_DATABASE_NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
ROOT = Path(__file__).resolve().parents[1]
M7_REMOTE_AGENT_SECRETS = {
    "test/agent-a/current": (
        "test-agent-a-current-secret-000000000000000000000000"
    ),
    "test/agent-a/previous": (
        "test-agent-a-previous-secret-0000000000000000000000"
    ),
    "test/agent-a/revoked": (
        "test-agent-a-revoked-secret-00000000000000000000000"
    ),
    "test/agent-a/expired": (
        "test-agent-a-expired-secret-00000000000000000000000"
    ),
    "test/agent-a/deployment": (
        "test-agent-a-deployment-secret-000000000000000000000"
    ),
    "test/agent-b/current": (
        "test-agent-b-current-secret-000000000000000000000000"
    ),
}
M7_REMOTE_TARGET_PROFILES = {
    "test-primary": {
        "agent_id": "remote-agent-a",
        "agent_endpoint": "https://agent-a.example.test:9443",
        "tls_fingerprint": f"sha256:{'a' * 64}",
        "credentials": [
            {
                "key_id": "key-current",
                "credential_ref": "test/agent-a/current",
                "scopes": ["heartbeat"],
                "active_from": "2020-01-01T00:00:00Z",
            },
            {
                "key_id": "key-previous",
                "credential_ref": "test/agent-a/previous",
                "scopes": ["heartbeat"],
                "active_from": "2020-01-01T00:00:00Z",
                "expires_at": "2099-01-01T00:00:00Z",
            },
            {
                "key_id": "key-revoked",
                "credential_ref": "test/agent-a/revoked",
                "scopes": ["heartbeat"],
                "active_from": "2020-01-01T00:00:00Z",
                "revoked_at": "2026-07-01T00:00:00Z",
            },
            {
                "key_id": "key-expired",
                "credential_ref": "test/agent-a/expired",
                "scopes": ["heartbeat"],
                "active_from": "2020-01-01T00:00:00Z",
                "expires_at": "2021-01-01T00:00:00Z",
            },
            {
                "key_id": "key-deployment",
                "credential_ref": "test/agent-a/deployment",
                "scopes": ["deployment"],
                "active_from": "2020-01-01T00:00:00Z",
            },
        ],
    },
    "test-secondary": {
        "agent_id": "remote-agent-b",
        "agent_endpoint": "https://agent-b.example.test:9444",
        "tls_fingerprint": f"sha256:{'b' * 64}",
        "credentials": [
            {
                "key_id": "key-current",
                "credential_ref": "test/agent-b/current",
                "scopes": ["heartbeat"],
                "active_from": "2020-01-01T00:00:00Z",
            }
        ],
    },
}


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> Generator[None, None, None]:
    """创建隔离测试数据库并执行 Alembic 迁移。"""

    database_url, ephemeral_database = _prepare_test_database()
    os.environ["CLOUDHELM_TEST_DATABASE_URL"] = database_url
    os.environ["CLOUDHELM_DATABASE_URL"] = database_url
    os.environ["CLOUDHELM_ENV"] = "test"
    os.environ["CLOUDHELM_VERSION"] = "0.5.1"
    os.environ["CLOUDHELM_TOOL_WORKSPACE_ROOTS"] = json.dumps([tempfile.gettempdir()])
    artifact_root = tempfile.mkdtemp(prefix="cloudhelm-test-artifacts-")
    m6_workspace_root = tempfile.mkdtemp(
        prefix="cloudhelm-test-m6-workspaces-"
    )
    os.environ["CLOUDHELM_ARTIFACT_ROOT"] = artifact_root
    os.environ["CLOUDHELM_M6_WORKSPACE_ROOT"] = m6_workspace_root
    os.environ["CLOUDHELM_M6_SAMPLE_REPO_ROOT"] = str(
        ROOT.parents[1] / "examples" / "sample-repo-python"
    )
    os.environ["CLOUDHELM_M6_RECIPE_ROOT"] = str(
        ROOT.parents[1]
        / "examples"
        / "sample-repo-python"
        / "demo-issues"
    )
    os.environ["CLOUDHELM_REMOTE_TARGET_PROFILES"] = json.dumps(
        M7_REMOTE_TARGET_PROFILES
    )
    os.environ["CLOUDHELM_REMOTE_AGENT_CREDENTIALS"] = json.dumps(
        M7_REMOTE_AGENT_SECRETS
    )
    os.environ["CLOUDHELM_REMOTE_AGENT_TIMESTAMP_TOLERANCE_SECONDS"] = "300"
    os.environ["CLOUDHELM_REMOTE_AGENT_NONCE_TTL_SECONDS"] = "900"
    os.environ["CLOUDHELM_REMOTE_AGENT_OFFLINE_TIMEOUT_SECONDS"] = "60"
    os.environ[
        "CLOUDHELM_REMOTE_AGENT_HEARTBEAT_EVENT_INTERVAL_SECONDS"
    ] = "300"
    os.environ["CLOUDHELM_REMOTE_AGENT_NEXT_HEARTBEAT_SECONDS"] = "20"
    os.environ["CLOUDHELM_REMOTE_AGENT_HEARTBEAT_MAX_BODY_BYTES"] = "16384"
    get_settings.cache_clear()
    reset_engine_cache()

    try:
        alembic_config = Config(str(ROOT / "alembic.ini"))
        command.upgrade(alembic_config, "head")
        yield
    finally:
        reset_engine_cache()
        get_settings.cache_clear()
        shutil.rmtree(artifact_root, ignore_errors=True)
        shutil.rmtree(m6_workspace_root, ignore_errors=True)
        if ephemeral_database is not None:
            _drop_ephemeral_database(*ephemeral_database)


@pytest.fixture(autouse=True)
def clean_business_tables(migrated_database: None) -> Generator[None, None, None]:
    """每个测试前清空业务表，保留 Alembic 版本表。"""

    with get_engine().begin() as connection:
        connection.execute(
            text(
                """
                TRUNCATE TABLE
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
def client() -> Generator[TestClient, None, None]:
    """创建 FastAPI 测试客户端。"""

    with TestClient(create_app()) as test_client:
        yield test_client


def create_project(client: TestClient, name: str = "演示项目") -> dict:
    """测试辅助：通过真实 API 创建项目。"""

    response = client.post(
        "/api/projects",
        json={
            "name": name,
            "repo_url": "https://example.com/cloudhelm/sample.git",
            "default_branch": "dev",
            "provider": "git",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_task(client: TestClient, project_id: str, title: str = "实现任务") -> dict:
    """测试辅助：通过真实 API 创建任务。"""

    response = client.post(
        "/api/tasks",
        json={
            "project_id": project_id,
            "title": title,
            "description": (
                "通过真实数据库验证 CloudHelm M4 编排的任务写入、"
                "状态机和事件副作用。"
            ),
            "source_type": "manual",
            "risk_level": "L1",
            "created_by": "tester",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_running_agent_run(
    task_id: str,
    agent_type: str,
    *,
    conversation_id: str | None = None,
) -> dict:
    """测试辅助：直接创建 Orchestrator 执行中的 AgentRun。"""

    with Session(get_engine()) as session:
        agent_run = AgentRun(
            task_id=UUID(task_id),
            agent_type=agent_type,
            status=AgentRunStatus.RUNNING.value,
            conversation_id=(
                UUID(conversation_id)
                if conversation_id is not None
                else None
            ),
            model_name="test-model",
            prompt_hash="pytest",
        )
        session.add(agent_run)
        session.commit()
        session.refresh(agent_run)
        return {"id": str(agent_run.id), "agent_type": agent_run.agent_type, "status": agent_run.status}


def _prepare_test_database() -> tuple[str, tuple[URL, str] | None]:
    """返回安全测试 URL；默认创建可并行、会话级临时数据库。

    显式 `CLOUDHELM_TEST_DATABASE_URL` 只允许指向名称含独立 `test` 段的
    PostgreSQL 数据库，并且必须同时启用 schema reset 开关。默认路径不重置
    任何既有数据库，而是在同一实例中创建并在测试后删除临时数据库。
    """

    configured_url = os.environ.get("CLOUDHELM_TEST_DATABASE_URL")
    base_url = make_url(configured_url or DEFAULT_TEST_DATABASE_URL)
    _validate_test_database_url(base_url)
    if configured_url:
        if os.environ.get(ALLOW_SCHEMA_RESET_ENV, "").lower() not in {
            "1",
            "true",
            "yes",
        }:
            raise RuntimeError(
                f"显式测试数据库需要设置 {ALLOW_SCHEMA_RESET_ENV}=true，"
                "确认允许重建其 public schema。"
            )
        _reset_test_schema(base_url)
        return base_url.render_as_string(hide_password=False), None

    database_name = (
        f"{base_url.database}_{os.getpid()}_{uuid4().hex[:8]}"
    )
    if len(database_name) > 63:
        database_name = database_name[:63]
    admin_url = base_url.set(database="postgres")
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as connection:
            connection.exec_driver_sql(
                f'CREATE DATABASE "{database_name}"'
            )
    finally:
        admin_engine.dispose()
    test_url = base_url.set(database=database_name)
    return (
        test_url.render_as_string(hide_password=False),
        (admin_url, database_name),
    )


def _validate_test_database_url(database_url: URL) -> None:
    """拒绝开发库、生产库或不可安全引用的数据库名称。"""

    if database_url.get_backend_name() != "postgresql":
        raise RuntimeError("Platform API 测试只允许使用 PostgreSQL 测试数据库。")
    database_name = database_url.database or ""
    if (
        not _DATABASE_NAME.fullmatch(database_name)
        or "test" not in database_name.split("_")
    ):
        raise RuntimeError(
            "CLOUDHELM_TEST_DATABASE_URL 的数据库名必须包含独立的 test 段，"
            "例如 cloudhelm_test。"
        )


def _reset_test_schema(database_url: URL) -> None:
    """仅在显式双重确认后重建专用测试数据库 schema。"""

    engine = create_engine(database_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
            connection.execute(text("GRANT ALL ON SCHEMA public TO public"))
    finally:
        engine.dispose()


def _drop_ephemeral_database(admin_url: URL, database_name: str) -> None:
    """关闭遗留连接并删除本次 pytest 会话创建的临时数据库。"""

    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as connection:
            connection.exec_driver_sql(
                f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)'
            )
    finally:
        admin_engine.dispose()
