"""Append-only operation receipts and conservative Task-side closure projection."""

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Connection

from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.guards import read_task
from modules.collaboration.records import (
    _authorization, contract_digest, read_fact_source, read_registered_reference,
)
from modules.collaboration.tables import task_operation_links, task_operation_observations
from packages.contracts.p0.engineering_contracts import EngineeringRef
from packages.contracts.p0.identity_contracts import AuthorizationEnvelope
from packages.contracts.p0.task_control_contracts import OperationClosureFact
from packages.contracts.p1.task_facts import EvidenceMetadata, OperationObservation, operation_assertion_digest

SETTLED = {"closed_unstarted", "ended_reconciled", "safely_stopped"}


def observation_head(observations: tuple[OperationObservation, ...]) -> OperationObservation | None:
    """Only an explicit, fully connected reconciliation chain can supersede receipts."""
    by_id = {item.observation_id: item for item in observations}
    if not by_id or len(by_id) != len(observations):
        return None
    superseded = set()
    for item in observations:
        for previous_id in item.supersedes_observation_ids:
            previous = by_id.get(previous_id)
            if previous is None or previous.operation_ref != item.operation_ref:
                return None
            if previous.control_revision > item.control_revision:
                return None
            if previous.closure in SETTLED and previous.closure != item.closure:
                return None
            superseded.add(previous_id)
    heads = set(by_id) - superseded
    if len(heads) != 1:
        return None
    head = by_id[heads.pop()]
    visited, visiting = set(), set()

    def visit(identity: str) -> bool:
        if identity in visiting:
            return False
        if identity in visited:
            return True
        visiting.add(identity)
        if not all(visit(previous) for previous in by_id[identity].supersedes_observation_ids):
            return False
        visiting.remove(identity)
        visited.add(identity)
        return True

    return head if visit(head.observation_id) and len(visited) == len(by_id) else None


def _binding_matches(
    connection: Connection, task: Mapping[str, Any], link: Mapping[str, Any], receipt: OperationObservation,
) -> bool:
    input_record = read_registered_reference(connection, task["project_id"], link["input_set_key"])
    operation_ref = EngineeringRef.model_validate(link["operation_ref"])
    return (
        receipt.project_id == task["project_id"] and receipt.task_id == task["task_id"]
        and receipt.operation_ref == operation_ref and receipt.operation_ref.object_id == link["operation_id"]
        and receipt.attempt_id == link["attempt_id"] and receipt.executor_id == link["executor_id"]
        and receipt.executor_generation == link["executor_generation"]
        and receipt.input_set_ref == input_record.reference
        and receipt.effect_scope_digest == link["effect_scope_digest"]
        and link["admitted_control_revision"] <= receipt.control_revision <= task["control_revision"]
    )


def _evidence_matches(
    connection: Connection, receipt: OperationObservation, evidence_ref: EngineeringRef,
) -> bool:
    evidence = read_registered_reference(connection, receipt.project_id, evidence_ref)
    data = evidence.metadata
    return (isinstance(data, EvidenceMetadata) and data.role == "operation_closure"
            and evidence.source_id == receipt.source_id and data.evidence.result == "passed"
            and evidence.source_record_id == receipt.source_record_id
            and data.fact_digest == operation_assertion_digest(receipt)
            and data.evidence.subject_ref == receipt.operation_ref
            and data.evidence.input_set_ref == receipt.resulting_input_set_ref)


