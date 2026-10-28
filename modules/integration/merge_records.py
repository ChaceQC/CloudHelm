"""Read exact queue facts; current queue state never rewrites past attempts."""

from sqlalchemy import select, update

from modules.collaboration.errors import TaskBoundaryError
from modules.integration.merge_tables import merge_queue
from modules.sync.tables import event_log
from packages.contracts.p2.merge_queue import IntegrationAttempt, IntegrationReview, MergeQueueEntry


def read_entry(connection, entry_id, *, for_update=False):
    statement = select(merge_queue.c.record_json).where(merge_queue.c.entry_id == entry_id)
    payload = connection.scalar(statement.with_for_update() if for_update else statement)
    if payload is None:
        raise TaskBoundaryError("merge_entry_not_found", status_code=404)
    return MergeQueueEntry.model_validate(payload)


def save_entry(connection, entry, **values):
    changed = MergeQueueEntry.model_validate(entry.model_copy(update=values).model_dump())
    connection.execute(update(merge_queue).where(merge_queue.c.entry_id == entry.entry_id).values(
        state=changed.state, record_json=changed.model_dump(mode="json")))
    return changed


def read_attempt(connection, attempt_id):
    payload = connection.scalar(select(event_log.c.payload).where(
        event_log.c.event_id == attempt_id, event_log.c.event_type == "integration.prepared"))
    return IntegrationAttempt.model_validate(payload) if payload is not None else None


def read_review(connection, review_id):
    payload = connection.scalar(select(event_log.c.payload).where(
        event_log.c.event_id == review_id, event_log.c.event_type == "integration.reviewed"))
    return IntegrationReview.model_validate(payload) if payload is not None else None


def queue_head(connection, project_id):
    entry_id = connection.scalar(select(merge_queue.c.entry_id).where(
        merge_queue.c.project_id == project_id, merge_queue.c.state.not_in(("merged", "withdrawn")),
    ).order_by(merge_queue.c.position).limit(1))
    return None if entry_id is None else read_entry(connection, entry_id)


def entry_for_attempt(connection, attempt_id):
    entry_id = connection.scalar(select(merge_queue.c.entry_id).where(
        merge_queue.c.record_json["attempt_id"].astext == attempt_id))
    if entry_id is None:
        raise TaskBoundaryError("integration_attempt_not_current")
    return read_entry(connection, entry_id)
