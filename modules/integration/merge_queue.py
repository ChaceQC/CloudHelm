"""Task-authorized project FIFO and explicit final-input review."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import insert, select

from database.commands import get_by_id, lock_and_get, save_result
from database.uow import UnitOfWork
from modules.collaboration.command_support import TaskCommandContext, lock_task_access, update_task
from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.guards import check_task_revisions, require_ordinary_progress, task_resource
from modules.collaboration.records import reference_key
from modules.delivery.commands import _candidate
from modules.integration.candidates import _current_input
from modules.integration.merge_records import queue_head, read_attempt, read_entry, read_review, save_entry
from modules.integration.merge_tables import merge_queue
from modules.integration.merge_validity import verified_final
from modules.projects.source_tables import project_git_sources
from modules.sync.events import append_event
from packages.contracts.p0.decision_common import Contract, Identifier
from packages.contracts.p0.identity_contracts import CommandEnvelope, CommandIntent, request_digest
from packages.contracts.p1.workspace_git import RegisteredGitSource
from packages.contracts.p1.workspace_records import workspace_metadata_digest
from packages.contracts.p2.merge_queue import (
    MERGE_SCHEMA, AdvanceMergeRequest, EnqueueMergeRequest, IntegrationReview, MergeQueueEntry,
    MergeQueueView, ReviewMergeRequest,
)


class _ScopedRequest(Contract):
    entry_id: Identifier | None
    request: EnqueueMergeRequest | AdvanceMergeRequest | ReviewMergeRequest


def record_event(uow, entry, event_id, event_type, value, command_id):
    append_event(uow.connection, command_id=command_id, project_id=entry.project_id,
        aggregate_kind="integration", aggregate_id=entry.entry_id, aggregate_version=entry.version,
        event_id=event_id, event_type=event_type, schema_version=MERGE_SCHEMA, payload=value)


def check_entry_task(connection, task, entry):
    if (entry.task_id != task["task_id"] or entry.project_id != task["project_id"]
            or entry.control_revision != task["control_revision"]
            or entry.input_validity_revision != task["input_validity_revision"]
            or _current_input(connection, task) != reference_key(entry.project_id, entry.source_input_set_ref)):
        raise TaskBoundaryError("merge_inputs_not_current")


class MergeQueueApplication:
    def __init__(self, engine, control_engine, *, enqueue_operation=None):
        self.engine, self.control_engine = engine, control_engine
        self.enqueue_operation = enqueue_operation

    def _dispatch(self, uow, entry, phase, command_id):
        if self.enqueue_operation is not None:
            command = get_by_id(uow.connection, command_id)
            # New commands are saved by the same caller before dispatch.
            self.enqueue_operation(uow, "merge-" + phase + "-" + entry.attempt_id,
                command_id, "merge-" + phase + "-" + entry.attempt_id, entry.version, command.envelope.request_digest)

    def start_head(self, uow, project_id):
        head = queue_head(uow.connection, project_id)
        if head is not None and head.state == "queued":
            head = save_entry(uow.connection, head, state="preparing")
            self._dispatch(uow, head, "prepare", head.command_id)

    def _prepare(self, uow, actor, task_id, request, key, entry_id=None):
        action = "review.submit" if isinstance(request, ReviewMergeRequest) else "candidate.submit"
        task, authorization = lock_task_access(uow, actor, task_id, action)
        resource = task_resource(task)
        intent = CommandIntent(request_schema_revision=MERGE_SCHEMA, caller=actor.principal,
            scope=resource.scope, target=resource.target_scope, action=action,
            expected_resource_revision=request.expected_version)
        command = CommandEnvelope(**intent.model_dump(), command_id=uuid4().hex, idempotency_key=key,
            request_digest=request_digest(intent, _ScopedRequest(entry_id=entry_id, request=request)))
        return TaskCommandContext(uow, actor, task, authorization, command), lock_and_get(uow.connection, command)

    def enqueue(self, actor, task_id, request, *, idempotency_key):
        with UnitOfWork(self.engine) as uow:
            context, previous = self._prepare(uow, actor, task_id, request, idempotency_key)
            if previous is not None:
                return MergeQueueEntry.model_validate(previous.result)
            task, command = context.task, context.envelope
            require_ordinary_progress(uow.connection, task_id, expected_version=request.expected_version,
                expected_control_revision=request.expected_control_revision,
                expected_input_validity_revision=request.expected_input_validity_revision)
            candidate = _candidate(uow.connection, task, request.candidate_id)
            if candidate.freeze_operation_id.startswith("merge-attempt-"):
                raise TaskBoundaryError("merge_original_candidate_required")
            from modules.workspaces.operations import read_workspace_operation
            from modules.workspaces.receipts import read_workspace_registration

            accepted, _ = read_workspace_operation(uow.connection, candidate.freeze_operation_id)
            receipt = read_workspace_registration(uow.connection, accepted)
            if receipt is None or not receipt.applicable or receipt.receipt.snapshot != candidate:
                raise TaskBoundaryError("merge_candidate_not_fixed")
            source_row = uow.connection.execute(select(project_git_sources).where(
                project_git_sources.c.project_id == task["project_id"])).mappings().one()
            source = RegisteredGitSource.model_validate(source_row["source_json"])
            if (workspace_metadata_digest(source) != source_row["source_digest"] or source.source_prefix
                    or source.access_mode != "read_write"
                    or source.source_id != candidate.binding.source_id
                    or source.source_revision != candidate.binding.source_revision
                    or _current_input(uow.connection, task) != reference_key(task["project_id"], accepted.result.input_set_ref)
                    or accepted.request.expected_control_revision != task["control_revision"]
                    or accepted.request.expected_input_validity_revision != task["input_validity_revision"]):
                raise TaskBoundaryError("merge_source_input_mismatch")
            update_task(context)
            entry = MergeQueueEntry(entry_id="merge-entry-" + command.command_id, command_id=command.command_id,
                project_id=task["project_id"], task_id=task_id, version=context.task["version"],
                control_revision=task["control_revision"], input_validity_revision=task["input_validity_revision"],
                source_input_set_ref=accepted.result.input_set_ref, source=source, candidate=candidate,
                state="queued", attempt_id="merge-attempt-" + command.command_id, created_at=datetime.now(UTC))
            uow.connection.execute(insert(merge_queue).values(entry_id=entry.entry_id, project_id=entry.project_id,
                task_id=task_id, state=entry.state, record_json=entry.model_dump(mode="json")))
            record_event(uow, entry, "merge-enqueued-" + command.command_id, "integration.enqueued", entry, command.command_id)
            save_result(uow.connection, command, entry, status_code=202, authorization=context.authorization.envelope)
            self.start_head(uow, entry.project_id)
            return entry

    def review(self, actor, entry_id, request, *, idempotency_key):
        with UnitOfWork(self.engine) as uow:
            entry = read_entry(uow.connection, entry_id)
            context, previous = self._prepare(uow, actor, entry.task_id, request, idempotency_key, entry_id)
            if previous is not None:
                return IntegrationReview.model_validate(previous.result)
            entry = read_entry(uow.connection, entry_id, for_update=True)
            self._guard(context, entry, request)
            if actor.principal.kind != "human" or entry.state != "awaiting_evidence":
                raise TaskBoundaryError("integration_human_review_required", status_code=403)
            attempt, view = verified_final(uow.connection, context.task, entry, request.verification_report_id)
            review = IntegrationReview(review_id="merge-review-" + context.envelope.command_id,
                entry_id=entry_id, attempt_id=attempt.attempt_id,
                integrated_commit=attempt.snapshot.candidate_commit, input_set_ref=view.report.evidence.input_set_ref,
                verification_report_id=view.report.report_id, conclusion=request.conclusion, reason=request.reason,
                reviewed_by=actor.principal, authorization_decision_id=context.authorization.envelope.decision_id,
                reviewed_at=datetime.now(UTC))
            update_task(context)
            entry = save_entry(uow.connection, entry, review_id=review.review_id, version=context.task["version"])
            record_event(uow, entry, review.review_id, "integration.reviewed", review, context.envelope.command_id)
            save_result(uow.connection, context.envelope, review, status_code=201,
                        authorization=context.authorization.envelope)
            return review

    def _guard(self, context, entry, request):
        if isinstance(request, AdvanceMergeRequest) and request.action == "withdraw":
            check_task_revisions(context.task, expected_version=request.expected_version,
                expected_control_revision=request.expected_control_revision,
                expected_input_validity_revision=request.expected_input_validity_revision)
            if entry.attempt_id != request.attempt_id:
                raise TaskBoundaryError("integration_attempt_not_current")
            return
        require_ordinary_progress(context.uow.connection, entry.task_id, expected_version=request.expected_version,
            expected_control_revision=request.expected_control_revision,
            expected_input_validity_revision=request.expected_input_validity_revision)
        check_entry_task(context.uow.connection, context.task, entry)
        if entry.attempt_id != request.attempt_id:
            raise TaskBoundaryError("integration_attempt_not_current")

    def advance(self, actor, entry_id, request, *, idempotency_key):
        with UnitOfWork(self.engine) as uow:
            entry = read_entry(uow.connection, entry_id)
            context, previous = self._prepare(uow, actor, entry.task_id, request, idempotency_key, entry_id)
            if previous is not None:
                return MergeQueueEntry.model_validate(previous.result)
            entry = read_entry(uow.connection, entry_id, for_update=True)
            if request.action == "reconcile":
                check_task_revisions(context.task, expected_version=request.expected_version,
                    expected_control_revision=request.expected_control_revision,
                    expected_input_validity_revision=request.expected_input_validity_revision)
                if entry.attempt_id != request.attempt_id or entry.state not in {"preparing", "applying"}:
                    raise TaskBoundaryError("merge_entry_not_reconcilable")
                save_result(uow.connection, context.envelope, entry, status_code=202,
                            authorization=context.authorization.envelope)
                operation_id = "merge-reconcile-" + context.envelope.command_id + "-" + entry.attempt_id
                if self.enqueue_operation is not None:
                    self.enqueue_operation(uow, operation_id, context.envelope.command_id, operation_id,
                                           entry.version, context.envelope.request_digest)
                return entry
            self._guard(context, entry, request)
            if (entry.state in {"merged", "withdrawn", "applying"}
                    or entry.state == "preparing" and request.action != "withdraw"):
                raise TaskBoundaryError("merge_entry_not_actionable")
            values = {}
            if request.action == "merge":
                if queue_head(uow.connection, entry.project_id).entry_id != entry_id:
                    raise TaskBoundaryError("merge_entry_not_head")
                attempt, view = verified_final(uow.connection, context.task, entry, request.verification_report_id)
                review = read_review(uow.connection, entry.review_id)
                if (review is None or review.conclusion != "approved" or review.attempt_id != attempt.attempt_id
                        or review.input_set_ref != view.report.evidence.input_set_ref
                        or review.verification_report_id != view.report.report_id):
                    raise TaskBoundaryError("integration_review_required")
                values = dict(state="applying", verification_report_id=view.report.report_id,
                              apply_command_id=context.envelope.command_id)
            elif request.action == "retry":
                values = dict(state="queued", attempt_id="merge-attempt-" + context.envelope.command_id,
                              command_id=context.envelope.command_id,
                              review_id=None, verification_report_id=None, apply_command_id=None)
            else:
                values = dict(state="withdrawn")
            update_task(context)
            entry = save_entry(uow.connection, entry, version=context.task["version"], **values)
            record_event(uow, entry, "merge-command-" + context.envelope.command_id,
                         "integration.commanded", entry, context.envelope.command_id)
            save_result(uow.connection, context.envelope, entry, status_code=202,
                        authorization=context.authorization.envelope)
            if entry.state == "applying":
                self._dispatch(uow, entry, "apply", context.envelope.command_id)
            else:
                self.start_head(uow, entry.project_id)
            return entry

    def query(self, actor, entry_id):
        with UnitOfWork(self.control_engine) as uow:
            entry = read_entry(uow.connection, entry_id)
            lock_task_access(uow, actor, entry.task_id, "resource.read")
            return MergeQueueView(entry=entry, attempt=read_attempt(uow.connection, entry.attempt_id),
                                  review=read_review(uow.connection, entry.review_id))

    def list(self, actor, project_id):
        from modules.identity.actors import AuthoritativeResource
        from modules.identity.authorization import authorize_current
        from modules.identity.locking import lock_current_subject, lock_project_policy

        with UnitOfWork(self.control_engine) as uow:
            lock_current_subject(uow, actor)
            lock_project_policy(uow, project_id)
            authorize_current(uow, actor, AuthoritativeResource(project_id, "project", project_id), "resource.read")
            records = uow.connection.scalars(select(merge_queue.c.record_json).where(
                merge_queue.c.project_id == project_id, merge_queue.c.state.not_in(("merged", "withdrawn")),
            ).order_by(merge_queue.c.position).limit(129)).all()
            if len(records) > 128:
                raise TaskBoundaryError("merge_queue_view_too_large")
            return tuple(MergeQueueEntry.model_validate(raw) for raw in records)
