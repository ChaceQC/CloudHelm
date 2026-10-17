"""Verify published Git facts outside a UoW, then atomically register their metadata."""

from dataclasses import dataclass, field
from datetime import UTC, datetime

import rfc8785
from pydantic import model_validator
from sqlalchemy import insert, select

from database.readiness import assert_schema_ready
from database.uow import UnitOfWork, require_transaction
from modules.collaboration.records import read_fact_source, read_registered_reference
from modules.identity.actors import AuthoritativeResource, actor_for_command
from modules.identity.authorization import authorize_current
from modules.projects.source_operations import SourceImportError, read_import_intent
from modules.projects.source_producer import register_imported_source_reference, source_import_producer_id
from modules.projects.source_tables import project_git_sources
from modules.sync.events import append_event
from modules.sync.tables import event_log
from modules.workspaces.source_import import ReferenceImportReceipt, ReferenceSourceImporter
from packages.contracts.p0.decision_common import Contract
from packages.contracts.p1.source_records import SourceImportRegistration
from packages.contracts.p1.task_facts import SourceMetadata
from packages.contracts.p1.workspace_git import content_digest
from packages.contracts.p1.workspace_records import GitSourceRecord, workspace_metadata_digest

_PUBLISHED_PROOF = object()


def source_receipt_digest(receipt: ReferenceImportReceipt) -> str:
    return content_digest(rfc8785.dumps(receipt.model_dump(mode="json")))


@dataclass(frozen=True, slots=True)
class _VerifiedPublishedImport:
    receipt: ReferenceImportReceipt
    observed_at: datetime
    _proof: object = field(repr=False, compare=False)

    def __post_init__(self):
        if self._proof is not _PUBLISHED_PROOF:
            raise SourceImportError("verified_source_receipt_required")


class _SourceImportedEvent(Contract):
    registration: SourceImportRegistration
    receipt: ReferenceImportReceipt

    @model_validator(mode="after")
    def check_receipt(self):
        registration = self.registration
        if (registration.operation_id != self.receipt.operation_id
                or registration.source_record.source != self.receipt.source
                or registration.source_ref.revision != self.receipt.import_commit
                or registration.receipt_digest != source_receipt_digest(self.receipt)):
            raise ValueError("source_registration_receipt_mismatch")
        return self


def verify_published_import(operation_id: str, importer: ReferenceSourceImporter) -> _VerifiedPublishedImport:
    """Call only outside database transactions; a raw DTO/provider is not a proof."""
    if type(importer) is not ReferenceSourceImporter:
        raise SourceImportError("trusted_source_importer_required")
    status = importer.query(operation_id)
    if status.state != "published" or status.receipt is None:
        raise SourceImportError("source_import_not_published")
    receipt = ReferenceImportReceipt.model_validate(status.receipt.model_dump(mode="python"))
    if (receipt.operation_id != operation_id or status.operation_id != operation_id
            or receipt.request_digest != status.request_digest):
        raise SourceImportError("source_import_receipt_binding_mismatch")
    return _VerifiedPublishedImport(receipt, datetime.now(UTC), _PUBLISHED_PROOF)


def _event_id(command_id: str) -> str:
    return "source-import-registered-" + command_id


