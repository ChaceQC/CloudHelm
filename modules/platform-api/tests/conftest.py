"""M2 API 测试夹具。

测试通过真实 PostgreSQL 和 Alembic 迁移验证，不在生产代码路径引入
mock/stub/fake。默认数据库地址与 `infra/docker-compose.dev.yml` 保持一致。
"""

import os
from collections.abc import Generator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from cloudhelm_platform_api.core.config import get_settings
from cloudhelm_platform_api.db.session import get_engine, reset_engine_cache
from cloudhelm_platform_api.main import create_app

DEFAULT_TEST_DATABASE_URL = "postgresql+psycopg://cloudhelm:cloudhelm_dev@127.0.0.1:15432/cloudhelm"
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> Generator[None, None, None]:
    """重建测试数据库 schema 并执行 Alembic 迁移。"""

    database_url = os.environ.get("CLOUDHELM_TEST_DATABASE_URL") or os.environ.get(
        "CLOUDHELM_DATABASE_URL",
        DEFAULT_TEST_DATABASE_URL,
    )
    os.environ["CLOUDHELM_DATABASE_URL"] = database_url
    os.environ["CLOUDHELM_ENV"] = "test"
    os.environ["CLOUDHELM_VERSION"] = "0.2.0"
    get_settings.cache_clear()
    reset_engine_cache()

    admin_engine = create_engine(database_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
        connection.execute(text("GRANT ALL ON SCHEMA public TO public"))
    admin_engine.dispose()

    alembic_config = Config(str(ROOT / "alembic.ini"))
    command.upgrade(alembic_config, "head")
    yield

    reset_engine_cache()
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def clean_business_tables(migrated_database: None) -> Generator[None, None, None]:
    """每个测试前清空业务表，保留 Alembic 版本表。"""

    with get_engine().begin() as connection:
        connection.execute(
            text(
                """
                TRUNCATE TABLE
                  event_logs,
                  tool_calls,
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
            "description": "通过真实数据库验证任务写入和事件副作用。",
            "source_type": "manual",
            "risk_level": "L1",
            "created_by": "tester",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()
