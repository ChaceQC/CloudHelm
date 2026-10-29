"""Bind rework closure to current formal verification and, when needed, review."""

from types import SimpleNamespace

from sqlalchemy import select

from modules.agent_runtime.tables import agent_runs
from modules.collaboration.errors import TaskBoundaryError
from modules.delivery.queries import read_build_intent
from modules.integration.candidates import _operation_access, _read
from modules.integration.rework_sources import _run_source, load_feedback_source
from modules.integration.validity import require_verified_report, verification_view
from modules.workspaces.tables import workspaces


def verify_rework_resolution_in_uow(uow, actor, task, issue, request):
    """Validate evidence in the caller's locked Task transaction; do not close it here."""
    connection = uow.connection
    if issue.task_id != task["task_id"] or request.issue_id != issue.issue_id:
        raise TaskBoundaryError("rework_issue_not_found", status_code=404)
    view = require_verified_report(connection, task, request.verification_report_id)
    report = view.report
    candidate = _read(connection, task, report.candidate_id)
    _, build = read_build_intent(connection, report.build_operation_id)
    snapshot = build.fixed_inputs.candidate
    binding = snapshot.binding
    _operation_access(uow, actor, task, build.operation_id)
    if (snapshot.freeze_operation_id.startswith("merge-attempt-")
            or snapshot.candidate_id.startswith("integration-candidate-")):
        raise TaskBoundaryError("rework_workspace_candidate_required")
    _operation_access(uow, actor, task, snapshot.freeze_operation_id)
    workspace = connection.execute(select(
        workspaces.c.project_id, workspaces.c.task_id, workspaces.c.work_item_id,
    ).where(workspaces.c.workspace_id == binding.workspace_id)).mappings().one_or_none()
    if (workspace is None or workspace["project_id"] != task["project_id"]
            or workspace["task_id"] != task["task_id"] or workspace["work_item_id"] != issue.work_item_id
            or binding.project_id != task["project_id"] or binding.task_id != task["task_id"]
            or binding.work_item_id != issue.work_item_id
            or build.project_id != task["project_id"] or build.task_id != task["task_id"]
            or build.operation_id != candidate.build_operation_id
            or build.fixed_inputs.source_input_set_ref != candidate.source_input_set_ref
            or candidate.source_input_set_ref != report.source_input_set_ref
            or candidate.control_revision != report.control_revision
            or candidate.input_validity_revision != report.input_validity_revision
            or report.source_ref.revision != snapshot.candidate_commit):
        raise TaskBoundaryError("rework_candidate_binding_mismatch")
    if candidate.candidate_id == issue.candidate_id or snapshot.candidate_commit == issue.candidate_commit:
        raise TaskBoundaryError("rework_new_candidate_required")
    passed = set(report.passed_check_ids)
    if (report.failed_check_ids or report.missing_check_ids or report.integrity_errors
            or not set(report.expected_check_ids) <= passed or not set(issue.check_ids) <= passed):
        raise TaskBoundaryError("rework_verification_incomplete")

    if issue.source_kind == "review" and request.review_run_id is None:
        raise TaskBoundaryError("rework_review_required")
    if request.review_run_id is not None:
        feedback = load_feedback_source(uow, actor, task, source_run_id=request.review_run_id)
        review_session = connection.scalar(select(agent_runs.c.session_id).where(
            agent_runs.c.run_id == request.review_run_id,
        ))
        if (feedback["source_kind"] != "review" or feedback["candidate_id"] != candidate.candidate_id
                or feedback["candidate_commit"] != snapshot.candidate_commit
                or feedback["source_input_set_ref"] != report.source_input_set_ref.model_dump(mode="json")
                or feedback["work_item_id"] != issue.work_item_id
                or review_session in {issue.owner_session_id, feedback["owner_session_id"]}
                or feedback["uncovered"]
                or any(item["severity"] == "blocking" or
                       issue.source_kind == "review" and item["fingerprint"] == issue.fingerprint
                       for item in feedback["issues"])):
            raise TaskBoundaryError("rework_review_incomplete")

    return {
        "issue_id": issue.issue_id, "source_kind": issue.source_kind, "work_item_id": issue.work_item_id,
        "candidate_id": candidate.candidate_id, "candidate_commit": snapshot.candidate_commit,
        "build_operation_id": build.operation_id, "verification_report_id": report.report_id,
        "evidence_ref": view.evidence_ref.model_dump(mode="json"), "review_run_id": request.review_run_id,
        "source_input_set_ref": report.source_input_set_ref.model_dump(mode="json"),
        "control_revision": report.control_revision, "input_validity_revision": report.input_validity_revision,
    }


def resolution_is_current(connection, task, resolution: dict) -> bool:
    """Reproject existing closure evidence without granting access or human approval."""
    if (resolution.get("source_kind") not in {"review", "verification"}
            or resolution.get("source_kind") == "review" and not resolution.get("review_run_id")):
        return False
    try:
        view = verification_view(connection, task, resolution["verification_report_id"])
        report = view.report
        _, build = read_build_intent(connection, report.build_operation_id)
        snapshot = build.fixed_inputs.candidate
        binding = snapshot.binding
        workspace = connection.execute(select(
            workspaces.c.project_id, workspaces.c.task_id, workspaces.c.work_item_id,
        ).where(workspaces.c.workspace_id == binding.workspace_id)).mappings().one_or_none()
        if (not view.usable or report.candidate_id != resolution.get("candidate_id")
                or report.build_operation_id != resolution.get("build_operation_id")
                or snapshot.freeze_operation_id.startswith("merge-attempt-")
                or snapshot.candidate_id.startswith("integration-candidate-")
                or report.source_ref.revision != snapshot.candidate_commit
                or snapshot.candidate_commit != resolution.get("candidate_commit")
                or report.source_input_set_ref.model_dump(mode="json") != resolution.get("source_input_set_ref")
                or view.evidence_ref.model_dump(mode="json") != resolution.get("evidence_ref")
                or report.control_revision != resolution.get("control_revision")
                or report.input_validity_revision != resolution.get("input_validity_revision")
                or build.task_id != task["task_id"] or build.project_id != task["project_id"]
                or binding.task_id != task["task_id"] or binding.project_id != task["project_id"]
                or binding.work_item_id != resolution.get("work_item_id")
                or workspace is None or workspace["task_id"] != task["task_id"]
                or workspace["project_id"] != task["project_id"]
                or workspace["work_item_id"] != binding.work_item_id):
            return False
        if resolution.get("review_run_id") is not None:
            kind, request, handoff = _run_source(
                SimpleNamespace(connection=connection), task, resolution["review_run_id"],
            )
            review = handoff.get("review") or {}
            if (kind != "review" or request.context.review.candidate_id != report.candidate_id
                    or request.context.input_set_ref != report.source_input_set_ref
                    or review.get("candidate_id") != report.candidate_id
                    or review.get("candidate_commit") != snapshot.candidate_commit
                    or review.get("source_input_set_ref") != resolution.get("source_input_set_ref")
                    or review.get("build_operation_id") != report.build_operation_id):
                return False
    except TaskBoundaryError:
        return False
    return True
