"""Task completion, cancellation and independent bounded control transitions."""

from datetime import UTC
from uuid import uuid4

from sqlalchemy import case, func, insert, select, update

from modules.collaboration.command_support import (
    command_result, normalized_request, record_event, update_task, visible_blockers,
)
from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.facts import (
    load_cancellation_facts, load_task_control_facts, read_completion_report, read_control_head,
)
from modules.collaboration.guards import check_task_revisions
from modules.collaboration.records import contract_digest
from modules.collaboration.tables import task_completion_reports, task_run_links, task_wait_conditions, work_items
from modules.workflow.dispatch import bind_and_enqueue
from modules.workflow.version import CONTROL_WORKFLOW
from packages.contracts.p0.task_control_contracts import (
    CurrentTaskAccess, TaskCompletionReport, TaskControlCommand, cancellation_readiness, decide_completion,
)
from packages.contracts.p1.commands import WorkflowDispatch
from packages.contracts.p1.task_results import TaskBlocker


def completed_result(context):
    report = read_completion_report(context.uow.connection, context.task)
    if report is None:
        raise TaskBoundaryError("legacy_completion_report_missing")
    return command_result(context, "already_completed", "task_already_completed",
                          original_command_id=report.completion_command.envelope.command_id), 200


def fence_dependents(context) -> None:
    task = context.task
    context.uow.connection.execute(update(task_run_links).where(
        task_run_links.c.task_id == task["task_id"],
    ).values(fenced_control_revision=task["control_revision"]))
    context.uow.connection.execute(update(task_wait_conditions).where(
        task_wait_conditions.c.task_id == task["task_id"],
    ).values(closed_control_revision=task["control_revision"], state=case(
        (task_wait_conditions.c.state == "waiting", "closed"), else_=task_wait_conditions.c.state,
    )))


def _completion_command(context, request):
    _, body = normalized_request(request)
    command = TaskControlCommand(envelope=context.envelope, request=body)
    grant = context.authorization.envelope
    access = CurrentTaskAccess(
        command_id=command.envelope.command_id, caller=grant.caller, scope=grant.scope,
        task_id=context.task["task_id"], action="complete_task",
        authorization_decision_id=grant.decision_id, permission_revision=grant.permission_revision,
        command_allowed=True, report_read_allowed=True,
    )
    return command, access


def _completion_rejection(context, decision, blockers):
    values = list(blockers)
    values.extend(TaskBlocker(code=decision.code, object_kind="operation", object_id=identity)
                  for identity in decision.blocking_operation_ids)
    if not values:
        values.append(TaskBlocker(code=decision.code, object_id=context.task["task_id"]))
    unique = tuple(dict.fromkeys(values))
    if len(unique) > 128:
        raise TaskBoundaryError("task_fact_projection_scope_too_large")
    return command_result(context, decision.outcome, decision.code,
                          blockers=visible_blockers(context, unique)), 409


def complete_task(context, request):
    command, access = _completion_command(context, request)
    decision = decide_completion(command, read_control_head(context.uow.connection, context.task), access)
    snapshot = None
    if decision.outcome == "blocked" and decision.code == "input_not_current":
        snapshot = load_task_control_facts(context.uow.connection, context.task["task_id"])
        decision = decide_completion(command, snapshot.facts, access)
    if decision.outcome == "already_completed":
        return completed_result(context)
    if decision.outcome != "completion_eligible":
        return _completion_rejection(context, decision, snapshot.blockers if snapshot else ())
    report = TaskCompletionReport(
        report_id=uuid4().hex, task_id=context.task["task_id"], completion_command=command,
        committed_version=context.task["version"] + 1,
        committed_control_revision=context.task["control_revision"] + 1,
        committed_at_utc=context.uow.connection.scalar(select(func.clock_timestamp())).astimezone(UTC),
        basis=snapshot.facts.basis,
    )
    update_task(context, state="completed", control_revision=report.committed_control_revision,
                completion_report_id=report.report_id, ordinary_progress_closed=True)
    context.uow.connection.execute(insert(task_completion_reports).values(
        report_id=report.report_id, task_id=report.task_id, command_id=context.envelope.command_id,
        report_json=report.model_dump(mode="json"), report_digest=contract_digest(report),
    ))
    fence_dependents(context)
    result = command_result(context, "completed", "task_completed")
    record_event(context, result, "task.completed")
    return result, 200


def _dispatch_control(context, client):
    workflow_id = "task-control-" + context.envelope.command_id
    bind_and_enqueue(context.uow.connection, client, WorkflowDispatch(
        command_id=context.envelope.command_id, workflow_id=workflow_id, task_id=context.task["task_id"],
        advance_revision=context.task["version"], workflow_name=CONTROL_WORKFLOW,
        request_digest=context.envelope.request_digest,
    ))
    return workflow_id


