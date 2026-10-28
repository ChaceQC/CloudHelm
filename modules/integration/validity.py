"""Consumer checks and atomic reverse-reference invalidation, separate from facts."""

from uuid import uuid4

from sqlalchemy import select, update

from database.commands import lock_and_get, save_result
from database.uow import UnitOfWork
from modules.collaboration.command_support import TaskCommandContext, lock_task_access
from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.input_commands import _advance_input_validity
from modules.collaboration.records import read_registered_reference, reference_key
from modules.identity.actors import AuthoritativeResource
from modules.identity.authorization import authorize_current
from modules.identity.locking import lock_current_subject, lock_project_policy
from modules.integration.candidates import _current_input, _read
from modules.integration.tables import verification_dependencies
from modules.integration.verification import _append, _event, report_evidence_ref
from modules.sync.tables import event_log
from packages.contracts.p0.identity_contracts import CommandEnvelope, CommandIntent, request_digest
from packages.contracts.p1.task_facts import EvidenceMetadata
from packages.contracts.p2.verification import (
    VERIFICATION_SCHEMA, DependencyImpactResult, VerificationReport, VerificationSelection, VerificationView,
)


def verification_view(connection, task, report_id):
    report = _event(connection, report_id, "verification.reported", VerificationReport)
    if report is None or report.task_id != task["task_id"] or report.project_id != task["project_id"]:
        raise TaskBoundaryError("verification_report_not_found", status_code=404)
    candidate = _read(connection, task, report.candidate_id)
    rows = connection.execute(select(verification_dependencies).where(
        verification_dependencies.c.report_id == report_id,
    )).mappings().all()
    evidence_ref = report_evidence_ref(report)
    registered = read_registered_reference(connection, task["project_id"], evidence_ref)
    environment = read_registered_reference(connection, task["project_id"], report.evidence.environment_ref)
    read_registered_reference(connection, task["project_id"], report.evidence.method_ref)
    control_current = task["control_revision"] == report.control_revision
    if task["state"] == "completed":
        from modules.collaboration.facts import read_completion_report

        completion = read_completion_report(connection, task)
        control_current = bool(completion and registered.reference in completion.basis.required_evidence_refs)
    current = bool(rows and all(row["applicability"] == "valid" for row in rows)
        and task["input_status"] == "valid" and task["cancel_requested_at"] is None
        and control_current
        and task["input_validity_revision"] == report.input_validity_revision
        and _current_input(connection, task) == reference_key(task["project_id"], report.source_input_set_ref)
        and candidate.source_input_set_ref == report.source_input_set_ref
        and candidate.build_operation_id == report.build_operation_id
        and candidate.environment_ref == report.evidence.environment_ref
        and set(report.evidence.support_scope) <= set(environment.metadata.support_scope))
    from modules.delivery.queries import read_build_intent

    _, build = read_build_intent(connection, report.build_operation_id)
    snapshot = build.fixed_inputs.candidate
    if snapshot.freeze_operation_id.startswith("merge-attempt-"):
        from modules.integration.merge_records import entry_for_attempt, read_attempt

        try:
            entry = entry_for_attempt(connection, snapshot.freeze_operation_id)
            attempt = read_attempt(connection, entry.attempt_id)
            current = bool(current and entry.task_id == task["task_id"]
                and entry.state in {"awaiting_evidence", "applying", "merged"}
                and attempt is not None and attempt.snapshot == snapshot
                and report.source_ref.revision == snapshot.candidate_commit)
        except TaskBoundaryError:
            current = False
    usable = current and report.evidence.result == "passed"
    return VerificationView(report=report, evidence_ref=evidence_ref,
        applicability="valid" if current else "needs_review", usable=usable,
        reason_code="exact_verified_inputs" if usable else
                    "verification_not_passed" if current else "verification_inputs_need_review")


def require_verified_report(connection, task, report_id, *, evidence_ref=None, build_operation_id=None):
    view = verification_view(connection, task, report_id)
    if (not view.usable or evidence_ref is not None and evidence_ref != view.evidence_ref
            or build_operation_id is not None and view.report.build_operation_id != build_operation_id):
        raise TaskBoundaryError("verification_not_applicable", object_ids=(report_id,))
    return view


def selected_verification(connection, task):
    payload = connection.scalar(select(event_log.c.payload).where(
        event_log.c.project_id == task["project_id"], event_log.c.aggregate_kind == "task",
        event_log.c.aggregate_id == task["task_id"], event_log.c.event_type == "verification.accepted",
    ).order_by(event_log.c.aggregate_version.desc()).limit(1))
    if payload is None:
        return None
    selected = VerificationSelection.model_validate(payload)
    return verification_view(connection, task, selected.report_id)


