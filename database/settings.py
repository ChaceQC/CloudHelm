"""Explicit database credential loading; no configuration is read on import."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Mapping

from pydantic import SecretStr
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

DatabaseRole = Literal["api", "worker", "migrator"]
MAX_DATABASE_URL_BYTES = 8_192
_URL_QUERY_FIELDS = {"host", "port", "sslmode", "sslrootcert", "sslcert", "sslkey"}


class DatabaseConfigurationError(ValueError):
    """Carries a fixed category, never the supplied credential or driver error."""


def _validate_url(secret: SecretStr) -> None:
    try:
        value = secret.get_secret_value()
        if len(value.encode("utf-8")) > MAX_DATABASE_URL_BYTES:
            raise ValueError
        url = make_url(value)
        if url.drivername not in {"postgresql", "postgresql+psycopg"}:
            raise ValueError
        if not url.database or not url.username:
            raise ValueError
        if set(url.query) - _URL_QUERY_FIELDS:
            raise ValueError
        if any(not isinstance(item, str) or "\n" in item or "\r" in item or "\x00" in item
               for item in url.query.values()):
            raise ValueError
    except (AttributeError, ValueError, TypeError, UnicodeError, SQLAlchemyError):
        raise DatabaseConfigurationError("database_configuration_invalid") from None


@dataclass(frozen=True, slots=True)
class DatabaseSettings:
    role: DatabaseRole
    url: SecretStr = field(repr=False)

    def __post_init__(self) -> None:
        if self.role not in {"api", "worker", "migrator"} or not isinstance(self.url, SecretStr):
            raise DatabaseConfigurationError("database_configuration_invalid")
        _validate_url(self.url)


def load_database_settings(
    role: DatabaseRole, *, environ: Mapping[str, str] | None = None
) -> DatabaseSettings:
    """Read exactly one URL or UTF-8 URL_FILE for the selected process role."""
    if role not in {"api", "worker", "migrator"}:
        raise DatabaseConfigurationError("database_role_invalid")
    values = os.environ if environ is None else environ
    name = f"CLOUDHELM_{role.upper()}_DATABASE_URL"
    direct, reference = values.get(name), values.get(f"{name}_FILE")
    if bool(direct) == bool(reference):
        raise DatabaseConfigurationError("database_credential_source_required")
    try:
        if reference:
            path = Path(reference)
            if path.stat().st_size > MAX_DATABASE_URL_BYTES:
                raise ValueError
            direct = path.read_text(encoding="utf-8").strip()
        return DatabaseSettings(role=role, url=SecretStr(direct or ""))
    except (OSError, ValueError, TypeError, UnicodeError):
        raise DatabaseConfigurationError("database_configuration_invalid") from None
