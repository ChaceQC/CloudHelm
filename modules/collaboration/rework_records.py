"""Immutable rework facts on the existing event stream, projected when consumed."""

from sqlalchemy import select

from modules.collaboration.errors import TaskBoundaryError
from modules.integration.rework_resolution import resolution_is_current
from modules.sync.tables import event_log
from packages.contracts.p2.rework import ReworkIssue


def read_rework_issues(connection, task, *, work_item_id=None):
    query = select(event_log.c.payload).where(
        event_log.c.project_id == task["project_id"],
        event_log.c.event_type == "rework.issue_received",
        event_log.c.payload["task_id"].astext == task["task_id"],
    )
    if work_item_id is not None:
        query = query.where(event_log.c.payload["work_item_id"].astext == work_item_id)
    rows = connection.scalars(query.order_by(event_log.c.event_id).limit(129)).all()
    if len(rows) > 128:
        raise TaskBoundaryError("rework_projection_scope_too_large")
    return [ReworkIssue.model_validate(row) for row in rows]


def latest_resolution(connection, task, issue_id):
    return connection.scalar(select(event_log.c.payload).where(
        event_log.c.project_id == task["project_id"],
        event_log.c.aggregate_kind == "rework_issue",
        event_log.c.aggregate_id == issue_id,
        event_log.c.event_type == "rework.issue_resolved",
    ).order_by(event_log.c.aggregate_version.desc()).limit(1))


def rework_view(connection, task, *, work_item_id=None):
    result = []
    for issue in read_rework_issues(connection, task, work_item_id=work_item_id):
        closed = latest_resolution(connection, task, issue.issue_id)
        current = closed is not None and resolution_is_current(connection, task, closed["resolution"])
        result.append({**issue.model_dump(mode="json"),
            "state": "resolved" if current else "needs_review" if closed else "open",
            "resolution": closed["resolution"] if closed else None})
    return result


def unresolved_rework(connection, task, *, work_item_id=None):
    return [issue for issue in rework_view(connection, task, work_item_id=work_item_id)
            if issue["state"] != "resolved"]
