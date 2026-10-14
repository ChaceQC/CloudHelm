"""A reusable WSL-only real PostgreSQL fixture with private, disposable credentials."""

from __future__ import annotations

import os
import re
import secrets
import shutil
import socket
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator
from uuid import uuid4

import psycopg
from psycopg import sql
from pydantic import SecretStr
from sqlalchemy.engine import URL

from database.maintenance import initialize_database
from database.permissions import DBOS_RUNTIME_ROLE
from database.readiness import ROLE_CONNECTION_LIMITS, ROLE_NAMES, RuntimeBaseline
from database.settings import DatabaseRole, DatabaseSettings, load_database_settings

_ROOT = Path(__file__).resolve().parents[2]
_RUNTIME_ROOT = Path("/home/cloudhelm/.local/state/cloudhelm/p1-fixtures")
_COMPOSE = _ROOT / "infra/p1/compose.yaml"
_DOCKER_SOCKET = "unix:///var/run/docker.sock"


class DatabaseFixtureError(RuntimeError):
    """Fixed category only; subprocess/driver output may contain private material."""

    public_diagnostic: str | None = None


@dataclass(frozen=True, slots=True)
class DatabaseFixture:
    project_name: str
    port: int
    runtime_dir: Path = field(repr=False)
    baseline: RuntimeBaseline | None

    def environment_for(self, role: DatabaseRole) -> dict[str, str]:
        if role not in ROLE_NAMES:
            raise DatabaseFixtureError("fixture_role_invalid")
        return {f"CLOUDHELM_{role.upper()}_DATABASE_URL_FILE": str(self.runtime_dir / f"{role}_database_url")}

    def settings(self, role: DatabaseRole) -> DatabaseSettings:
        return load_database_settings(role, environ=self.environment_for(role))