def read_source_registration(connection, row) -> SourceImportRegistration | None:
    """Read an immutable registration fact; this is not a live storage health check."""
    event = connection.execute(select(event_log).where(
        event_log.c.event_id == _event_id(row["command_id"]),
    )).mappings().one_or_none()
    if event is None:
        return None
    try:
        payload = _SourceImportedEvent.model_validate(event["payload"])
        registration = payload.registration
        if not all((event["command_id"] == row["command_id"], event["project_id"] == row["project_id"],
                    event["aggregate_kind"] == "project_source", event["aggregate_id"] == row["source_id"],
                    event["aggregate_version"] == 1, event["event_type"] == "project.source_registered",
                    event["schema_version"] == "p1-source-registration-event-r1",
                    registration.operation_id == row["operation_id"],
                    payload.receipt.request_digest == row["request_digest"],
                    registration.source_record.registered_by_command_id == row["command_id"])):
            raise ValueError
        stored = connection.execute(select(project_git_sources).where(
            project_git_sources.c.project_id == row["project_id"],
        )).mappings().one_or_none()
        if stored is None:
            raise ValueError
        source = registration.source_record
        if not all((stored["source_json"] == source.source.model_dump(mode="json"),
                    stored["source_digest"] == source.source_digest,
                    stored["registered_by_command_id"] == source.registered_by_command_id,
                    stored["authorization_decision_id"] == source.authorization_decision_id,
                    stored["registered_at"] == source.registered_at)):
            raise ValueError
        record = read_registered_reference(connection, row["project_id"], registration.source_ref)
        producer = read_fact_source(connection, row["project_id"], record.source_id)
        if (not isinstance(record.metadata, SourceMetadata) or record.metadata.commit != payload.receipt.import_commit
                or record.source_id != source_import_producer_id(row["command_id"])
                or producer.producer_domain != "projects" or producer.purpose != "product"):
            raise ValueError
    except (ValueError, TypeError, KeyError):
        raise SourceImportError("source_registration_fact_invalid") from None
    return registration


def register_published_import(
    uow: UnitOfWork, operation_id: str, verified: _VerifiedPublishedImport,
) -> SourceImportRegistration:
    """Caller-owned short transaction; private proof can only come from a real query."""
    require_transaction(uow.connection)
    if type(verified) is not _VerifiedPublishedImport or verified._proof is not _PUBLISHED_PROOF:
        raise SourceImportError("verified_source_receipt_required")
    assert_schema_ready(uow.connection)
    row, spec = read_import_intent(uow.connection, operation_id)
    actor = actor_for_command(uow, row["command_id"])
    resource = AuthoritativeResource(row["project_id"], "project", row["project_id"])
    management = authorize_current(uow, actor, resource, "project.manage")
    authorize_current(uow, actor, resource, "resource.read")
    receipt = verified.receipt
    if (receipt.operation_id != operation_id or receipt.source != spec.source
            or receipt.request_digest != row["request_digest"]):
        raise SourceImportError("source_import_receipt_binding_mismatch")
    existing = read_source_registration(uow.connection, row)
    digest = source_receipt_digest(receipt)
    if existing is not None:
        if existing.receipt_digest != digest:
            raise SourceImportError("source_import_physical_digest_conflict")
        return existing
    if uow.connection.scalar(select(project_git_sources.c.project_id).where(
        project_git_sources.c.project_id == row["project_id"],
    )) is not None:
        raise SourceImportError("project_source_registration_conflict")
    archive = authorize_current(uow, actor, resource, "fact.archive")
    source_ref = register_imported_source_reference(
        uow, row, receipt, actor, management, archive, verified.observed_at,
    )
    stored = uow.connection.execute(insert(project_git_sources).values(
        project_id=row["project_id"], source_id=receipt.source.source_id, source_revision=receipt.source.source_revision,
        source_json=receipt.source.model_dump(mode="json"), source_digest=workspace_metadata_digest(receipt.source),
        registered_by_command_id=row["command_id"], authorization_decision_id=management.envelope.decision_id,
    ).returning(*project_git_sources.c)).mappings().one()
    source_record = GitSourceRecord(
        source=receipt.source, source_digest=stored["source_digest"],
        registered_by_command_id=stored["registered_by_command_id"],
        authorization_decision_id=stored["authorization_decision_id"], registered_at=stored["registered_at"],
    )
    registration = SourceImportRegistration(operation_id=operation_id, receipt_digest=digest,
                                             source_record=source_record, source_ref=source_ref)
    append_event(uow.connection, command_id=row["command_id"], project_id=row["project_id"],
                 aggregate_kind="project_source", aggregate_id=row["source_id"], aggregate_version=1,
                 event_type="project.source_registered", schema_version="p1-source-registration-event-r1",
                 event_id=_event_id(row["command_id"]),
                 payload=_SourceImportedEvent(registration=registration, receipt=receipt))
    return registration
