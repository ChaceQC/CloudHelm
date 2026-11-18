"""Accept a submitted WorkItem using the current, approved final integration."""

from sqlalchemy import insert, select, update

from modules.collaboration.command_support import TaskCommandContext, command_result, update_task
from modules.collaboration.completion_facts import read_completion_inputs
from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.fact_reads import FactReader
from modules.collaboration.facts import read_declaration
from modules.collaboration.guards import MAX_REVISION, require_ordinary_progress
from modules.collaboration.records import register_work_item_acceptance
from modules.collaboration.rework_records import unresolved_rework
from modules.collaboration.tables import task_evidence_links, work_items
from modules.integration.candidates import _operation_access
from modules.sync.events import append_event
from modules.workspaces.operations import read_workspace_row
from packages.contracts.p1.task_internal import WorkItemAcceptedEvent
from packages.contracts.p1.task_requests import AcceptWorkItemResultRequest


def accept_work_item(context: TaskCommandContext, request: AcceptWorkItemResultRequest):
    connection, task = context.uow.connection, context.task
    require_ordinary_progress(connection, task["task_id"], expected_version=request.expected_version,
        expected_control_revision=request.expected_control_revision,
        expected_input_validity_revision=request.expected_input_validity_revision)
    item = connection.execute(select(work_items).where(
        work_items.c.task_id == task["task_id"], work_items.c.work_item_id == request.work_item_id,
    ).with_for_update()).mappings().one_or_none()
    if item is None:
        raise TaskBoundaryError("work_item_not_found", status_code=404)
    if item["revision"] != request.expected_work_item_revision:
        raise TaskBoundaryError("work_item_revision_conflict")
    if item["state"] != "submitted" or item["declaration_id"] != task["declaration_id"]:
        raise TaskBoundaryError("work_item_not_submitted")
    if item["revision"] == MAX_REVISION:
        raise TaskBoundaryError("revision_exhausted")

    reader = FactReader(connection, task["project_id"], task["task_id"])
    inputs = read_completion_inputs(reader, task, read_declaration(connection, task))
    view, merge, assets = inputs.verification, inputs.merge, inputs.acceptance
    if view is None or view.report.report_id != request.report_id:
        raise TaskBoundaryError("work_item_acceptance_report_not_selected")
    report = view.report
    _operation_access(context.uow, context.actor, task, report.build_operation_id)
    if not inputs.current or merge is None or assets is None:
        raise TaskBoundaryError("work_item_acceptance_evidence_not_current")
    if report.evidence.input_set_ref != request.input_set_ref:
        raise TaskBoundaryError("work_item_acceptance_input_mismatch")
    binding = merge.candidate.binding
    if binding.work_item_id != item["work_item_id"]:
        raise TaskBoundaryError("work_item_acceptance_candidate_mismatch")
    workspace = read_workspace_row(connection, binding.workspace_id)
    if (workspace["workspace_revision"], workspace["write_generation"]) != (
        binding.workspace_revision, binding.write_generation,
    ):
        raise TaskBoundaryError("work_item_acceptance_candidate_stale")
    proof = reader.read(view.evidence_ref, "evidence")
    if (proof is None or report.acceptance_assets_ref != assets.reference
            or report.evidence.method_ref != assets.metadata.method_ref
            or not set(assets.metadata.required_check_ids).issubset(report.passed_check_ids)):
        raise TaskBoundaryError("work_item_acceptance_checks_unsatisfied")
    if any(issue["severity"] == "blocking" for issue in unresolved_rework(
        connection, task, work_item_id=item["work_item_id"],
    )):
        raise TaskBoundaryError("rework_unresolved")

    update_task(context)
    revision = item["revision"] + 1
    input_key, evidence_key = register_work_item_acceptance(connection, view, proof,
        authorization=context.authorization.envelope, acceptance_id="work-item-acceptance-" + context.envelope.command_id,
        work_item_id=item["work_item_id"], work_item_revision=revision)
    connection.execute(insert(task_evidence_links).values(task_id=task["task_id"], evidence_key=evidence_key,
        input_validity_revision=task["input_validity_revision"], input_set_key=input_key, applicability="valid",
        rule_id="final-integration-work-item-acceptance", rule_revision="r1", reason_code="exact_verified_inputs"))
    connection.execute(update(work_items).where(work_items.c.work_item_id == item["work_item_id"]).values(
        state="accepted", revision=revision, blocked_reason=None,
        accepted_input_set_key=input_key, acceptance_evidence_key=evidence_key))
    result = command_result(context, "work_item_accepted", "work_item_accepted")
    append_event(connection, command_id=context.envelope.command_id, project_id=task["project_id"],
        aggregate_kind="task", aggregate_id=task["task_id"], aggregate_version=result.version,
        event_type="task.work_item_accepted", schema_version="p2-work-item-accepted-event-r1",
        payload=WorkItemAcceptedEvent(result=result, work_item_id=item["work_item_id"], work_item_revision=revision,
            input_set_ref=request.input_set_ref, report_evidence_ref=view.evidence_ref))
    return result, 200
