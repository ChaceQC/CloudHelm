"""Read-only, bounded diagnostics for the isolated P0 environment."""

import json
import os
import platform
import subprocess
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import psycopg


def command(*args: str) -> str | dict:
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, encoding="utf-8", timeout=10,
            env={**os.environ, "LANG": "C.UTF-8"}, check=False,
        )
        if result.returncode:
            return {"available": False, "exit_code": result.returncode}
        return result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"available": False, "error_type": type(error).__name__}


def database() -> dict:
    try:
        with psycopg.connect(
            host="127.0.0.1", port=55432, user="cloudhelm_probe",
            dbname="cloudhelm_p0", connect_timeout=3,
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_setting('server_version')")
                server_version = cursor.fetchone()[0]
                cursor.execute("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()")
                connections = cursor.fetchone()[0]
        return {"reachable": True, "version": server_version, "connections": connections}
    except psycopg.Error as error:
        return {"reachable": False, "error_type": type(error).__name__}


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    os.chdir(root)
    packages = (
        "dbos", "pydantic-ai-slim", "openai", "pydantic", "SQLAlchemy",
        "psycopg", "fastapi", "alembic", "httpx", "PyYAML", "rfc8785",
    )
    result = {
        "observed_at": datetime.now(UTC).isoformat(),
        "scope": "isolated-p0-wsl; no product or native desktop acceptance",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "repository": str(root),
        "git_head": command("git", "rev-parse", "HEAD"),
        "packages": {name: version(name) for name in packages},
        "uv": command("uv", "--version"),
        "git": command("git", "--version"),
        "docker": command("docker", "version", "--format", "{{.Client.Version}}/{{.Server.Version}}"),
        "compose": command("docker", "compose", "version", "--short"),
        "buildx": command("docker", "buildx", "version"),
        "node": command("node", "--version"),
        "npm": command("npm", "--version"),
        "rustc": command("rustc", "--version"),
        "cargo": command("cargo", "--version"),
        "database": database(),
        "credentials": "not inspected",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
