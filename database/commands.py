"""Persistent command identity/results; authorization remains in the caller's UoW."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

import rfc8785
from sqlalchemy import (
    CheckConstraint, Column, DateTime, ForeignKey, SmallInteger, String, Table,
    UniqueConstraint, func, insert, select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Connection

from database.metadata import BUSINESS_SCHEMA, metadata
from database.uow import DatabaseFailure, require_transaction
from packages.contracts.p0.decision_common import Contract
from packages.contracts.p0.identity_contracts import AuthorizationEnvelope, CommandEnvelope
from packages.contracts.p1.commands import PersistedCommand, contract_payload

commands = Table(
    "commands", metadata,
    Column("command_id", String(160), primary_key=True),
    Column("caller_kind", String(16), nullable=False),
    Column("subject_id", String(160), nullable=False),
    Column("delegator_id", String(160)),
    Column("project_id", String(160), nullable=False),
    Column("resource_kind", String(160), nullable=False),
    Column("resource_id", String(160), nullable=False),
    Column("idempotency_key", String(160), nullable=False),
    Column("request_digest", String(71), nullable=False),
    Column("envelope_json", JSONB, nullable=False),
    Column("status_code", SmallInteger, nullable=False),
    Column("result_json", JSONB, nullable=False),
    Column("audit_session_id", String(160), nullable=False),
    Column("authorization_decision_id", String(160),
           ForeignKey(f"{BUSINESS_SCHEMA}.audit_records.decision_id"), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint(
        "caller_kind", "subject_id", "delegator_id", "project_id", "resource_kind",
        "resource_id", "idempotency_key", name="uq_commands_scope_key",
        postgresql_nulls_not_distinct=True,
    ),
    CheckConstraint("caller_kind IN ('human', 'agent', 'executor')", name="caller_kind"),
    CheckConstraint("status_code >= 200 AND status_code < 500", name="result_status"),
    CheckConstraint("jsonb_typeof(envelope_json) = 'object'", name="envelope_object"),
    CheckConstraint("jsonb_typeof(result_json) = 'object'", name="result_object"),
)


class CommandConflict(ValueError):
    """Stable conflict category, containing no stored result or request body."""


def _scope_values(envelope: CommandEnvelope) -> dict[str, str | None]:
    return {
        "caller_kind": envelope.caller.kind,
        "subject_id": envelope.caller.subject_id,
        "delegator_id": envelope.caller.delegator_id,
        "project_id": envelope.scope.project_id,
        "resource_kind": envelope.scope.resource_kind,
        "resource_id": envelope.scope.resource_id,
        "idempotency_key": envelope.idempotency_key,
    }


def command_lock_key(envelope: CommandEnvelope) -> int:
    identity = {"namespace": "cloudhelm.command.v1", **_scope_values(envelope)}
    try:
        digest = hashlib.sha256(rfc8785.dumps(identity)).digest()
    except (ValueError, TypeError, UnicodeError):
        raise ValueError("command_identity_invalid") from None
    return int.from_bytes(digest[:8], "big", signed=True)


def _stored(row: Mapping[str, Any]) -> PersistedCommand:
    try:
        record = PersistedCommand(
            envelope=row["envelope_json"], status_code=row["status_code"],
            result=row["result_json"], audit_session_id=row["audit_session_id"],
            authorization_decision_id=row["authorization_decision_id"],
        )
        if record.envelope.command_id != row["command_id"]:
            raise ValueError
        if record.envelope.request_digest != row["request_digest"]:
            raise ValueError
        if any(row[name] != value for name, value in _scope_values(record.envelope).items()):
            raise ValueError
        return record
    except (KeyError, ValueError, TypeError):
        raise DatabaseFailure("persisted_command_invalid") from None


def get_by_id(connection: Connection, command_id: str) -> PersistedCommand | None:
    """Internal lookup for actor recovery; reauthorize before exposing the result."""
    require_transaction(connection)
    row = connection.execute(
        select(commands).where(commands.c.command_id == command_id)
    ).mappings().first()
    return None if row is None else _stored(row)


def lock_and_get(
    connection: Connection, envelope: CommandEnvelope
) -> PersistedCommand | None:
    """Call after current authorization; no expected-version check happens here."""
    require_transaction(connection)
    connection.execute(select(func.pg_advisory_xact_lock(command_lock_key(envelope))))
    scope = _scope_values(envelope)
    row = connection.execute(
        select(commands).where(*(commands.c[name] == value for name, value in scope.items()))
    ).mappings().first()
    if row is not None:
        record = _stored(row)
        if record.envelope.request_digest != envelope.request_digest:
            raise CommandConflict("idempotency_digest_conflict")
        return record
    if get_by_id(connection, envelope.command_id) is not None:
        raise CommandConflict("idempotency_scope_mismatch")
    return None


def save_result(
    connection: Connection,
    envelope: CommandEnvelope,
    result: Contract,
    *,
    status_code: int,
    authorization: AuthorizationEnvelope,
) -> None:
    """Save a validated public Contract, including authorized domain rejections."""
    require_transaction(connection)
    for name in ("caller", "scope", "target", "action"):
        if getattr(envelope, name) != getattr(authorization, name):
            raise ValueError("authorization_binding_mismatch")
    if not authorization.allowed:
        raise ValueError("permission_denied")
    payload = contract_payload(result)
    try:
        record = PersistedCommand(
            envelope=envelope, status_code=status_code, result=payload,
            audit_session_id=authorization.audit_session_id,
            authorization_decision_id=authorization.decision_id,
        )
    except ValueError:
        raise ValueError("command_result_invalid") from None
    connection.execute(insert(commands).values(
        command_id=envelope.command_id, **_scope_values(envelope),
        request_digest=envelope.request_digest, envelope_json=envelope.model_dump(mode="json"),
        status_code=record.status_code, result_json=record.result,
        audit_session_id=record.audit_session_id,
        authorization_decision_id=record.authorization_decision_id,
    ))
