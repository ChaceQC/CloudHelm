"""Read feedback from persisted Runs and current fixed-candidate evidence."""

from hashlib import sha256

import rfc8785
from sqlalchemy import select

from modules.agent_runtime.tables import agent_runs, agent_sessions
from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.records import reference_key
from modules.collaboration.tables import work_items
from modules.delivery.queries import read_build_intent
from modules.integration.candidates import _current_input, _operation_access, _read
from modules.integration.validity import verification_view
from modules.workspaces.tables import workspaces
from packages.contracts.p0.core_contracts import TurnResult
from packages.contracts.p2.review_agent import ReviewFinding
from packages.contracts.p2.runtime import RuntimeStartRequest


def _fingerprint(*parts):
    return "sha256:" + sha256(rfc8785.dumps(list(parts))).hexdigest()


def _run_source(uow, task, run_id):
    row = uow.connection.execute(select(agent_runs).join(
        agent_sessions, agent_sessions.c.session_id == agent_runs.c.session_id,
    ).where(agent_runs.c.run_id == run_id, agent_sessions.c.task_id == task["task_id"])).mappings().one_or_none()
    if row is None:
        raise TaskBoundaryError("rework_source_run_not_found", status_code=404)
    if row["state"] != "succeeded" or row["result_json"] is None:
        raise TaskBoundaryError("rework_source_run_not_ready")
    request = RuntimeStartRequest.model_validate(row["start_json"])
    result = row["result_json"]
    handoff = result.get("handoff") or {}
    reasons = {"agent_review_feedback_ready": ("review", "agent-review-r1"),
               "agent_verification_report_ready": ("verification", "agent-verification-r1")}
    if handoff.get("reason") not in reasons:
        raise TaskBoundaryError("rework_source_run_not_ready")
    kind, revision = reasons[handoff["reason"]]
    turn = TurnResult.model_validate(result["turn"])
    incoming = request.runtime_input
    digest = "sha256:" + sha256(rfc8785.dumps(handoff)).hexdigest()
    if (result.get("state") != "succeeded" or incoming.task_id != task["task_id"]
            or incoming.run_id != run_id or incoming.session_id != row["session_id"]
            or incoming.expected_task_control_revision != task["control_revision"]
            or incoming.expected_input_validity_revision != task["input_validity_revision"]
            or turn.run_id != run_id or turn.outcome != "submitted" or turn.reason_code != handoff["reason"]
            or not any(ref.object_id == run_id and ref.revision == revision
                       and ref.authority == "agent-runtime" and ref.digest == digest
                       for ref in turn.delivery_refs)):
        raise TaskBoundaryError("rework_source_run_binding_mismatch")
    if ((kind == "review" and (request.policy.role != "reviewer" or request.context.review is None))
            or (kind == "verification" and (request.policy.role != "verifier"
                                             or request.context.verification is None))):
        raise TaskBoundaryError("rework_source_run_binding_mismatch")
    return kind, request, handoff


def _work_item(uow, task, snapshot):
    if (snapshot.freeze_operation_id.startswith("merge-attempt-")
            or snapshot.candidate_id.startswith("integration-candidate-")):
        raise TaskBoundaryError("rework_workspace_candidate_required")
    binding = snapshot.binding
    row = uow.connection.execute(select(work_items.c.work_item_id, work_items.c.owner_session_id).select_from(
        workspaces.join(work_items, (workspaces.c.task_id == work_items.c.task_id)
                        & (workspaces.c.work_item_id == work_items.c.work_item_id)),
    ).where(workspaces.c.workspace_id == binding.workspace_id, workspaces.c.project_id == task["project_id"],
            workspaces.c.task_id == task["task_id"], workspaces.c.work_item_id == binding.work_item_id,
            work_items.c.task_id == task["task_id"])).mappings().one_or_none()
    if row is None or binding.project_id != task["project_id"] or binding.task_id != task["task_id"]:
        raise TaskBoundaryError("rework_source_work_item_unavailable")
    return row["work_item_id"], row["owner_session_id"]


def _candidate(uow, actor, task, candidate_id):
    candidate = _read(uow.connection, task, candidate_id)
    _operation_access(uow, actor, task, candidate.build_operation_id)
    if (candidate.control_revision != task["control_revision"]
            or candidate.input_validity_revision != task["input_validity_revision"]
            or _current_input(uow.connection, task) != reference_key(task["project_id"], candidate.source_input_set_ref)):
        raise TaskBoundaryError("rework_source_input_stale")
    _, build = read_build_intent(uow.connection, candidate.build_operation_id)
    snapshot = build.fixed_inputs.candidate
    if (build.task_id != task["task_id"] or build.project_id != task["project_id"]
            or build.fixed_inputs.source_input_set_ref != candidate.source_input_set_ref):
        raise TaskBoundaryError("rework_source_candidate_binding_mismatch")
    return candidate, build


