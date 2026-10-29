"""Controlled Task provenance registration and exact reference reads.

These functions participate in an already authorized UnitOfWork. No HTTP route
accepts their records. Source bytes are checked in memory and are never persisted
or logged; the stored data is the bounded, schema-validated producer metadata.
"""

import hashlib

import rfc8785
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Connection

from database.uow import require_transaction
from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.tables import task_fact_sources, task_reference_records
from packages.contracts.p0.decision_common import Contract
from packages.contracts.p0.engineering_contracts import EngineeringRef
from packages.contracts.p0.identity_contracts import AuthorizationEnvelope, parse_request
from packages.contracts.p1.task_facts import (
    EnvironmentMetadata, EvidenceMetadata, HumanConclusionMetadata, MethodMetadata, RegisteredReference, TaskFactSource,
)
from packages.contracts.p1.task_requests import TaskDeclaration


def contract_digest(value: Contract) -> str:
    return "sha256:" + hashlib.sha256(rfc8785.dumps(value.model_dump(mode="json"))).hexdigest()


def reference_key(project_id: str, reference: EngineeringRef) -> str:
    value = {"project_id": project_id, "reference": reference.model_dump(mode="json")}
    return "sha256:" + hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def _authorization(authorization: AuthorizationEnvelope, project_id: str, action: str) -> None:
    if (not authorization.allowed or authorization.action != action
            or authorization.scope.project_id != project_id or authorization.target.project_id != project_id):
        raise TaskBoundaryError("fact_registration_not_authorized", status_code=403)


def read_fact_source(connection: Connection, project_id: str, source_id: str) -> TaskFactSource:
    require_transaction(connection)
    row = connection.execute(select(task_fact_sources).where(
        task_fact_sources.c.project_id == project_id, task_fact_sources.c.source_id == source_id,
    )).mappings().one_or_none()
    if row is None or not row["enabled"]:
        raise TaskBoundaryError("fact_source_unavailable", object_ids=(source_id,))
    try:
        source = TaskFactSource.model_validate(row["source_json"])
    except ValidationError:
        raise TaskBoundaryError("fact_source_invalid", object_ids=(source_id,)) from None
    if (source.project_id != project_id or source.source_id != source_id
            or contract_digest(source) != row["source_digest"]):
        raise TaskBoundaryError("fact_source_invalid", object_ids=(source_id,))
    return source


def register_fact_source(
    connection: Connection, source: TaskFactSource, *, authorization: AuthorizationEnvelope,
) -> str:
    """Controlled project-owner setup; re-registration cannot alter or re-enable a source."""
    require_transaction(connection)
    _authorization(authorization, source.project_id, "project.manage")
    if authorization.caller.kind != "human":
        raise TaskBoundaryError("fact_source_setup_requires_human", status_code=403)
    digest = contract_digest(source)
    connection.execute(insert(task_fact_sources).values(
        project_id=source.project_id, source_id=source.source_id,
        source_json=source.model_dump(mode="json"), source_digest=digest,
        authorization_decision_id=authorization.decision_id,
    ).on_conflict_do_nothing())
    row = connection.execute(select(task_fact_sources.c.source_digest).where(
        task_fact_sources.c.project_id == source.project_id,
        task_fact_sources.c.source_id == source.source_id,
    )).one()
    if row.source_digest != digest:
        raise TaskBoundaryError("fact_source_conflict", object_ids=(source.source_id,))
    return source.source_id


