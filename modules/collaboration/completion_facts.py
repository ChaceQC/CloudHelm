"""Build completion inputs and evidence from exact registered producer records."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from modules.collaboration.fact_reads import FactReader, bounded_rows
from modules.collaboration.tables import task_evidence_links, task_inputs, work_items
from packages.contracts.p0.engineering_contracts import EngineeringRef
from packages.contracts.p1.task_facts import (
    CandidateMetadata, EvidenceMetadata, InputSetMetadata, RegisteredReference, SourceMetadata,
)
from packages.contracts.p1.task_requests import TaskDeclaration
from packages.contracts.p2.verification import VerificationView


@dataclass(frozen=True)
class VerificationReference:
    """Read-only metadata projection of the exact integration-owned report facts."""
    reference: EngineeringRef
    metadata: InputSetMetadata | SourceMetadata | CandidateMetadata


@dataclass(frozen=True)
class CompletionInputs:
    row: Mapping[str, Any] | None
    input_set: RegisteredReference | VerificationReference | None
    source: RegisteredReference | VerificationReference | None
    candidate: RegisteredReference | VerificationReference | None
    requirement: RegisteredReference | None
    acceptance: RegisteredReference | None
    policy: RegisteredReference | None
    current: bool
    verification: VerificationView | None = None


@dataclass(frozen=True)
class AcceptanceFacts:
    required_work_items_accepted: bool
    required_acceptance_satisfied: bool
    evidence_current: bool
    evidence_refs: tuple[EngineeringRef, ...]


def read_completion_inputs(
    reader: FactReader, task: Mapping[str, Any], declaration: TaskDeclaration,
) -> CompletionInputs:
    requirement = reader.read(declaration.requirement_ref, "requirement")
    acceptance = reader.read(declaration.acceptance_assets_ref, "acceptance_assets")
    policy = reader.read(declaration.human_test_policy_ref, "human_policy")
    resources = reader.read(declaration.resource_scope_ref, "resource_policy")
    row = reader.connection.execute(select(task_inputs).where(
        task_inputs.c.task_id == task["task_id"],
        task_inputs.c.input_validity_revision == task["input_validity_revision"],
    )).mappings().one_or_none()
    from modules.integration.validity import selected_verification
    from modules.collaboration.records import reference_key

    selected = selected_verification(reader.connection, task)
    if selected is not None:
        from modules.integration.merge_validity import require_merged_report
        from modules.collaboration.errors import TaskBoundaryError

        merged = True
        try:
            require_merged_report(reader.connection, task, selected)
        except TaskBoundaryError:
            merged = False
            reader.block("project_integration_required")
        report = selected.report
        inputs = VerificationReference(report.evidence.input_set_ref, InputSetMetadata(input_set=report.input_set))
        source = VerificationReference(report.source_ref, SourceMetadata(commit=report.source_ref.revision))
        candidate = VerificationReference(report.evidence.subject_ref,
            CandidateMetadata(source_ref=source.reference, input_set_ref=inputs.reference))
        refs = report.input_set.references
        current = bool(merged and selected.usable and row is not None and all(
            item is not None and item.reference in refs for item in (requirement, acceptance, policy, resources)))
        if not current:
            reader.block("input_not_current")
        projected = dict(row or {}, input_set_key=reference_key(reader.project_id, inputs.reference),
                         source_key=reference_key(reader.project_id, source.reference),
                         candidate_key=reference_key(reader.project_id, candidate.reference))
        return CompletionInputs(projected, inputs, source, candidate, requirement, acceptance, policy, current, selected)
    input_set = reader.read(row["input_set_key"] if row else None, "input_set", missing_code="final_input_missing")
    source = reader.read(row["source_key"] if row else None, "source", missing_code="final_source_missing")
    candidate = reader.read(row["candidate_key"] if row else None, "candidate", missing_code="final_candidate_missing")
    reader.block("project_integration_required")
    reader.block("input_not_current")
    return CompletionInputs(row, input_set, source, candidate, requirement, acceptance, policy, False)


def _applicable_evidence(reader: FactReader, task: Mapping[str, Any], inputs: CompletionInputs):
    from modules.integration.validity import require_verification_evidence
    from modules.collaboration.errors import TaskBoundaryError
    from modules.collaboration.records import reference_key

    selected = inputs.verification
    links = bounded_rows(reader.connection, select(task_evidence_links).where(
        task_evidence_links.c.task_id == task["task_id"],
        task_evidence_links.c.input_validity_revision == task["input_validity_revision"],
    ), "evidence_projection_scope_too_large")
    records, current = {}, True
    if selected is not None:
        proof = reader.read(selected.evidence_ref, "evidence")
        current = selected.usable and proof is not None
        if current:
            records[reference_key(reader.project_id, proof.reference)] = proof
    for link in links:
        if selected is not None and link["input_set_key"] != reference_key(reader.project_id, selected.report.evidence.input_set_ref):
            continue
        record = reader.read(link["evidence_key"], "evidence")
        data = record.metadata if record is not None else None
        if (not isinstance(data, EvidenceMetadata) or data.role not in {"verification", "work_item_acceptance"}
                or inputs.row is None or inputs.input_set is None or inputs.candidate is None or inputs.acceptance is None):
            current = False
            continue
        valid = (link["applicability"] == "valid" and link["input_set_key"] == inputs.row["input_set_key"]
                 and data.evidence.input_set_ref == inputs.input_set.reference
                 and data.evidence.subject_ref == inputs.candidate.reference
                 and data.acceptance_assets_ref == inputs.acceptance.reference
                 and data.evidence.method_ref == inputs.acceptance.metadata.method_ref)
        method = reader.read(data.evidence.method_ref)
        environment = reader.read(data.evidence.environment_ref, "environment")
        refs = inputs.input_set.metadata.input_set.references
        valid = bool(valid and method and environment and data.evidence.method_ref in refs
                     and data.evidence.environment_ref in refs
                     and set(data.evidence.support_scope).issubset(environment.metadata.support_scope))
        if valid and data.role == "verification":
            try:
                require_verification_evidence(reader.connection, task, record.reference, data)
            except TaskBoundaryError:
                valid = False
        if not valid:
            current = False
        else:
            records[link["evidence_key"]] = record
    return records, current


def read_acceptance_facts(
    reader: FactReader, task: Mapping[str, Any], inputs: CompletionInputs,
) -> AcceptanceFacts:
    evidence, current = _applicable_evidence(reader, task, inputs)
    checks = set(inputs.acceptance.metadata.required_check_ids) if inputs.acceptance else set()
    required_items = bounded_rows(reader.connection, select(work_items).where(
        work_items.c.task_id == task["task_id"], work_items.c.required.is_(True),
    ), "work_items_scope_too_large")
    items_accepted = bool(required_items and inputs.row is not None)
    if not required_items:
        reader.block("required_work_items_unaccepted")
    for item in required_items:
        proof = evidence.get(item["acceptance_evidence_key"])
        valid = (item["state"] == "accepted" and item["declaration_id"] == task["declaration_id"]
                 and inputs.row is not None and item["accepted_input_set_key"] == inputs.row["input_set_key"]
                 and proof is not None and proof.metadata.role == "work_item_acceptance"
                 and proof.metadata.work_item_id == item["work_item_id"]
                 and proof.metadata.work_item_revision == item["revision"]
                 and proof.metadata.evidence.result == "passed" and checks.issubset(proof.metadata.check_ids))
        if not valid:
            items_accepted = False
            reader.block("required_work_items_unaccepted", item["work_item_id"], "work_item")
    covered = set()
    all_passed = bool(evidence)
    for record in evidence.values():
        if record.metadata.evidence.result != "passed":
            all_passed = False
        else:
            covered.update(record.metadata.check_ids)
    accepted = bool(checks and checks.issubset(covered) and all_passed and current)
    if not accepted:
        reader.block("required_acceptance_unsatisfied")
    if not current or not evidence:
        reader.block("evidence_not_applicable")
    return AcceptanceFacts(items_accepted, accepted, bool(current and evidence),
                           tuple(record.reference for record in evidence.values()))