def _review(uow, actor, task, run_id, request, handoff):
    from modules.agent_runtime.review import read_review_evidence_in_uow
    from modules.agent_runtime.source_context import secret_context_path

    build, facts = read_review_evidence_in_uow(uow, actor, task, request)
    candidate = _read(uow.connection, task, request.context.review.candidate_id)
    stored = handoff.get("review") or {}
    keys = ("candidate_id", "candidate_commit", "baseline_commit", "input_set_ref",
            "source_input_set_ref", "environment_ref", "evidence_refs")
    if (any(stored.get(key) != facts[key] for key in keys)
            or stored.get("build_operation_id") != build.operation_id
            or stored.get("build_state") != facts["build"]["state"]
            or stored.get("verification_report_id") != request.context.review.verification_report_id
            or stored.get("verification_result") != facts["verification"].get("result", "missing")
            or stored.get("verification_applicability") != facts["verification"].get("applicability")
            or stored.get("decision") != "feedback_only"
            or (request.context.review.verification_report_id is not None
                and facts["verification"].get("applicability") != "valid")):
        raise TaskBoundaryError("rework_review_evidence_binding_mismatch")
    if len(handoff["findings"]) > 16:
        raise TaskBoundaryError("rework_source_issue_limit")
    issues = []
    for data in handoff["findings"]:
        finding = ReviewFinding.model_validate(data)
        refs = [ref.model_dump(mode="json") for ref in finding.evidence_refs]
        if secret_context_path(finding.path) or any(ref not in facts["evidence_refs"] for ref in refs):
            raise TaskBoundaryError("rework_review_evidence_binding_mismatch")
        issues.append({"fingerprint": _fingerprint("review", finding.path, str(finding.line), finding.title),
                       "title": finding.title, "reason": finding.reason, "severity": finding.severity,
                       "path": finding.path, "line": finding.line, "check_ids": [], "evidence_refs": refs})
    return candidate, build, {"source_id": run_id, "source_kind": "review", "issues": issues,
                              "evidence_refs": facts["evidence_refs"], "uncovered": handoff["uncovered"]}


def _verification(uow, actor, task, report_id, request=None, handoff=None):
    view = verification_view(uow.connection, task, report_id)
    report = view.report
    if view.applicability != "valid":
        raise TaskBoundaryError("rework_verification_not_current")
    candidate, build = _candidate(uow, actor, task, report.candidate_id)
    snapshot = build.fixed_inputs.candidate
    if (report.build_operation_id != build.operation_id or report.source_ref.revision != snapshot.candidate_commit
            or report.source_input_set_ref != candidate.source_input_set_ref
            or report.control_revision != candidate.control_revision
            or report.input_validity_revision != candidate.input_validity_revision):
        raise TaskBoundaryError("rework_verification_binding_mismatch")
    if request is not None:
        from modules.agent_runtime.verification import read_verification_candidate_in_uow

        checked, checked_build = read_verification_candidate_in_uow(uow, actor, task, request)
        stored = handoff.get("verification") or {}
        if (checked != candidate or checked_build != build or request.context.verification.round_id != report.round_id
                or handoff.get("report_id") != report_id or stored.get("report_id") != report_id
                or stored.get("candidate_id") != candidate.candidate_id
                or stored.get("candidate_commit") != snapshot.candidate_commit
                or stored.get("evidence_ref") != view.evidence_ref.model_dump(mode="json")
                or stored.get("applicability") != "valid"):
            raise TaskBoundaryError("rework_verification_binding_mismatch")
    issues = []
    report_refs = [view.evidence_ref.model_dump(mode="json")]
    for status, ids in (("failed", report.failed_check_ids), ("missing", report.missing_check_ids)):
        for check_id in ids:
            issues.append({"fingerprint": _fingerprint("verification", "check", check_id),
                "title": "Verification check " + status, "reason": f"Check {check_id}: {status}.",
                "severity": "blocking", "path": None, "line": None, "check_ids": [check_id],
                "evidence_refs": report_refs})
    if (report.integrity_errors or report.evidence.result in {"unknown", "not_run"}
            or (report.evidence.result == "failed" and not report.failed_check_ids)):
        detail = "Report result: " + report.evidence.result + "."
        if report.integrity_errors:
            detail += " Integrity errors: " + ", ".join(report.integrity_errors) + "."
        if report.evidence.result in {"unknown", "not_run"}:
            detail += " Phase exit codes: " + (", ".join(
                f"{phase.phase}={phase.exit_code}" for phase in report.phases) or "none") + "."
        issues.append({"fingerprint": _fingerprint("verification", "integrity_or_unknown"),
            "title": "Verification integrity or result unresolved", "reason": detail,
            "severity": "blocking", "path": None, "line": None, "check_ids": list(report.expected_check_ids),
            "evidence_refs": report_refs})
    if len(issues) > 128:
        raise TaskBoundaryError("rework_source_issue_limit")
    refs = [item.evidence_ref.model_dump(mode="json") for item in candidate.evidence]
    refs.extend(report_refs)
    return candidate, build, {"source_id": report_id, "source_kind": "verification", "issues": issues,
                              "evidence_refs": refs, "uncovered": []}


def load_feedback_source(uow, actor, task, *, source_run_id=None, verification_report_id=None):
    """Read original facts under the caller's Task authorization and row lock."""
    if (source_run_id is None) == (verification_report_id is None):
        raise TaskBoundaryError("rework_exactly_one_source_required", status_code=422)
    if task["input_status"] != "valid" or task["cancel_requested_at"] is not None:
        raise TaskBoundaryError("rework_source_input_stale")
    if source_run_id is not None:
        kind, request, handoff = _run_source(uow, task, source_run_id)
        if kind == "review":
            candidate, build, result = _review(uow, actor, task, source_run_id, request, handoff)
        else:
            candidate, build, result = _verification(uow, actor, task, handoff["report_id"], request, handoff)
    else:
        candidate, build, result = _verification(uow, actor, task, verification_report_id)
    work_item_id, owner_session_id = _work_item(uow, task, build.fixed_inputs.candidate)
    result.update(candidate_id=candidate.candidate_id, candidate_commit=build.fixed_inputs.candidate.candidate_commit,
                  source_input_set_ref=candidate.source_input_set_ref.model_dump(mode="json"),
                  work_item_id=work_item_id, owner_session_id=owner_session_id,
                  control_revision=candidate.control_revision, input_validity_revision=candidate.input_validity_revision)
    return result