def _check_producer(source: TaskFactSource, record: RegisteredReference) -> None:
    domains = {
        "requirement": {"projects"}, "acceptance_assets": {"integration"},
        "source": {"projects", "integration"}, "resource_policy": {"identity"},
        "method": {"projects", "identity", "integration", "execution", "collaboration", "agent-runtime"},
        "environment": {"integration", "execution"},
        "human_policy": {"identity"}, "input_set": {"collaboration", "integration"},
        "candidate": {"integration"}, "human_conclusion": {"integration"},
        "operation": {"execution"},
        "run_history": {"agent-runtime"},
    }
    kind = record.metadata.record_kind
    if kind == "evidence":
        allowed = {"execution"} if record.metadata.role == "operation_closure" else {"integration"}
    else:
        allowed = domains[kind]
    authority = record.reference.authority or "cloudhelm"
    if source.producer_domain not in allowed or source.authority != authority:
        raise TaskBoundaryError("reference_source_mismatch", object_ids=(record.reference.object_id,))
    if kind == "operation" and record.metadata.executor_id not in source.executor_ids:
        raise TaskBoundaryError("operation_source_scope_mismatch", object_ids=(record.reference.object_id,))


def validate_source_payload(record: RegisteredReference, source_bytes: bytes) -> str:
    if not isinstance(source_bytes, bytes) or not 0 < len(source_bytes) <= 1048576:
        raise TaskBoundaryError("reference_source_size_invalid", status_code=422)
    try:
        source_metadata = parse_request(source_bytes.decode("utf-8"), type(record.metadata))
    except (UnicodeDecodeError, ValueError):
        raise TaskBoundaryError("reference_source_payload_invalid", status_code=422) from None
    if source_metadata != record.metadata:
        raise TaskBoundaryError("reference_source_payload_mismatch", status_code=422)
    source_digest = "sha256:" + hashlib.sha256(source_bytes).hexdigest()
    if source_digest != record.reference.digest:
        raise TaskBoundaryError("reference_source_digest_mismatch", status_code=422)
    return source_digest


def register_reference(
    connection: Connection, record: RegisteredReference, *, source_bytes: bytes,
    authorization: AuthorizationEnvelope,
) -> str:
    """Register a producer's metadata envelope, not arbitrary artifact/config bytes."""
    require_transaction(connection)
    _authorization(authorization, record.project_id, "fact.archive")
    source = read_fact_source(connection, record.project_id, record.source_id)
    if authorization.caller != source.principal:
        raise TaskBoundaryError("fact_source_principal_mismatch", status_code=403)
    _check_producer(source, record)
    return _store_reference(connection, record, source_bytes, authorization)


def _store_reference(connection, record, source_bytes, authorization):
    source_digest = validate_source_payload(record, source_bytes)
    key, digest = reference_key(record.project_id, record.reference), contract_digest(record)
    reference = record.reference
    connection.execute(insert(task_reference_records).values(
        reference_key=key, project_id=record.project_id, source_id=record.source_id,
        registration_id=record.registration_id, source_record_id=record.source_record_id,
        record_kind=record.metadata.record_kind, reference_kind=reference.kind,
        object_id=reference.object_id, revision=reference.revision, authority=reference.authority,
        source_content_digest=source_digest, record_digest=digest,
        record_json=record.model_dump(mode="json"), authorization_decision_id=authorization.decision_id,
    ).on_conflict_do_nothing())
    row = connection.execute(select(task_reference_records.c.record_digest).where(
        task_reference_records.c.reference_key == key,
    )).one_or_none()
    if row is None or row.record_digest != digest:
        raise TaskBoundaryError("reference_identity_conflict", object_ids=(reference.object_id,))
    return key


