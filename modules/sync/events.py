"""Append a public domain event and its Outbox record in one caller-owned UoW."""

from uuid import uuid4

from sqlalchemy import insert
from sqlalchemy.engine import Connection

from database.uow import require_transaction
from modules.sync.tables import event_log, outbox
from packages.contracts.p0.decision_common import Contract
from packages.contracts.p1.commands import EventEnvelope, contract_payload


def append_event(
    connection: Connection,
    *,
    command_id: str,
    project_id: str,
    aggregate_kind: str,
    aggregate_id: str,
    aggregate_version: int,
    event_type: str,
    schema_version: str,
    payload: Contract,
    event_id: str | None = None,
) -> str:
    """Event IDs are facts, not delivery cursors; no external delivery occurs here."""
    require_transaction(connection)
    public_payload = contract_payload(payload)
    try:
        event = EventEnvelope(
            event_id=event_id if event_id is not None else uuid4().hex,
            command_id=command_id, project_id=project_id,
            aggregate_kind=aggregate_kind, aggregate_id=aggregate_id,
            aggregate_version=aggregate_version, event_type=event_type,
            schema_version=schema_version, payload=public_payload,
        )
    except ValueError:
        raise ValueError("event_envelope_invalid") from None
    connection.execute(insert(event_log).values(**event.model_dump(mode="json")))
    connection.execute(insert(outbox).values(event_id=event.event_id))
    return event.event_id