def register_operation_observation(
    connection: Connection, receipt: OperationObservation, *, authorization: AuthorizationEnvelope,
) -> str:
    """Archive scoped producer facts without updating physical state or Task progress."""
    _authorization(authorization, receipt.project_id, "fact.archive")
    source = read_fact_source(connection, receipt.project_id, receipt.source_id)
    if (authorization.caller != source.principal or source.producer_domain != "execution"
            or receipt.executor_id not in source.executor_ids):
        raise TaskBoundaryError("operation_fact_source_mismatch", status_code=403)
    task = read_task(connection, receipt.task_id, for_update=True)
    link = connection.execute(select(task_operation_links).where(
        task_operation_links.c.task_id == receipt.task_id,
        task_operation_links.c.operation_id == receipt.operation_ref.object_id,
    )).mappings().one_or_none()
    if link is None or not _binding_matches(connection, task, link, receipt):
        raise TaskBoundaryError("operation_fact_binding_mismatch")
    read_registered_reference(connection, receipt.project_id, receipt.resulting_input_set_ref)
    read_registered_reference(connection, receipt.project_id, receipt.evidence_ref)
    if receipt.closure in SETTLED and not _evidence_matches(connection, receipt, receipt.evidence_ref):
        raise TaskBoundaryError("operation_closure_evidence_mismatch")
    if receipt.reconciliation_evidence_ref is not None and not _evidence_matches(
        connection, receipt, receipt.reconciliation_evidence_ref,
    ):
        raise TaskBoundaryError("operation_reconciliation_evidence_mismatch")
    for previous_id in receipt.supersedes_observation_ids:
        previous = connection.execute(select(task_operation_observations.c.observation_id).where(
            task_operation_observations.c.observation_id == previous_id,
            task_operation_observations.c.task_id == receipt.task_id,
            task_operation_observations.c.operation_id == receipt.operation_ref.object_id,
        )).one_or_none()
        if previous is None:
            raise TaskBoundaryError("operation_observation_predecessor_missing")
    digest = contract_digest(receipt)
    connection.execute(insert(task_operation_observations).values(
        observation_id=receipt.observation_id, task_id=receipt.task_id,
        operation_id=receipt.operation_ref.object_id, project_id=receipt.project_id,
        source_id=receipt.source_id, record_digest=digest,
        observation_json=receipt.model_dump(mode="json"), authorization_decision_id=authorization.decision_id,
    ).on_conflict_do_nothing())
    stored = connection.execute(select(task_operation_observations.c.record_digest).where(
        task_operation_observations.c.observation_id == receipt.observation_id,
    )).one()
    if stored.record_digest != digest:
        raise TaskBoundaryError("operation_observation_conflict")
    return receipt.observation_id


def _read_observations(
    connection: Connection, task: Mapping[str, Any], link: Mapping[str, Any],
) -> tuple[OperationObservation, ...]:
    rows = connection.execute(select(task_operation_observations).where(
        task_operation_observations.c.task_id == task["task_id"],
        task_operation_observations.c.operation_id == link["operation_id"],
    ).limit(129)).mappings().all()
    if len(rows) > 128:
        raise TaskBoundaryError("operation_observations_scope_too_large")
    receipts = []
    for row in rows:
        receipt = OperationObservation.model_validate(row["observation_json"])
        source = read_fact_source(connection, receipt.project_id, receipt.source_id)
        if (receipt.observation_id != row["observation_id"] or contract_digest(receipt) != row["record_digest"]
                or receipt.source_id != row["source_id"] or receipt.project_id != row["project_id"]
                or source.producer_domain != "execution" or receipt.executor_id not in source.executor_ids
                or not _binding_matches(connection, task, link, receipt)):
            raise TaskBoundaryError("operation_observation_invalid")
        if receipt.reconciliation_evidence_ref is not None and not _evidence_matches(
            connection, receipt, receipt.reconciliation_evidence_ref,
        ):
            raise TaskBoundaryError("operation_reconciliation_evidence_mismatch")
        receipts.append(receipt)
    return tuple(receipts)


def read_operation_facts(
    connection: Connection, task: Mapping[str, Any], input_set_ref: EngineeringRef | None,
    *, for_cancellation: bool = False,
) -> tuple[OperationClosureFact, ...]:
    links = connection.execute(select(task_operation_links).where(
        task_operation_links.c.task_id == task["task_id"],
    ).order_by(task_operation_links.c.operation_id).limit(129)).mappings().all()
    if len(links) > 128:
        raise TaskBoundaryError("operation_projection_scope_too_large")
    facts = []
    for link in links:
        fact = dict(operation_ref=EngineeringRef.model_validate(link["operation_ref"]),
                    owner_kind=link["owner_kind"], owner_id=link["owner_id"],
                    affects_completion=link["affects_completion"], closure="unknown")
        try:
            head = observation_head(_read_observations(connection, task, link))
            current = (head is not None and (for_cancellation or (
                head.control_revision == task["control_revision"] and head.resulting_input_set_ref == input_set_ref
            )))
            reconciled = (head is not None and (not head.supersedes_observation_ids or
                          _evidence_matches(connection, head, head.reconciliation_evidence_ref)))
            if current and reconciled and _evidence_matches(connection, head, head.evidence_ref):
                fact.update(closure=head.closure, closure_evidence_ref=head.evidence_ref,
                            effects_recorded=head.effects_recorded)
        except (TaskBoundaryError, ValidationError):
            pass  # An untrusted/incomplete receipt keeps this known operation unknown.
        facts.append(OperationClosureFact(**fact))
    return tuple(facts)