def register_human_test_reference(connection, record, *, source_bytes, authorization):
    """Register only integration-produced facts derived from this human decision."""
    require_transaction(connection)
    target = authorization.target
    actions = {"human_test.pass": "passed", "human_test.request_changes": "changes_requested",
               "human_test.skip": "skipped"}
    result = actions.get(authorization.action)
    if (not authorization.allowed or result is None or authorization.caller.kind != "human"
            or authorization.scope.project_id != record.project_id or target.project_id != record.project_id
            or target.resource_kind != "human_test_session"):
        raise TaskBoundaryError("human_test_fact_registration_not_authorized", status_code=403)
    session_id, metadata = target.resource_id, record.metadata
    source = read_fact_source(connection, record.project_id, record.source_id)
    if (source.producer_domain != "integration" or source.authority != "integration" or source.purpose != "product"
            or record.reference.authority != "integration"):
        raise TaskBoundaryError("human_test_product_source_required")
    if isinstance(metadata, MethodMetadata):
        valid = (record.reference.object_id == "human-method-" + session_id and metadata.description ==
                 "Explicit conclusion by the assigned human tester for the fixed human-test session.")
    elif isinstance(metadata, EnvironmentMetadata):
        valid = (result == "skipped" and record.reference.object_id == "human-not-run-" + session_id
                 and metadata.description == "Human test was not deployed or run; this is a skip decision context."
                 and metadata.support_scope == ("human_test_not_run",))
    elif isinstance(metadata, EvidenceMetadata):
        valid = (metadata.role == "human_test" and metadata.evidence.evidence_id == "human-evidence-" + session_id
                 and metadata.evidence.method_ref.object_id == "human-method-" + session_id
                 and metadata.evidence.result == {"passed": "passed", "changes_requested": "failed",
                                                  "skipped": "not_run"}[result])
    elif isinstance(metadata, HumanConclusionMetadata):
        valid = (record.reference.object_id == "human-conclusion-" + session_id
                 and metadata.session_id == session_id and metadata.concluded_by == authorization.caller
                 and metadata.authorization_decision_id == authorization.decision_id
                 and metadata.conclusion == result and metadata.evidence_ref.object_id == "human-evidence-" + session_id)
    else:
        valid = False
    if not valid:
        raise TaskBoundaryError("human_test_fact_binding_mismatch")
    _check_producer(source, record)
    return _store_reference(connection, record, source_bytes, authorization)


def read_registered_reference(
    connection: Connection, project_id: str, reference: EngineeringRef | str,
) -> RegisteredReference:
    require_transaction(connection)
    key = reference_key(project_id, reference) if isinstance(reference, EngineeringRef) else reference
    row = connection.execute(select(task_reference_records).where(
        task_reference_records.c.reference_key == key, task_reference_records.c.project_id == project_id,
    )).mappings().one_or_none()
    if row is None:
        raise TaskBoundaryError("reference_not_registered", object_ids=(key,))
    try:
        record = RegisteredReference.model_validate(row["record_json"])
    except ValidationError:
        raise TaskBoundaryError("registered_reference_invalid", object_ids=(key,)) from None
    ref = record.reference
    actual = (ref.kind, ref.object_id, ref.revision, ref.authority, record.metadata.record_kind)
    stored = tuple(row[field] for field in ("reference_kind", "object_id", "revision", "authority", "record_kind"))
    if (record.project_id != project_id or record.source_id != row["source_id"] or actual != stored
            or reference_key(project_id, ref) != key or contract_digest(record) != row["record_digest"]
            or record.reference.digest != row["source_content_digest"]
            or record.registration_id != row["registration_id"] or record.source_record_id != row["source_record_id"]
            or isinstance(reference, EngineeringRef) and reference != ref):
        raise TaskBoundaryError("registered_reference_invalid", object_ids=(key,))
    _check_producer(read_fact_source(connection, project_id, record.source_id), record)
    return record


def validate_declaration_references(
    connection: Connection, project_id: str, declaration: TaskDeclaration,
) -> dict[str, RegisteredReference]:
    kinds = {"requirement_ref": "requirement", "acceptance_assets_ref": "acceptance_assets",
             "source_ref": "source", "resource_scope_ref": "resource_policy",
             "human_test_policy_ref": "human_policy"}
    records = {}
    for field, kind in kinds.items():
        record = read_registered_reference(connection, project_id, getattr(declaration, field))
        if record.metadata.record_kind != kind:
            raise TaskBoundaryError("declaration_reference_kind_mismatch", object_ids=(record.reference.object_id,))
        records[field] = record
    method = read_registered_reference(connection, project_id, records["acceptance_assets_ref"].metadata.method_ref)
    if method.metadata.record_kind not in {"method", "acceptance_assets"}:
        raise TaskBoundaryError("acceptance_method_not_registered")
    return records
