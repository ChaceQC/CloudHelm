"""Verifier routes over immutable candidates and the existing controlled method."""

from hashlib import sha256

from pydantic import ValidationError
from sqlalchemy import select

from database.commands import CommandConflict
from database.uow import UnitOfWork
from modules.collaboration.command_support import lock_task_access
from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.records import read_registered_reference, reference_key
from modules.delivery.queries import read_build_intent
from modules.identity.actors import actor_for_command
from modules.identity.errors import IdentityError
from modules.integration.candidates import _current_input, _operation_access, _read, _ref
from modules.integration.verification import VerificationApplication, _assets, _event
from modules.integration.validity import verification_view
from modules.projects.reference_assets import ReferenceAssetError
from modules.sync.tables import event_log
from modules.workspaces.safe_paths import WorkspaceFileError
from packages.contracts.p2.verification import (
    FinalizeVerificationRequest, VerificationPhase, VerificationPhaseRequest,
)
from packages.contracts.p2.verification_agent import (
    CandidateListDirectory, VERIFICATION_TOOL_SCHEMAS,
)
from .admission import current_run
from .source_context import safe_context_text


def read_verification_candidate_in_uow(uow, actor, task, request):
    binding = request.context.verification or request.context.review
    candidate = _read(uow.connection, task, binding.candidate_id)
    lock_task_access(uow, actor, task["task_id"], "resource.read")
    _operation_access(uow, actor, task, candidate.build_operation_id)
    if (candidate.source_input_set_ref != request.context.input_set_ref
            or candidate.control_revision != task["control_revision"]
            or candidate.input_validity_revision != task["input_validity_revision"]
            or _current_input(uow.connection, task) != reference_key(task["project_id"], candidate.source_input_set_ref)
            or any(ref not in candidate.input_set.references for ref in (
                request.context.requirement_ref, request.context.acceptance_assets_ref, request.context.source_ref))):
        raise TaskBoundaryError("agent_verification_candidate_not_current")
    _, build = read_build_intent(uow.connection, candidate.build_operation_id)
    return candidate, build


def load_verification_context_in_uow(uow, actor, task, request, reader, repository):
    candidate, build = read_verification_candidate_in_uow(uow, actor, task, request)
    assets, acceptance, method = _assets(uow.connection, task["project_id"], candidate, repository)
    if reader is None:
        raise TaskBoundaryError("agent_verification_candidate_reader_unavailable")
    source = reader(build, "candidate.list_directory", CandidateListDirectory())
    binding = request.context.verification
    return source, {
        "candidate": candidate.model_dump(mode="json"),
        "candidate_commit": build.fixed_inputs.candidate.candidate_commit,
        "round_id": binding.round_id,
        "acceptance": acceptance.metadata.model_dump(mode="json"),
        "method": {"reference": method.reference.model_dump(mode="json"),
                   "content": method.metadata.model_dump(mode="json")},
        "expected_check_ids": assets.required_check_ids,
        "prepared_phase": binding.setup.phase if binding.setup else None,
        "setup_evidence_ref": binding.setup.setup_evidence_ref.model_dump(mode="json") if binding.setup else None,
    }


def verification_summary(view):
    report = view.report
    return {
        "report_id": report.report_id, "candidate_id": report.candidate_id,
        "candidate_commit": report.source_ref.revision, "round_id": report.round_id,
        "input_set_ref": _ref("input_set", report.input_set.input_set_id,
                              report.schema_revision, "integration", report.input_set).model_dump(mode="json"),
        "environment_ref": report.evidence.environment_ref.model_dump(mode="json"),
        "method_ref": report.evidence.method_ref.model_dump(mode="json"),
        "evidence_ref": view.evidence_ref.model_dump(mode="json"),
        "result": report.evidence.result, "applicability": view.applicability, "usable": view.usable,
        "expected_check_ids": report.expected_check_ids, "passed_check_ids": report.passed_check_ids,
        "failed_check_ids": report.failed_check_ids, "missing_check_ids": report.missing_check_ids,
        "integrity_errors": report.integrity_errors,
        "phases": [{"phase_id": phase.phase_id, "phase": phase.phase, "exit_code": phase.exit_code,
                    "output_digest": phase.output_digest, "observed_at": phase.observed_at.isoformat()}
                   for phase in report.phases],
    }


def resolve_verification_handoff_in_uow(uow, run, request, handoff):
    if handoff["reason"] != "agent_verification_report_ready":
        return
    actor = actor_for_command(uow, run["source_command_id"])
    task, _ = lock_task_access(uow, actor, request.runtime_input.task_id, "resource.read")
    candidate, _ = read_verification_candidate_in_uow(uow, actor, task, request)
    view = verification_view(uow.connection, task, handoff["report_id"])
    _operation_access(uow, actor, task, view.report.build_operation_id)
    if (view.report.candidate_id != candidate.candidate_id
            or view.report.round_id != request.context.verification.round_id
            or view.applicability != "valid"):
        raise TaskBoundaryError("agent_verification_report_binding_mismatch")
    handoff["verification"] = verification_summary(view)


def verification_handoff(output, stop_reason):
    if output is None and stop_reason is None:
        return None
    return {
        "reason": stop_reason or "agent_verification_" + output.reason,
        "summary": safe_context_text(output.summary) if output else "Verification Run stopped at the recorded boundary.",
        "next_action": safe_context_text(output.next_action) if output else
            "Inspect committed history and original verification intents before continuing.",
        "report_id": output.report_id if output else None,
    }


