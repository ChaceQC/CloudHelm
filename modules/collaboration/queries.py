"""Current authorized Task views, keeping fixed reports separate from fresh acceptance."""

from sqlalchemy import select

from modules.collaboration.command_support import visible_blockers
from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.fact_reads import FactReader, bounded_rows
from modules.collaboration.facts import (
    project_cancellation_facts, project_task_control_facts, read_control_head, read_declaration,
)
from modules.collaboration.records import reference_key
from modules.collaboration.tables import work_items
from packages.contracts.p0.task_control_contracts import cancellation_readiness
from packages.contracts.p1.task_results import TaskBlocker, TaskView, WorkItemView


def _control_blockers(context, declaration, head):
    task = context.task
    if task["state"] in {"completed", "cancelled"}:
        return ()
    if task["cancel_requested_at"] is not None:
        decision = cancellation_readiness(project_cancellation_facts(context.uow.connection, task, head))
        if decision.outcome == "cancellation_eligible":
            return ()
        blocks = tuple(TaskBlocker(code=decision.code, object_kind="operation", object_id=identity)
                       for identity in decision.blocking_operation_ids)
        return blocks or (TaskBlocker(code=decision.code, object_id=task["task_id"]),)
    return project_task_control_facts(context.uow.connection, task, declaration, head).blockers


def task_view(context) -> TaskView:
    task = context.task
    declaration = read_declaration(context.uow.connection, task)
    head = read_control_head(context.uow.connection, task)
    reader = FactReader(context.uow.connection, task["project_id"], task["task_id"])
    rows = bounded_rows(context.uow.connection, select(work_items).where(
        work_items.c.task_id == task["task_id"],
    ).order_by(work_items.c.work_item_id), "work_items_scope_too_large")
    frozen = head.completion_report.basis.input_set_ref if head.completion_report else None
    items = []
    for row in rows:
        accepted_ref = None
        key = row["accepted_input_set_key"]
        if key is not None and frozen is not None and reference_key(task["project_id"], frozen) == key:
            accepted_ref = frozen
        elif key is not None and task["state"] not in {"completed", "cancelled"}:
            record = reader.read(key, "input_set")
            accepted_ref = record.reference if record else None
        items.append(WorkItemView(
            work_item_id=row["work_item_id"], revision=row["revision"], state=row["state"],
            required=row["required"], goal=row["goal"], blocked_reason=row["blocked_reason"],
            accepted_input_set_ref=accepted_ref,
        ))
    blockers = tuple(dict.fromkeys((*_control_blockers(context, declaration, head), *reader.blockers)))
    if len(blockers) > 128:
        raise TaskBoundaryError("task_fact_projection_scope_too_large")
    return TaskView(
        task_id=task["task_id"], project_id=task["project_id"], state=task["state"], version=task["version"],
        control_revision=task["control_revision"], input_validity_revision=task["input_validity_revision"],
        declaration=declaration, cancellation=head.cancellation, completion_report_id=task["completion_report_id"],
        input_status=task["input_status"], ordinary_progress_closed=task["ordinary_progress_closed"],
        work_items=tuple(items), blockers=visible_blockers(context, blockers),
    )