def require_verification_evidence(connection, task, reference, data, *, build_operation_id=None):
    if not isinstance(data, EvidenceMetadata):
        raise TaskBoundaryError("controlled_verification_required")
    view = require_verified_report(connection, task, data.evidence.evidence_id,
                                   evidence_ref=reference, build_operation_id=build_operation_id)
    if data.evidence != view.report.evidence:
        raise TaskBoundaryError("verification_evidence_mismatch")
    return view


def require_release_verification(connection, project_id, release):
    from modules.collaboration.guards import read_task
    from modules.delivery.queries import read_build_intent

    _, build = read_build_intent(connection, release.build_operation_id)
    task = read_task(connection, build.task_id, for_update=True)
    acceptance = read_registered_reference(connection, project_id, build.fixed_inputs.definition.acceptance_assets_ref)
    expected, covered = set(acceptance.metadata.required_check_ids), set()
    for ref in release.verification_refs:
        data = read_registered_reference(connection, project_id, ref).metadata
        if isinstance(data, EvidenceMetadata) and expected.intersection(data.check_ids):
            view = require_verification_evidence(connection, task, ref, data, build_operation_id=build.operation_id)
            from modules.integration.merge_validity import require_merged_report

            require_merged_report(connection, task, view)
            covered.update(view.report.passed_check_ids)
    if not expected or not expected <= covered:
        raise TaskBoundaryError("controlled_verification_required")


class VerificationImpactApplication:
    def __init__(self, engine):
        self.engine = engine

    def invalidate(self, actor, project_id, request, *, idempotency_key):
        """Explicit old producer -> new change, including consumers of completed Tasks.

        Propagation is synchronous and bounded. Every affected report is blocked in
        the same transaction; there is no asynchronous interval with stale success.
        """
        with UnitOfWork(self.engine) as uow:
            lock_current_subject(uow, actor)
            lock_project_policy(uow, project_id)
            resource = AuthoritativeResource(project_id, "project", project_id)
            authorization = authorize_current(uow, actor, resource, "fact.archive")
            authorize_current(uow, actor, resource, "resource.read")
            intent = CommandIntent(request_schema_revision=VERIFICATION_SCHEMA, caller=actor.principal,
                                   scope=resource.scope, target=resource.target_scope, action="fact.archive",
                                   expected_resource_revision=0)
            command = CommandEnvelope(**intent.model_dump(), command_id=uuid4().hex, idempotency_key=idempotency_key,
                                      request_digest=request_digest(intent, request))
            existing = lock_and_get(uow.connection, command)
            if existing is not None:
                return DependencyImpactResult.model_validate(existing.result)
            read_registered_reference(uow.connection, project_id, request.change_ref)
            key = reference_key(project_id, request.producer_ref)
            links = uow.connection.execute(select(verification_dependencies).where(
                verification_dependencies.c.producer_key == key,
            ).order_by(verification_dependencies.c.task_id).limit(129)).mappings().all()
            if len(links) > 128:
                raise TaskBoundaryError("verification_impact_scope_too_large")
            report_ids = tuple(sorted({row["report_id"] for row in links}))
            task_ids = tuple(sorted({row["task_id"] for row in links}))
            for task_id in task_ids:
                task, task_authorization = lock_task_access(uow, actor, task_id, "fact.archive")
                if task["project_id"] != project_id:
                    raise TaskBoundaryError("verification_impact_project_mismatch")
                reports = [_event(uow.connection, row["report_id"], "verification.reported", VerificationReport)
                           for row in links if row["task_id"] == task_id]
                if (task["state"] not in {"completed", "cancelled"}
                        and any(report.input_validity_revision == task["input_validity_revision"] for report in reports)):
                    context = TaskCommandContext(uow, actor, task, task_authorization, command)
                    _advance_input_validity(context)
            if report_ids:
                uow.connection.execute(update(verification_dependencies).where(
                    verification_dependencies.c.report_id.in_(report_ids),
                ).values(applicability="needs_review"))
            result = DependencyImpactResult(command_id=command.command_id, report_ids=report_ids, task_ids=task_ids,
                producer_ref=request.producer_ref, change_ref=request.change_ref, reason=request.reason)
            # A project-scoped change records one immutable propagation outcome.
            _append(uow, command.command_id, {"project_id": project_id}, "verification-impact-" + command.command_id,
                    "verification.invalidated", result)
            save_result(uow.connection, command, result, status_code=200, authorization=authorization.envelope)
            return result