class VerificationGateway:
    def __init__(self, engine, repository, reader):
        self.engine, self.repository, self.reader = engine, repository, reader
        self.application = VerificationApplication(engine, engine, repository)

    def call(self, run_id, tool_call_id, name, arguments):
        try:
            query = VERIFICATION_TOOL_SCHEMAS[name].model_validate(arguments)
        except ValidationError:
            return {"status": "rejected", "code": "agent_verification_arguments_invalid"}
        try:
            with UnitOfWork(self.engine) as uow:
                task, _, run, request, now = current_run(uow, run_id)
                if request.context.verification is None or request.policy.role != "verifier":
                    raise TaskBoundaryError("agent_role_tool_not_allowed")
                actor = actor_for_command(uow, run["source_command_id"])
                candidate, build = read_verification_candidate_in_uow(uow, actor, task, request)
                binding = request.context.verification
                if name.startswith("candidate."):
                    if self.reader is None:
                        raise TaskBoundaryError("agent_verification_candidate_reader_unavailable")
                    return self.reader(build, name, query)
                if name == "verification.result":
                    view = verification_view(uow.connection, task, query.report_id)
                    if view.report.candidate_id != candidate.candidate_id or view.report.round_id != binding.round_id:
                        raise TaskBoundaryError("agent_verification_report_binding_mismatch")
                    return verification_summary(view)
                lock_task_access(uow, actor, task["task_id"], "fact.archive")
                _, acceptance, _ = _assets(uow.connection, task["project_id"], candidate, self.repository)
                revisions = dict(expected_version=task["version"],
                    expected_control_revision=task["control_revision"],
                    expected_input_validity_revision=task["input_validity_revision"],
                    candidate_id=candidate.candidate_id, round_id=binding.round_id, source_id=acceptance.source_id)
                events = uow.connection.execute(select(event_log).where(
                    event_log.c.project_id == task["project_id"],
                    event_log.c.event_type.in_(("verification.phase_started", "verification.phase_finished")),
                    event_log.c.payload["candidate_id"].astext == candidate.candidate_id,
                    event_log.c.payload["round_id"].astext == binding.round_id,
                )).mappings().all()
                identity = "\n".join((request.runtime_input.session_id, candidate.candidate_id, binding.round_id,
                                       query.phase if name == "verification.run_phase" else "finalize"))
                key = "agent-verification-" + sha256(identity.encode("utf-8")).hexdigest()
                if name == "verification.run_phase":
                    setup = binding.setup
                    if setup is None or query.phase != setup.phase:
                        raise TaskBoundaryError("agent_verification_phase_not_prepared")
                    started = [row for row in events if row["event_type"] == "verification.phase_started"
                               and row["payload"]["phase"] == query.phase]
                    if started:
                        original = VerificationPhaseRequest.model_validate(started[0]["payload"])
                        if original.setup_evidence_ref != setup.setup_evidence_ref:
                            raise TaskBoundaryError("agent_verification_round_requires_new_identity")
                        phase = _event(uow.connection, started[0]["event_id"].removesuffix("-intent"),
                                       "verification.phase_finished", VerificationPhase)
                        if phase is None:
                            raise TaskBoundaryError("verification_phase_outcome_unknown")
                        return phase.model_dump(mode="json")
                    order = ("baseline", "seed", "verify-persisted", "not-ready")
                    finished = {row["payload"]["phase"]: VerificationPhase.model_validate(row["payload"])
                                for row in events if row["event_type"] == "verification.phase_finished"}
                    preceding = order[:order.index(query.phase)]
                    if any(phase not in finished for phase in preceding):
                        raise TaskBoundaryError("agent_verification_preceding_phase_required")
                    if query.phase in {"verify-persisted", "not-ready"}:
                        proof = read_registered_reference(uow.connection, task["project_id"], setup.setup_evidence_ref)
                        if proof.metadata.evidence.observed_at <= finished[preceding[-1]].observed_at:
                            raise TaskBoundaryError("agent_verification_setup_predates_preceding_phase")
                    timeout_seconds = min(300, max(0, (run["deadline_at"] - now).total_seconds()))
                    phase_request = VerificationPhaseRequest(**revisions, phase=query.phase,
                                                            setup_evidence_ref=setup.setup_evidence_ref)
                else:
                    phase_ids = tuple(sorted({row["event_id"].removesuffix("-intent") for row in events}))
                    if len(phase_ids) > 4:
                        raise TaskBoundaryError("agent_verification_round_requires_new_identity")
                    final_request = FinalizeVerificationRequest(**revisions, phase_ids=phase_ids)
            # Physical checks execute after the admission transaction has closed.
            if name == "verification.run_phase":
                phase = self.application.run_phase(actor, task["task_id"], phase_request,
                    base_url=setup.base_url, idempotency_key=key, timeout_seconds=timeout_seconds)
                return phase.model_dump(mode="json")
            report = self.application.finalize(actor, task["task_id"], final_request, idempotency_key=key)
            return verification_summary(self.application.query(actor, task["task_id"], report.report_id))
        except (TaskBoundaryError, IdentityError, WorkspaceFileError) as error:
            return {"status": "unknown" if error.code == "verification_phase_outcome_unknown" else "rejected",
                    "code": error.code}
        except ReferenceAssetError:
            return {"status": "rejected", "code": "agent_verification_assets_unavailable"}
        except CommandConflict:
            return {"status": "rejected", "code": "agent_verification_round_requires_new_identity"}
