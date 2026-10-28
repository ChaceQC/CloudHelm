"""Exact final-commit admission, shared by merge, completion and delivery."""

from sqlalchemy import select

from modules.collaboration.errors import TaskBoundaryError
from modules.delivery.queries import read_build_intent
from modules.integration.merge_records import entry_for_attempt, read_attempt, read_review
from modules.integration.merge_tables import merge_queue


def verified_final(connection, task, entry, report_id):
    from modules.integration.validity import require_verified_report

    attempt = read_attempt(connection, entry.attempt_id)
    if attempt is None or attempt.state != "prepared" or attempt.snapshot is None:
        raise TaskBoundaryError("integration_final_candidate_required")
    view = require_verified_report(connection, task, report_id)
    _, build = read_build_intent(connection, view.report.build_operation_id)
    if (build.fixed_inputs.candidate != attempt.snapshot
            or view.report.source_ref.revision != attempt.snapshot.candidate_commit
            or view.report.source_input_set_ref != entry.source_input_set_ref
            or entry.control_revision != view.report.control_revision
            or entry.input_validity_revision != task["input_validity_revision"]):
        raise TaskBoundaryError("integration_final_evidence_required")
    return attempt, view


def require_merged_report(connection, task, view):
    """A legacy candidate cannot bypass the project queue at a final consumer."""
    _, build = read_build_intent(connection, view.report.build_operation_id)
    snapshot = build.fixed_inputs.candidate
    if not snapshot.freeze_operation_id.startswith("merge-attempt-"):
        raise TaskBoundaryError("project_integration_required")
    entry = entry_for_attempt(connection, snapshot.freeze_operation_id)
    attempt, checked = verified_final(connection, task, entry, view.report.report_id)
    review = read_review(connection, entry.review_id)
    if (entry.state != "merged" or entry.verification_report_id != checked.report.report_id
            or review is None or review.conclusion != "approved"
            or review.attempt_id != attempt.attempt_id
            or review.integrated_commit != snapshot.candidate_commit
            or review.input_set_ref != checked.report.evidence.input_set_ref):
        raise TaskBoundaryError("project_integration_not_accepted")
    return entry


def pending_merges(connection, task_id):
    from packages.contracts.p0.engineering_contracts import EngineeringRef
    from packages.contracts.p0.task_control_contracts import OperationClosureFact
    from packages.contracts.p1.build_records import build_digest
    from packages.contracts.p2.merge_queue import MERGE_SCHEMA, MergeQueueEntry

    records = connection.scalars(select(merge_queue.c.record_json).where(
        merge_queue.c.task_id == task_id,
        merge_queue.c.state == "applying",
    ).order_by(merge_queue.c.position).limit(129)).all()
    return tuple(OperationClosureFact(operation_ref=EngineeringRef(kind="operation",
        object_id=entry.entry_id, revision=MERGE_SCHEMA, authority="integration",
        digest=build_digest(entry.candidate), digest_algorithm="sha256"), owner_kind="task",
        owner_id=task_id, affects_completion=True, closure="unknown")
        for entry in (MergeQueueEntry.model_validate(raw) for raw in records))