def _private_file(path: Path, value: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as target:
        target.write(value)
        target.flush()
        os.fsync(target.fileno())


def _runtime_directory() -> Path:
    if os.environ.get("WSL_DISTRO_NAME") != "Ubuntu-24.04" or os.name != "posix":
        raise DatabaseFixtureError("fixture_requires_wsl_ubuntu_24_04")
    if not Path("/var/run/docker.sock").is_socket():
        raise DatabaseFixtureError("local_docker_socket_required")
    _RUNTIME_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    state = _RUNTIME_ROOT.stat()
    if state.st_uid != os.getuid() or state.st_mode & 0o077:
        raise DatabaseFixtureError("fixture_runtime_permissions_invalid")
    return Path(tempfile.mkdtemp(prefix="instance-", dir=_RUNTIME_ROOT))


def _check_port(port: int) -> None:
    if not isinstance(port, int) or isinstance(port, bool) or not 1024 <= port <= 65535:
        raise DatabaseFixtureError("fixture_port_invalid")
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", port))
    except OSError:
        raise DatabaseFixtureError("fixture_port_in_use") from None


def _docker_diagnostic(fixture: DatabaseFixture, message: str) -> str:
    from sqlalchemy.engine import make_url

    for filename in ("bootstrap_password", "api_database_url", "worker_database_url", "migrator_database_url"):
        source = fixture.runtime_dir / filename
        if source.is_file():
            private = source.read_text(encoding="utf-8")
            message = message.replace(private, "[private]")
            if filename != "bootstrap_password":
                password = make_url(private).password
                if password:
                    message = message.replace(password, "[private]")
    message = re.sub(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s\"']+", "[endpoint]", message)
    message = re.sub(r"(?i)(password|token|authorization)\s*[:=]\s*\S+", r"\1=[private]", message)
    return message[-1600:].strip()


def _compose(fixture: DatabaseFixture, *arguments: str) -> None:
    command = [
        "docker", "--host", _DOCKER_SOCKET, "compose", "--project-name", fixture.project_name,
        "--env-file", str(fixture.runtime_dir / "compose.env"), "--file", str(_COMPOSE), *arguments,
    ]
    try:
        result = subprocess.run(command, cwd=_ROOT, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise DatabaseFixtureError("fixture_docker_unavailable") from None
    if result.returncode != 0:
        code = "fixture_cleanup_failed" if arguments[0] == "down" else "fixture_start_failed"
        if arguments[0] != "down":
            diagnostics = (result.stdout + result.stderr).lower()
            categories = (
                ("permission denied", "fixture_docker_permission_denied"),
                ("port is already allocated", "fixture_port_in_use"),
                ("address already in use", "fixture_port_in_use"),
                ("invalid mount", "fixture_mount_invalid"),
                ("invalid volume", "fixture_mount_invalid"),
                ("is not shared", "fixture_mount_not_shared"),
                ("no such file or directory", "fixture_path_missing"),
                ("cannot connect", "fixture_docker_unavailable"),
                ("unhealthy", "fixture_database_unhealthy"),
                ("exited", "fixture_database_exited"),
                ("unknown flag", "fixture_docker_cli_mismatch"),
            )
            code = next((reason for fragment, reason in categories if fragment in diagnostics), code)
        failure = DatabaseFixtureError(code)
        failure.public_diagnostic = _docker_diagnostic(fixture, result.stdout + result.stderr)
        raise failure


def _credentials(fixture: DatabaseFixture) -> SecretStr:
    bootstrap = SecretStr(secrets.token_urlsafe(32))
    _private_file(fixture.runtime_dir / "bootstrap_password", bootstrap.get_secret_value())
    for role, name in ROLE_NAMES.items():
        url = URL.create("postgresql+psycopg", username=name, password=secrets.token_urlsafe(32),
                         host="127.0.0.1", port=fixture.port, database="cloudhelm")
        _private_file(fixture.runtime_dir / f"{role}_database_url", url.render_as_string(hide_password=False))
    _private_file(fixture.runtime_dir / "compose.env", (
        f"CLOUDHELM_P1_PORT={fixture.port}\nCLOUDHELM_P1_RUNTIME_DIR={fixture.runtime_dir}\n"
    ))
    return bootstrap


def _bootstrap_roles(fixture: DatabaseFixture, password: SecretStr) -> None:
    from sqlalchemy.engine import make_url

    url = URL.create("postgresql", username="cloudhelm_fixture_admin", password=password.get_secret_value(),
                     host="127.0.0.1", port=fixture.port, database="cloudhelm")
    try:
        with psycopg.connect(url.render_as_string(hide_password=False), autocommit=True, connect_timeout=5) as connection:
            connection.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(DBOS_RUNTIME_ROLE)))
            for role, name in ROLE_NAMES.items():
                protected = fixture.settings(role)
                role_password = make_url(protected.url.get_secret_value()).password
                connection.execute(sql.SQL(
                    "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                    "NOREPLICATION NOBYPASSRLS CONNECTION LIMIT {} PASSWORD {}"
                ).format(sql.Identifier(name), sql.Literal(ROLE_CONNECTION_LIMITS[role]), sql.Literal(role_password)))
            connection.execute("REVOKE ALL ON DATABASE cloudhelm FROM PUBLIC")
            connection.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            connection.execute("ALTER DATABASE cloudhelm OWNER TO cloudhelm_migrator")
            connection.execute("GRANT CONNECT ON DATABASE cloudhelm TO cloudhelm_api, cloudhelm_worker")
            connection.execute(sql.SQL("GRANT {} TO cloudhelm_api, cloudhelm_worker").format(sql.Identifier(DBOS_RUNTIME_ROLE)))
    except Exception:
        raise DatabaseFixtureError("fixture_role_bootstrap_failed") from None


def _remove_runtime(directory: Path) -> None:
    resolved = directory.resolve()
    root = _RUNTIME_ROOT.resolve()
    if resolved.parent != root or not resolved.name.startswith("instance-"):
        raise DatabaseFixtureError("fixture_cleanup_path_invalid")
    shutil.rmtree(resolved)


@contextmanager
def database_fixture(*, port: int = 55433, initialize: bool = True) -> Iterator[DatabaseFixture]:
    """Yield protected role settings; remove only this unique project and runtime directory."""
    _check_port(port)
    runtime_dir = _runtime_directory()
    fixture = DatabaseFixture(f"cloudhelm-p1-{uuid4().hex[:12]}", port, runtime_dir, None)
    docker_attempted = False
    cleanup_ok = False
    try:
        bootstrap = _credentials(fixture)
        docker_attempted = True
        _compose(fixture, "up", "--detach", "--wait", "--wait-timeout", "45")
        _bootstrap_roles(fixture, bootstrap)
        baseline = initialize_database(fixture.settings("migrator")) if initialize else None
        fixture = DatabaseFixture(fixture.project_name, port, runtime_dir, baseline)
        yield fixture
    finally:
        try:
            if docker_attempted:
                _compose(fixture, "down", "--remove-orphans", "--volumes", "--timeout", "10")
            cleanup_ok = True
        finally:
            # Keep private recovery material if the container's stop is unconfirmed.
            if cleanup_ok:
                _remove_runtime(runtime_dir)
