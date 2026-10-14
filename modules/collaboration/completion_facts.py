"""Build completion inputs and evidence from exact registered producer records."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from modules.collaboration.fact_reads import FactReader, bounded_rows
from modules.collaboration.tables import task_evidence_links, task_inputs, work_items
from packages.contracts.p0.engineering_contracts import EngineeringRef
from packages.contracts.p1.task_facts import EvidenceMetadata, RegisteredReference
from packages.contracts.p1.task_requests import TaskDeclaration


@dataclass(frozen=True)
class CompletionInputs:
    row: Mapping[str, Any] | None
    input_set: RegisteredReference | None
    source: RegisteredReference | None
    candidate: RegisteredReference | None
    requirement: RegisteredReference | None
    acceptance: RegisteredReference | None
    policy: RegisteredReference | None
    current: bool


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
    input_set = reader.read(row["input_set_key"] if row else None, "input_set", missing_code="final_input_missing")
    source = reader.read(row["source_key"] if row else None, "source", missing_code="final_source_missing")
    candidate = reader.read(row["candidate_key"] if row else None, "candidate", missing_code="final_candidate_missing")
    current = bool(task["input_status"] == "valid" and all(
        item is not None for item in (input_set, source, candidate, requirement, acceptance, policy, resources)
    ))
    if current:
        refs = input_set.metadata.input_set.references
        required = (requirement.reference, acceptance.reference, source.reference, policy.reference, resources.reference)
        current = (all(ref in refs for ref in required)
                   and candidate.metadata.source_ref == source.reference
                   and candidate.metadata.input_set_ref == input_set.reference)
        for ref in refs:
            if reader.read(ref) is None:
                current = False
    if not current:
        reader.block("input_not_current")
    return CompletionInputs(row, input_set, source, candidate, requirement, acceptance, policy, current)


def _applicable_evidence(reader: FactReader, task: Mapping[str, Any], inputs: CompletionInputs):
    links = bounded_rows(reader.connection, select(task_evidence_links).where(
        task_evidence_links.c.task_id == task["task_id"],
        task_evidence_links.c.input_validity_revision == task["input_validity_revision"],
    ), "evidence_projection_scope_too_large")
    records, current = {}, True
    for link in links:
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
