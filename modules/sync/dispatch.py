"""Serialized bounded dispatch of committed Outbox facts in the caller's UoW."""

from uuid import uuid4

from sqlalchemy import func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from modules.collaboration.errors import TaskBoundaryError
from modules.sync.tables import dispatch_events, event_log, outbox, streams
from packages.contracts.p1.sync import SyncBatch, SyncEvent


def stream_head(connection, project_id, *, lock=False):
    connection.execute(pg_insert(streams).values(project_id=project_id, stream_id=uuid4().hex)
                       .on_conflict_do_nothing(index_elements=[streams.c.project_id]))
    statement = select(streams).where(streams.c.project_id == project_id)
    if lock:
        statement = statement.with_for_update()
    return connection.execute(statement).mappings().one()


def public_stream_id(head, epoch):
    # API restarts (including an old-backup restore) invalidate old live cursors.
    return head["stream_id"] + "." + epoch


def dispatch_pending(connection, head):
    pending = connection.execute(select(outbox.c.event_id).join(
        event_log, outbox.c.event_id == event_log.c.event_id,
    ).where(event_log.c.project_id == head["project_id"], outbox.c.dispatched_at.is_(None))
        .order_by(outbox.c.created_at, outbox.c.event_id).limit(32)).scalars().all()
    cursor = head["last_cursor"]
    if cursor + len(pending) > 9007199254740991:
        raise TaskBoundaryError("sync_cursor_exhausted")
    for event_id in pending:
        cursor += 1
        connection.execute(insert(dispatch_events).values(
            project_id=head["project_id"], cursor=cursor, event_id=event_id))
        connection.execute(update(outbox).where(outbox.c.event_id == event_id).values(dispatched_at=func.now()))
    if pending:
        connection.execute(update(streams).where(streams.c.project_id == head["project_id"]).values(last_cursor=cursor))
    return cursor


def read_batch(connection, project_id, head, epoch, after):
    rows = connection.execute(select(
        dispatch_events.c.cursor, event_log.c.event_id, event_log.c.project_id,
        event_log.c.aggregate_kind, event_log.c.aggregate_id, event_log.c.aggregate_version,
        event_log.c.event_type, event_log.c.schema_version,
    ).join(event_log, dispatch_events.c.event_id == event_log.c.event_id).where(
        dispatch_events.c.project_id == project_id, dispatch_events.c.cursor > after,
    ).order_by(dispatch_events.c.cursor).limit(32)).mappings().all()
    events = tuple(SyncEvent(**row) for row in rows)
    return SyncBatch(stream_id=public_stream_id(head, epoch),
                     cursor=events[-1].cursor if events else after, events=events)
