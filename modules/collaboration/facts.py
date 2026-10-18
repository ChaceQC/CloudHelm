"""Task control projection from a complete, bounded same-transaction database view."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.engine import Connection

from modules.collaboration.completion_facts import read_acceptance_facts, read_completion_inputs
from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.fact_reads import FactReader, bounded_rows
from modules.collaboration.guards import read_task
from modules.collaboration.human_facts import read_human_fact
from modules.collaboration.operation_facts import read_operation_facts
from modules.collaboration.operation_projection import merge_operation_facts
from modules.collaboration.records import contract_digest, reference_key
from modules.collaboration.tables import (
    task_completion_reports, task_declarations, task_run_links, task_wait_conditions,
)
from packages.contracts.p0.engineering_contracts import EngineeringRef
from packages.contracts.p0.identity_contracts import Principal
from packages.contracts.p0.task_control_contracts import (
    CancellationIntent, CompletionBasis, OperationClosureFact, TaskCompletionReport, TaskControlFacts,
)
from packages.contracts.p1.task_facts import EvidenceMetadata
from packages.contracts.p1.task_requests import TaskDeclaration
from packages.contracts.p1.task_results import TaskBlocker


@dataclass(frozen=True)
class TaskControlSnapshot:
    task: Mapping[str, Any]
    declaration: TaskDeclaration
    facts: TaskControlFacts
    blockers: tuple[TaskBlocker, ...]


_OPERATION_SOURCE_SCOPE_ERRORS = frozenset({
    "operation_projection_scope_too_large", "engineering_operation_scope_too_large",
    "workspace_operation_scope_too_large", "build_operation_scope_too_large",
    "workspace_development_operation_scope_too_large",
})


def read_declaration(connection: Connection, task: Mapping[str, Any]) -> TaskDeclaration:
    row = connection.execute(select(task_declarations).where(
        task_declarations.c.declaration_id == task["declaration_id"],
        task_declarations.c.project_id == task["project_id"],
    )).mappings().one_or_none()
    if row is None:
        raise TaskBoundaryError("task_declaration_missing")
    try:
        declaration = TaskDeclaration.model_validate(row["declaration_json"])
    except ValidationError:
        raise TaskBoundaryError("task_declaration_invalid") from None
    if contract_digest(declaration) != row["declaration_digest"]:
        raise TaskBoundaryError("task_declaration_invalid")
    return declaration


def read_completion_report(
    connection: Connection, task: Mapping[str, Any],
) -> TaskCompletionReport | None:
    if task["completion_report_id"] is None:
        return None
    row = connection.execute(select(task_completion_reports).where(
        task_completion_reports.c.report_id == task["completion_report_id"],
        task_completion_reports.c.task_id == task["task_id"],
    )).mappings().one_or_none()
    if row is None:
        return None
    try:
        report = TaskCompletionReport.model_validate(row["report_json"])
    except ValidationError:
        raise TaskBoundaryError("completion_report_invalid") from None
    if (report.task_id != task["task_id"] or report.report_id != row["report_id"]
            or report.completion_command.envelope.command_id != row["command_id"]
            or contract_digest(report) != row["report_digest"]):
        raise TaskBoundaryError("completion_report_invalid")
    return report


def read_control_head(connection: Connection, task: Mapping[str, Any]) -> TaskControlFacts:
    """Read only fixed history before dedupe/terminal branches; do not re-evaluate evidence."""
    cancellation = None
    if task["cancel_requested_at"] is not None:
        cancellation = CancellationIntent(
            command_id=task["cancel_command_id"],
            cancel_requested_at=task["cancel_requested_at"].astimezone(UTC),
            cancel_requested_by=Principal.model_validate(task["cancel_requested_by"]),
            cancel_reason=task["cancel_reason"], control_revision=task["cancel_control_revision"],
        )
    return TaskControlFacts(
        task_id=task["task_id"], state=task["state"], version=task["version"],
        control_revision=task["control_revision"], input_validity_revision=task["input_validity_revision"],
        cancellation=cancellation, ordinary_progress_closed=task["ordinary_progress_closed"],
        completion_report=read_completion_report(connection, task),
    )


def _waits_satisfied(reader: FactReader, input_set_ref) -> bool:
    waits = bounded_rows(reader.connection, select(task_wait_conditions).where(
        task_wait_conditions.c.task_id == reader.task_id,
        task_wait_conditions.c.required_for_completion.is_(True),
    ), "wait_projection_scope_too_large")
    ready = True
    key = reference_key(reader.project_id, input_set_ref) if input_set_ref else None
    for wait in waits:
        proof = reader.read(wait["conclusion_evidence_key"], "evidence")
        data = proof.metadata if proof else None
        if (wait["state"] != "satisfied" or key is None or wait["input_set_key"] != key
                or not isinstance(data, EvidenceMetadata) or data.evidence.result != "passed"
                or data.evidence.input_set_ref != input_set_ref):
            ready = False
            reader.block("required_waits_unresolved", wait["wait_condition_id"], "wait_condition")
    return ready


def _run_history(reader: FactReader, task: Mapping[str, Any]) -> tuple[bool, bool]:
    runs = bounded_rows(reader.connection, select(task_run_links).where(
        task_run_links.c.task_id == task["task_id"],
    ), "run_projection_scope_too_large")
    fenced = bool(task["ordinary_progress_closed"])
    for run in runs:
        history = reader.read(run["history_key"], "run_history")
        if (history is None or history.metadata.run_id != run["run_id"]
                or history.metadata.run_revision != run["run_revision"]
                or run["fenced_control_revision"] is None
                or run["fenced_control_revision"] < task["control_revision"]):
            fenced = False
    # No model calls exist in P1.1. A later runtime link without its fee-domain
    # projection leaves usage unknown; this is never an amount or a zero charge.
    return fenced, bool(runs)


def _read_task_operation_projection(
    connection: Connection, task: Mapping[str, Any], input_set_ref: EngineeringRef | None, *,
    for_cancellation: bool = False,
) -> tuple[OperationClosureFact, ...]:
    """Combine Task and engineering operations under one complete projection bound."""
    from modules.collaboration.engineering_operations import read_engineering_operation_blockers

    try:
        task_operations = read_operation_facts(
            connection, task, input_set_ref, for_cancellation=for_cancellation,
        )
        engineering_operations = read_engineering_operation_blockers(connection, task["task_id"])
        return merge_operation_facts(task_operations, engineering_operations)
    except TaskBoundaryError as error:
        if error.code in _OPERATION_SOURCE_SCOPE_ERRORS:
            raise TaskBoundaryError("task_fact_projection_scope_too_large") from None
        raise


def _completion_basis(reader: FactReader, inputs, acceptance, human, operations, revision: int):
    if not inputs.current or not acceptance.evidence_refs:
        return None
    refs = {reference_key(reader.project_id, ref): ref for ref in acceptance.evidence_refs}
    for operation in operations:
        if operation.affects_completion and operation.closure_evidence_ref is not None:
            refs[reference_key(reader.project_id, operation.closure_evidence_ref)] = operation.closure_evidence_ref
    if human.is_completion_gate and human.conclusion_evidence_ref is not None:
        refs[reference_key(reader.project_id, human.conclusion_evidence_ref)] = human.conclusion_evidence_ref
    if len(refs) > 128:
        raise TaskBoundaryError("completion_evidence_scope_too_large")
    return CompletionBasis(
        requirement_ref=inputs.requirement.reference, acceptance_assets_ref=inputs.acceptance.reference,
        final_candidate_ref=inputs.candidate.reference, integrated_source_ref=inputs.source.reference,
        input_set_ref=inputs.input_set.reference, input_validity_revision=revision,
        required_check_ids=inputs.acceptance.metadata.required_check_ids,
        required_evidence_refs=tuple(refs[key] for key in sorted(refs)), human_test=human,
    )


def load_task_control_facts(connection: Connection, task_id: str) -> TaskControlSnapshot:
    """Call after identity/policy locks and only for a genuinely new transition.

    Same-key results and a completed Task use read_control_head first. This function
    may reject an oversized/incomplete live projection; it must not replace those
    fixed-response paths with a new verification attempt.
    """
    task = read_task(connection, task_id, for_update=True)
    declaration = read_declaration(connection, task)
    reader = FactReader(connection, task["project_id"], task_id)
    inputs = read_completion_inputs(reader, task, declaration)
    acceptance = read_acceptance_facts(reader, task, inputs)
    input_ref = inputs.input_set.reference if inputs.input_set else None
    operations = _read_task_operation_projection(connection, task, input_ref)
    human = read_human_fact(reader, inputs, declaration)
    waits_ready = _waits_satisfied(reader, input_ref)
    history_fenced, usage_unknown = _run_history(reader, task)
    for operation in operations:
        if operation.affects_completion and (operation.closure not in {
            "closed_unstarted", "ended_reconciled", "safely_stopped",
        } or not operation.effects_recorded or operation.closure_evidence_ref is None):
            reader.block("writes_unsettled", operation.operation_ref.object_id, "operation")
    basis = _completion_basis(reader, inputs, acceptance, human, operations, task["input_validity_revision"])
    data = read_control_head(connection, task).model_dump()
    data.update(
        basis=basis, input_current=inputs.current,
        required_work_items_accepted=acceptance.required_work_items_accepted,
        required_acceptance_satisfied=acceptance.required_acceptance_satisfied,
        evidence_current=acceptance.evidence_current, required_waits_satisfied=waits_ready,
        # The Task row lock serializes every admitted intent/link and its revision.
        # The bounded query enumerated the entire set; unknown receipts remain in it.
        operation_set_current=True, operations=operations,
        run_history_saved_and_fenced=history_fenced, unknown_model_usage_present=usage_unknown,
    )
    return TaskControlSnapshot(task, declaration, TaskControlFacts.model_validate(data), tuple(reader.blockers))


def load_cancellation_facts(connection: Connection, task_id: str) -> TaskControlFacts:
    """Cancellation needs physical closure and history, not a completed delivery input."""
    task = read_task(connection, task_id, for_update=True)
    reader = FactReader(connection, task["project_id"], task_id)
    operations = _read_task_operation_projection(connection, task, None, for_cancellation=True)
    history_fenced, usage_unknown = _run_history(reader, task)
    data = read_control_head(connection, task).model_dump()
    data.update(operation_set_current=True, operations=operations,
                run_history_saved_and_fenced=history_fenced, unknown_model_usage_present=usage_unknown)
    return TaskControlFacts.model_validate(data)
