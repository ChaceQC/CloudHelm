"""Read-only review of fixed inputs; feedback never records human approval."""

from pydantic import ValidationError

from database.uow import UnitOfWork
from modules.collaboration.command_support import lock_task_access
from modules.collaboration.errors import TaskBoundaryError
from modules.delivery.queries import build_view
from modules.identity.actors import actor_for_command
from modules.identity.errors import IdentityError
from modules.integration.candidates import _ref
from modules.integration.validity import verification_view
from modules.workspaces.safe_paths import WorkspaceFileError
from packages.contracts.p2.review_agent import REVIEW_TOOL_SCHEMAS
from packages.contracts.p2.verification_agent import CandidateListDirectory
from .admission import current_run
from .context import safe_context_value
from .source_context import secret_context_path
from .verification import read_verification_candidate_in_uow, verification_summary


def read_review_evidence_in_uow(uow, actor, task, request):
    candidate, build = read_verification_candidate_in_uow(uow, actor, task, request)
    snapshot = build.fixed_inputs.candidate
    view = build_view(uow.connection, build)
    evidence_refs = [item.evidence_ref.model_dump(mode="json") for item in candidate.evidence]
    report_id = request.context.review.verification_report_id
    verification = {"status": "missing", "reason_code": "review_verification_not_supplied"}
    if report_id is not None:
        report = verification_view(uow.connection, task, report_id)
        if (report.report.candidate_id != candidate.candidate_id
                or report.report.build_operation_id != build.operation_id
                or report.report.source_ref.revision != snapshot.candidate_commit):
            raise TaskBoundaryError("agent_review_report_binding_mismatch")
        verification = verification_summary(report)
        evidence_refs.append(report.evidence_ref.model_dump(mode="json"))
    return build, {
        "candidate_id": candidate.candidate_id,
        "candidate_commit": snapshot.candidate_commit, "baseline_commit": snapshot.parent_commit,
        "input_set_ref": _ref("input_set", candidate.input_set.input_set_id,
                              candidate.schema_revision, "integration", candidate.input_set).model_dump(mode="json"),
        "source_input_set_ref": candidate.source_input_set_ref.model_dump(mode="json"),
        "environment_ref": candidate.environment_ref.model_dump(mode="json"),
        "evidence_refs": evidence_refs,
        "build": {"operation_id": build.operation_id, "build_run_id": build.build_run_id,
                  "state": view.state, "content_verified": view.content_verified,
                  "execution": view.execution.model_dump(mode="json") if view.execution else None,
                  "content": view.content.model_dump(mode="json") if view.content else None},
        "verification": verification,
    }


def load_review_context_in_uow(uow, actor, task, request, reader):
    build, facts = read_review_evidence_in_uow(uow, actor, task, request)
    if reader is None:
        raise TaskBoundaryError("agent_review_candidate_reader_unavailable")
    source = reader(build, "candidate.list_directory", CandidateListDirectory())
    return source, facts


def review_handoff(output, stop_reason):
    if output is None and stop_reason is None:
        return None
    content = output.model_dump(mode="json", exclude={"reason"}) if output else {
        "summary": "Review Run stopped at the recorded boundary.",
        "next_action": "Inspect committed history and fixed inputs before continuing.",
        "findings": [], "uncovered": ["Review is incomplete."],
    }
    return safe_context_value({"reason": stop_reason or "agent_review_" + output.reason, **content})


def resolve_review_handoff_in_uow(uow, run, request, handoff):
    if handoff["reason"] != "agent_review_feedback_ready":
        return
    actor = actor_for_command(uow, run["source_command_id"])
    task, _ = lock_task_access(uow, actor, request.runtime_input.task_id, "resource.read")
    _, facts = read_review_evidence_in_uow(uow, actor, task, request)
    for finding in handoff["findings"]:
        if secret_context_path(finding["path"]):
            raise TaskBoundaryError("agent_review_sensitive_path")
        if any(ref not in facts["evidence_refs"] for ref in finding["evidence_refs"]):
            raise TaskBoundaryError("agent_review_evidence_binding_mismatch")
    # Detailed facts remain at their original immutable references, not duplicated in a new report store.
    handoff["review"] = {key: facts[key] for key in (
        "candidate_id", "candidate_commit", "baseline_commit", "input_set_ref",
        "source_input_set_ref", "environment_ref", "evidence_refs")}
    handoff["review"].update(build_operation_id=facts["build"]["operation_id"],
        build_state=facts["build"]["state"], verification_report_id=request.context.review.verification_report_id,
        verification_result=facts["verification"].get("result", "missing"),
        verification_applicability=facts["verification"].get("applicability"), decision="feedback_only")


class ReviewGateway:
    def __init__(self, engine, reader):
        self.engine, self.reader = engine, reader

    def call(self, run_id, tool_call_id, name, arguments):
        try:
            query = REVIEW_TOOL_SCHEMAS[name].model_validate(arguments)
        except ValidationError:
            return {"status": "rejected", "code": "agent_review_arguments_invalid"}
        try:
            with UnitOfWork(self.engine) as uow:
                task, _, run, request, _ = current_run(uow, run_id)
                if request.context.review is None or request.policy.role != "reviewer":
                    raise TaskBoundaryError("agent_role_tool_not_allowed")
                actor = actor_for_command(uow, run["source_command_id"])
                build, facts = read_review_evidence_in_uow(uow, actor, task, request)
                if name == "review.evidence":
                    return safe_context_value(facts)
                if self.reader is None:
                    raise TaskBoundaryError("agent_review_candidate_reader_unavailable")
            try:
                result = self.reader(build, name, query)
            finally:
                with UnitOfWork(self.engine) as uow:
                    current_run(uow, run_id)
            return result
        except (TaskBoundaryError, IdentityError, WorkspaceFileError) as error:
            return {"status": "rejected", "code": error.code}
