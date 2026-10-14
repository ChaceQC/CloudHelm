"""Bounded process pools; control work never borrows the ordinary request pool."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import SQLAlchemyError

from database.settings import DatabaseConfigurationError, DatabaseSettings

PoolPurpose = Literal["normal", "control", "dbos", "maintenance"]
POOL_SIZES: dict[PoolPurpose, int] = {"normal": 2, "control": 1, "dbos": 4, "maintenance": 2}
DBOS_LISTENER_CONNECTIONS = 1


def create_engine_from_settings(
    settings: DatabaseSettings, *, purpose: PoolPurpose = "normal"
) -> Engine:
    if purpose not in POOL_SIZES or (purpose == "dbos" and settings.role != "worker"):
        raise DatabaseConfigurationError("database_pool_purpose_invalid")
    if (purpose == "maintenance") != (settings.role == "migrator"):
        raise DatabaseConfigurationError("database_pool_role_mismatch")
    try:
        url = make_url(settings.url.get_secret_value()).set(drivername="postgresql+psycopg")
        return create_engine(
            url,
            pool_size=POOL_SIZES[purpose],
            max_overflow=0,
            pool_timeout=5,
            pool_pre_ping=True,
            isolation_level="READ COMMITTED",
            hide_parameters=True,
            echo=False,
            json_serializer=lambda value: json.dumps(value, ensure_ascii=False, allow_nan=False),
            connect_args={
                "application_name": f"cloudhelm_{settings.role}_{purpose}",
                "connect_timeout": 5,
                "options": (
                    "-c timezone=UTC -c statement_timeout=10000 -c lock_timeout=3000 "
                    "-c idle_in_transaction_session_timeout=15000"
                ),
            },
        )
    except (ValueError, TypeError, SQLAlchemyError):
        raise DatabaseConfigurationError("database_engine_configuration_invalid") from None


@dataclass(frozen=True, slots=True)
class BusinessPools:
    normal: Engine = field(repr=False)
    control: Engine = field(repr=False)

    def dispose(self) -> None:
        self.control.dispose()
        self.normal.dispose()


def create_business_pools(settings: DatabaseSettings) -> BusinessPools:
    if settings.role not in {"api", "worker"}:
        raise DatabaseConfigurationError("database_runtime_role_required")
    normal = create_engine_from_settings(settings, purpose="normal")
    try:
        return BusinessPools(normal, create_engine_from_settings(settings, purpose="control"))
    except BaseException:
        normal.dispose()
        raise
