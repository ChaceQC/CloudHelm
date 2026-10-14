"""Caller-owned short transactions shared by all participating domain services."""

from __future__ import annotations

from contextlib import AbstractContextManager
from types import TracebackType
from typing import Self

from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError


class DatabaseFailure(RuntimeError):
    """Safe technical category; raw driver errors never cross the service boundary."""


class UnitOfWork:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._context: AbstractContextManager[Connection] | None = None
        self._connection: Connection | None = None

    @property
    def connection(self) -> Connection:
        if self._connection is None:
            raise RuntimeError("unit_of_work_not_active")
        return self._connection

    def __enter__(self) -> Self:
        if self._context is not None:
            raise RuntimeError("unit_of_work_already_active")
        context = self._engine.begin()
        try:
            self._connection = context.__enter__()
        except SQLAlchemyError:
            raise DatabaseFailure("database_unavailable") from None
        self._context = context
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._context is None:
            raise RuntimeError("unit_of_work_not_active")
        try:
            self._context.__exit__(exc_type, exc, traceback)
        except SQLAlchemyError:
            code = "database_commit_unconfirmed" if exc is None else "database_rollback_failed"
            raise DatabaseFailure(code) from None
        finally:
            self._context = None
            self._connection = None
        if isinstance(exc, SQLAlchemyError):
            raise DatabaseFailure("database_operation_failed") from None


def require_transaction(connection: Connection) -> None:
    if not connection.in_transaction():
        raise RuntimeError("caller_owned_transaction_required")
