"""Task row serialization and ordinary progress guards within the caller's UoW."""

from collections.abc import Collection, Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Connection

from database.uow import require_transaction
from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.tables import tasks
from modules.identity.actors import AuthoritativeResource

MAX_REVISION = 9007199254740991


def read_task(connection: Connection, task_id: str, *, for_update: bool = False) -> Mapping[str, Any]:
    require_transaction(connection)
    statement = select(tasks).where(tasks.c.task_id == task_id)
    if for_update:
        statement = statement.with_for_update()
    row = connection.execute(statement).mappings().one_or_none()
    if row is None:
        raise TaskBoundaryError("task_not_found", status_code=404)
    return row


def task_resource(task: Mapping[str, Any]) -> AuthoritativeResource:
    return AuthoritativeResource(task["project_id"], "task", task["task_id"],
                                 revision=task["version"], task_id=task["task_id"])


def check_task_revisions(
    task: Mapping[str, Any], *, expected_version: int, expected_control_revision: int,
    expected_input_validity_revision: int | None = None,
) -> None:
    """Call only after fresh authorization, dedupe and fixed terminal-result branches."""
    revisions = [("version", expected_version, "resource_revision_conflict"),
                 ("control_revision", expected_control_revision, "control_revision_conflict")]
    if expected_input_validity_revision is not None:
        revisions.append(("input_validity_revision", expected_input_validity_revision,
                          "input_validity_revision_conflict"))
    for field, expected, code in revisions:
        if type(expected) is not int or not 0 <= expected <= MAX_REVISION:
            raise TaskBoundaryError("revision_invalid", status_code=422)
        if task[field] != expected:
            raise TaskBoundaryError(code)


def require_ordinary_progress(
    connection: Connection, task_id: str, *, expected_version: int,
    expected_control_revision: int, expected_input_validity_revision: int,
    allowed_states: Collection[str] = ("active",),
) -> Mapping[str, Any]:
    """Caller holds identity/policy locks; this guard acquires the next Task row lock.

    It grants no authentication, model/physical budget, resource or executor capability.
    New intents and input invalidation must retain this lock until their Task version
    condition and owned records commit together through the caller's UnitOfWork.
    """
    task = read_task(connection, task_id, for_update=True)
    if (task["state"] in {"completed", "cancelled"} or task["cancel_requested_at"] is not None
            or task["ordinary_progress_closed"]):
        raise TaskBoundaryError("task_progress_closed")
    if task["state"] == "paused":
        raise TaskBoundaryError("task_paused")
    if task["state"] not in allowed_states:
        raise TaskBoundaryError("task_source_not_allowed")
    check_task_revisions(task, expected_version=expected_version,
                         expected_control_revision=expected_control_revision,
                         expected_input_validity_revision=expected_input_validity_revision)
    if task["input_status"] != "valid":
        raise TaskBoundaryError("input_not_current")
    if max(task["version"], task["control_revision"], task["input_validity_revision"]) == MAX_REVISION:
        raise TaskBoundaryError("revision_exhausted")
    return task
