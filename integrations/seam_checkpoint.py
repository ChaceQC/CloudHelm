"""Ref-only checkpoint storage and transient inputs for the P0 SDK probe."""

from __future__ import annotations

from hashlib import sha256
from typing import Any, Mapping

import rfc8785
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    MetaData,
    String,
    Table,
    func,
    select,
    update,
    delete,
)
from sqlalchemy.engine import Engine
from sqlalchemy.schema import CreateSchema
from sqlalchemy.dialects.postgresql import insert


SCHEMA = "p0_checkpoint"
TABLE_NAME = "context_references"
REFERENCE_MAX_LENGTH = 512
DIGEST_PREFIX = "sha256:"


class ContextReferences(BaseModel):
    """The complete persisted checkpoint payload: bounded references only."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
    )

    requirement_ref: str = Field(min_length=1, max_length=REFERENCE_MAX_LENGTH)
    input_set_ref: str = Field(min_length=1, max_length=REFERENCE_MAX_LENGTH)
    history_ref: str = Field(min_length=1, max_length=REFERENCE_MAX_LENGTH)
    artifact_ref: str = Field(min_length=1, max_length=REFERENCE_MAX_LENGTH)
    secret_resource_ref: str = Field(min_length=1, max_length=REFERENCE_MAX_LENGTH)


class CheckpointError(RuntimeError):
    """Base class whose message is safe to persist or report."""

    code = "P0_CHECKPOINT_ERROR"

    def __init__(self) -> None:
        super().__init__(self.code)


class InvalidContextReferences(CheckpointError):
    code = "P0_CHECKPOINT_INVALID_REFERENCES"


class CheckpointConflict(CheckpointError):
    code = "P0_CHECKPOINT_ID_DIGEST_CONFLICT"


class CheckpointNotFound(CheckpointError):
    code = "P0_CHECKPOINT_NOT_FOUND"


class CheckpointRetained(CheckpointError):
    code = "P0_CHECKPOINT_STILL_RETAINED"


class CheckpointCorrupt(CheckpointError):
    code = "P0_CHECKPOINT_DIGEST_MISMATCH"


def _canonical(value: Mapping[str, Any]) -> bytes:
    return rfc8785.dumps(dict(value))


def _validated_refs(value: ContextReferences | Mapping[str, Any]) -> ContextReferences:
    try:
        payload = value.model_dump(mode="python") if isinstance(value, ContextReferences) else value
        return ContextReferences.model_validate(payload)
    except (ValidationError, TypeError, ValueError):
        raise InvalidContextReferences() from None


def _reference_mapping(refs: ContextReferences) -> dict[str, str]:
    return refs.model_dump(mode="python")


def _reference_digest(refs: ContextReferences) -> str:
    envelope = {
        "schema_version": "cloudhelm.context-references.v1",
        "references": _reference_mapping(refs),
    }
    try:
        return DIGEST_PREFIX + sha256(_canonical(envelope)).hexdigest()
    except Exception:
        raise InvalidContextReferences() from None


def _checkpoint_id(refs: ContextReferences) -> str:
    # These immutable identity anchors name one saved context snapshot.
    identity = {
        "identity_version": "cloudhelm.checkpoint-id.v1",
        "requirement_ref": refs.requirement_ref,
        "input_set_ref": refs.input_set_ref,
        "history_ref": refs.history_ref,
    }
    try:
        return "cp-" + sha256(_canonical(identity)).hexdigest()
    except Exception:
        raise InvalidContextReferences() from None


_metadata = MetaData()
_context_references = Table(
    TABLE_NAME,
    _metadata,
    Column("checkpoint_id", String(67), primary_key=True),
    Column("request_digest", String(71), nullable=False),
    Column("requirement_ref", String(REFERENCE_MAX_LENGTH), nullable=False),
    Column("input_set_ref", String(REFERENCE_MAX_LENGTH), nullable=False),
    Column("history_ref", String(REFERENCE_MAX_LENGTH), nullable=False),
    Column("artifact_ref", String(REFERENCE_MAX_LENGTH), nullable=False),
    Column("secret_resource_ref", String(REFERENCE_MAX_LENGTH), nullable=False),
    Column("retained", Boolean, nullable=False, server_default="true"),
    Column("terminal", Boolean, nullable=False, server_default="false"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("terminal_at", DateTime(timezone=True), nullable=True),
    schema=SCHEMA,
)


class CheckpointStore:
    """Store immutable, bounded context references outside the DBOS schema."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def bootstrap(self) -> None:
        with self._engine.begin() as connection:
            connection.execute(CreateSchema(SCHEMA, if_not_exists=True))
            _metadata.create_all(connection)

    def put(self, refs: ContextReferences | Mapping[str, Any]) -> str:
        validated = _validated_refs(refs)
        digest = _reference_digest(validated)
        checkpoint_id = _checkpoint_id(validated)
        values = {
            "checkpoint_id": checkpoint_id,
            "request_digest": digest,
            **_reference_mapping(validated),
            "retained": True,
            "terminal": False,
        }
        with self._engine.begin() as connection:
            connection.execute(
                insert(_context_references)
                .values(**values)
                .on_conflict_do_nothing(index_elements=[_context_references.c.checkpoint_id])
            )
            existing = connection.execute(
                select(_context_references.c.request_digest).where(
                    _context_references.c.checkpoint_id == checkpoint_id
                )
            ).scalar_one()
        if existing != digest:
            raise CheckpointConflict()
        return checkpoint_id

    def get(self, checkpoint_id: str) -> ContextReferences:
        with self._engine.connect() as connection:
            row = connection.execute(
                select(_context_references).where(
                    _context_references.c.checkpoint_id == checkpoint_id
                )
            ).mappings().first()
        if row is None:
            raise CheckpointNotFound()
        refs = ContextReferences.model_validate(
            {name: row[name] for name in ContextReferences.model_fields}
        )
        if _reference_digest(refs) != row["request_digest"]:
            raise CheckpointCorrupt()
        return refs

    def mark_terminal(self, checkpoint_id: str) -> None:
        """Release the recovery hold after all referencing work is terminal."""
        with self._engine.begin() as connection:
            result = connection.execute(
                update(_context_references)
                .where(_context_references.c.checkpoint_id == checkpoint_id)
                .values(terminal=True, retained=False, terminal_at=func.now())
            )
            if result.rowcount != 1:
                raise CheckpointNotFound()
    def cleanup(self, checkpoint_id: str) -> None:
        with self._engine.begin() as connection:
            row = connection.execute(
                select(
                    _context_references.c.retained,
                    _context_references.c.terminal,
                )
                .where(_context_references.c.checkpoint_id == checkpoint_id)
                .with_for_update()
            ).first()
            if row is None:
                raise CheckpointNotFound()
            if row.retained or not row.terminal:
                raise CheckpointRetained()
            connection.execute(
                delete(_context_references).where(
                    _context_references.c.checkpoint_id == checkpoint_id
                )
            )
