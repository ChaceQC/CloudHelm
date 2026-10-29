"""Feedback -> original developer work item -> new, evidenced rework closure."""

from hashlib import sha256
from uuid import uuid4

from sqlalchemy import func, select, update

from database.commands import get_by_id, lock_and_get, save_result
from database.uow import UnitOfWork
from modules.collaboration.command_support import TaskCommandContext, lock_task_access, update_task
from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.guards import MAX_REVISION, require_ordinary_progress, task_resource
from modules.collaboration.rework_records import read_rework_issues, rework_view
from modules.collaboration.tables import work_items
from modules.identity.actors import actor_for_command
from modules.integration.rework_resolution import verify_rework_resolution_in_uow
from modules.integration.rework_sources import load_feedback_source
from modules.sync.events import append_event
from modules.sync.tables import event_log
from packages.contracts.p0.identity_contracts import CommandEnvelope, CommandIntent, request_digest
from packages.contracts.p2.rework import (
    REWORK_SCHEMA, ReceiveReworkRequest, ReworkIssue, ReworkReceipt,
    ReworkResolutionEvent, ReworkResolutionReceipt,
)


def receive_feedback_in_uow(context, *, source_run_id=None, verification_report_id=None):
    """The caller owns Task authorization, ordinary-progress admission and transaction."""
    uow, task = context.uow, context.task
    source = load_feedback_source(uow, context.actor, task, source_run_id=source_run_id,
                                  verification_report_id=verification_report_id)
    previous = read_rework_issues(uow.connection, task)
    existing_ids = {issue.issue_id for issue in previous}
    common = {key: source[key] for key in (
        "source_id", "source_kind", "candidate_id", "candidate_commit", "source_input_set_ref",
        "evidence_refs", "work_item_id", "owner_session_id", "control_revision", "input_validity_revision")}
    issues = []
    for index, finding in enumerate(source["issues"]):
        identity = f"{source['source_kind']}:{source['source_id']}:{index}"
        issue_id = "rework-issue-" + sha256(identity.encode("utf-8")).hexdigest()
        recurrence = tuple(issue.issue_id for issue in previous
            if issue.work_item_id == source["work_item_id"] and issue.fingerprint == finding["fingerprint"]
            and issue.source_id != source["source_id"])
        issues.append(ReworkIssue(**{**common, **finding, "issue_id": issue_id,
            "task_id": task["task_id"], "previous_issue_ids": recurrence}))
    new = [issue for issue in issues if issue.issue_id not in existing_ids]
    if len(previous) + len(new) > 128:
        raise TaskBoundaryError("rework_projection_scope_too_large")
    if new:
        if any(issue.severity == "blocking" for issue in new):
            item = uow.connection.execute(select(work_items).where(
                work_items.c.task_id == task["task_id"],
                work_items.c.work_item_id == source["work_item_id"]).with_for_update()).mappings().one()
            if item["revision"] == MAX_REVISION:
                raise TaskBoundaryError("revision_exhausted")
            uow.connection.execute(update(work_items).where(
                work_items.c.work_item_id == item["work_item_id"]).values(
                state="ready", revision=item["revision"] + 1, required=True, blocked_reason=None,
                accepted_input_set_key=None, acceptance_evidence_key=None))
        update_task(context)
        for issue in new:
            append_event(uow.connection, command_id=context.envelope.command_id,
                project_id=task["project_id"], aggregate_kind="rework_issue", aggregate_id=issue.issue_id,
                aggregate_version=1, event_type="rework.issue_received", schema_version=REWORK_SCHEMA,
                event_id=issue.issue_id, payload=issue)
    return ReworkReceipt(command_id=context.envelope.command_id, task_id=task["task_id"],
        version=context.task["version"], source_id=source["source_id"],
        issue_ids=tuple(issue.issue_id for issue in issues), work_item_id=source["work_item_id"],
        owner_session_id=source["owner_session_id"])