def cancel_task(context, request, client):
    if context.task["state"] == "completed":
        return completed_result(context)
    if context.task["state"] == "cancelled":
        return command_result(context, "already_cancelled", "task_already_cancelled",
                              original_command_id=context.task["cancel_command_id"]), 200
    if context.task["cancel_requested_at"] is not None:
        cancelled = context.task["state"] == "cancelled"
        return command_result(
            context, "already_cancelled" if cancelled else "cancellation_requested",
            "task_already_cancelled" if cancelled else "cancellation_already_requested",
            original_command_id=context.task["cancel_command_id"], control_purpose="cancellation",
        ), 200 if cancelled else 202
    # Cancellation intentionally does not require valid input, a candidate or acceptance.
    check_task_revisions(context.task, expected_version=request.expected_version,
                         expected_control_revision=request.expected_control_revision)
    TaskControlCommand(envelope=context.envelope, request=normalized_request(request)[1])
    revision = context.task["control_revision"] + 1
    update_task(
        context, control_revision=revision, ordinary_progress_closed=True,
        cancel_command_id=context.envelope.command_id, cancel_control_revision=revision,
        cancel_requested_at=context.uow.connection.scalar(select(func.clock_timestamp())),
        cancel_requested_by=context.actor.principal.model_dump(mode="json"), cancel_reason=request.cancel_reason,
    )
    fence_dependents(context)
    workflow_id = _dispatch_control(context, client)
    result = command_result(context, "cancellation_requested", "cancellation_requested",
                            workflow_id=workflow_id, control_purpose="cancellation")
    record_event(context, result, "task.cancellation_requested")
    return result, 202


def reconcile_task(context, request, client):
    if context.task["state"] == "completed":
        return completed_result(context)
    if context.task["state"] == "cancelled":
        return command_result(context, "already_cancelled", "task_already_cancelled",
                              original_command_id=context.task["cancel_command_id"]), 200
    check_task_revisions(context.task, expected_version=request.expected_version,
                         expected_control_revision=request.expected_control_revision)
    if request.purpose == "cancellation" and context.task["cancel_requested_at"] is None:
        raise TaskBoundaryError("cancel_intent_missing")
    if request.purpose == "completion" and context.task["cancel_requested_at"] is not None:
        raise TaskBoundaryError("task_progress_closed")
    update_task(context)
    workflow_id = _dispatch_control(context, client)
    result = command_result(context, "reconciliation_requested", "task_control_inspection_requested",
                            workflow_id=workflow_id, control_purpose=request.purpose)
    record_event(context, result, "task.control_inspection_requested")
    return result, 202


def advance_control(context, request):
    if context.task["state"] == "completed":
        return completed_result(context)
    if context.task["state"] == "cancelled":
        return command_result(context, "already_cancelled", "task_already_cancelled",
                              original_command_id=context.task["cancel_command_id"]), 200
    check_task_revisions(context.task, expected_version=request.expected_version,
                         expected_control_revision=request.expected_control_revision)
    if request.purpose == "cancellation":
        return _advance_cancellation(context, request)
    snapshot = load_task_control_facts(context.uow.connection, context.task["task_id"])
    result = command_result(context, "blocked" if snapshot.blockers else "reconciled",
                            "task_control_blocked" if snapshot.blockers else "task_control_inspected",
                            blockers=visible_blockers(context, snapshot.blockers))
    # Inspection cannot stand in for an explicit complete_task command.
    return result, 200


def _advance_cancellation(context, request):
    facts = load_cancellation_facts(context.uow.connection, context.task["task_id"])
    decision = cancellation_readiness(facts)
    if decision.outcome != "cancellation_eligible":
        blockers = tuple(TaskBlocker(code=decision.code, object_kind="operation", object_id=identity)
                         for identity in decision.blocking_operation_ids)
        if not blockers:
            blockers = (TaskBlocker(code=decision.code, object_id=context.task["task_id"]),)
        return command_result(context, "blocked", decision.code,
                              blockers=visible_blockers(context, blockers)), 200
    update_task(context, state="cancelled")
    context.uow.connection.execute(update(work_items).where(
        work_items.c.task_id == context.task["task_id"],
        work_items.c.state.not_in(("accepted", "failed", "cancelled")),
    ).values(state="cancelled", blocked_reason=None))
    result = command_result(context, "cancelled", "task_cancelled",
                            original_command_id=context.task["cancel_command_id"])
    record_event(context, result, "task.cancelled", source_command_id=request.source_command_id)
    return result, 200