def receive_run_feedback_in_uow(uow, run_id, source_command_id):
    """Join the Run result transaction, so a crash cannot lose the developer notification."""
    from modules.agent_runtime.tables import agent_sessions, agent_runs

    task_id = uow.connection.scalar(select(agent_sessions.c.task_id).join(agent_runs).where(
        agent_runs.c.run_id == run_id))
    actor = actor_for_command(uow, source_command_id)
    task, authorization = lock_task_access(uow, actor, task_id, "task.command")
    require_ordinary_progress(uow.connection, task_id, expected_version=task["version"],
        expected_control_revision=task["control_revision"],
        expected_input_validity_revision=task["input_validity_revision"])
    context = TaskCommandContext(uow, actor, task, authorization,
                                 get_by_id(uow.connection, source_command_id).envelope)
    return receive_feedback_in_uow(context, source_run_id=run_id)


class ReworkApplication:
    def __init__(self, engine):
        self.engine = engine

    def _prepare(self, uow, actor, task_id, request, key):
        task, authorization = lock_task_access(uow, actor, task_id, "task.command")
        resource = task_resource(task)
        schema = REWORK_SCHEMA + ("-receive" if isinstance(request, ReceiveReworkRequest) else "-resolve")
        intent = CommandIntent(request_schema_revision=schema, caller=actor.principal,
            scope=resource.scope, target=resource.target_scope, action="task.command",
            expected_resource_revision=request.expected_version)
        command = CommandEnvelope(**intent.model_dump(), command_id=uuid4().hex, idempotency_key=key,
                                   request_digest=request_digest(intent, request))
        context = TaskCommandContext(uow, actor, task, authorization, command)
        return context, lock_and_get(uow.connection, command)

    def receive(self, actor, task_id, request, *, idempotency_key):
        with UnitOfWork(self.engine) as uow:
            context, existing = self._prepare(uow, actor, task_id, request, idempotency_key)
            if existing is not None:
                return ReworkReceipt.model_validate(existing.result)
            require_ordinary_progress(uow.connection, task_id, expected_version=request.expected_version,
                expected_control_revision=request.expected_control_revision,
                expected_input_validity_revision=request.expected_input_validity_revision)
            result = receive_feedback_in_uow(context, source_run_id=request.source_run_id,
                                            verification_report_id=request.verification_report_id)
            save_result(uow.connection, context.envelope, result, status_code=200,
                        authorization=context.authorization.envelope)
            return result

    def resolve(self, actor, task_id, request, *, idempotency_key):
        with UnitOfWork(self.engine) as uow:
            context, existing = self._prepare(uow, actor, task_id, request, idempotency_key)
            if existing is not None:
                return ReworkResolutionReceipt.model_validate(existing.result)
            require_ordinary_progress(uow.connection, task_id, expected_version=request.expected_version,
                expected_control_revision=request.expected_control_revision,
                expected_input_validity_revision=request.expected_input_validity_revision)
            issue = next((issue for issue in read_rework_issues(uow.connection, context.task)
                          if issue.issue_id == request.issue_id), None)
            if issue is None:
                raise TaskBoundaryError("rework_issue_not_found", status_code=404)
            resolution = verify_rework_resolution_in_uow(uow, actor, context.task, issue, request)
            revision = uow.connection.scalar(select(func.max(event_log.c.aggregate_version)).where(
                event_log.c.aggregate_kind == "rework_issue", event_log.c.aggregate_id == issue.issue_id)) + 1
            update_task(context)
            append_event(uow.connection, command_id=context.envelope.command_id,
                project_id=context.task["project_id"], aggregate_kind="rework_issue", aggregate_id=issue.issue_id,
                aggregate_version=revision, event_type="rework.issue_resolved", schema_version=REWORK_SCHEMA,
                payload=ReworkResolutionEvent(issue_id=issue.issue_id, resolution=resolution))
            result = ReworkResolutionReceipt(command_id=context.envelope.command_id, task_id=task_id,
                version=context.task["version"], issue_id=issue.issue_id, resolution=resolution)
            save_result(uow.connection, context.envelope, result, status_code=200,
                        authorization=context.authorization.envelope)
            return result

    def query(self, actor, task_id):
        with UnitOfWork(self.engine) as uow:
            task, _ = lock_task_access(uow, actor, task_id, "resource.read")
            return rework_view(uow.connection, task)
