"""Projects-owned method and actual commit metadata from verified import receipts."""

import rfc8785

from modules.collaboration.records import contract_digest, register_fact_source, register_reference
from packages.contracts.p0.engineering_contracts import EngineeringRef
from packages.contracts.p1.task_facts import MethodMetadata, RegisteredReference, SourceMetadata, TaskFactSource


def source_import_producer_id(command_id: str) -> str:
    return "source-import-producer-" + command_id


def register_imported_source_reference(uow, row, receipt, actor, management, archive, observed_at):
    """Use real current authorization envelopes, never caller-supplied allowed flags."""
    method = MethodMetadata(description=(
        "CloudHelm fixed reference r1 import: trusted ReferenceSourceImporter.query rechecks "
        "the published bare repository, exact source tree, file hashes and manifest."
    ))
    method_ref = EngineeringRef(kind="method", object_id="cloudhelm-reference-import",
                                revision="p1-reference-import-r1", authority="projects",
                                digest=contract_digest(method), digest_algorithm="sha256")
    producer_id = source_import_producer_id(row["command_id"])
    producer = TaskFactSource(
        project_id=row["project_id"], source_id=producer_id, producer_domain="projects",
        authority="projects", principal=actor.principal, purpose="product", method_ref=method_ref,
    )
    register_fact_source(uow.connection, producer, authorization=management.envelope)
    register_reference(uow.connection, RegisteredReference(
        project_id=row["project_id"], registration_id="source-method-registration-" + row["command_id"],
        source_id=producer_id, source_record_id="reference-import-method-r1", reference=method_ref,
        metadata=method, observed_at_utc=observed_at,
    ), source_bytes=rfc8785.dumps(method.model_dump(mode="json")), authorization=archive.envelope)
    metadata = SourceMetadata(commit=receipt.import_commit)
    source_ref = EngineeringRef(kind="source", object_id=receipt.source.source_id,
                                revision=receipt.import_commit, authority="projects",
                                digest=contract_digest(metadata), digest_algorithm="sha256")
    register_reference(uow.connection, RegisteredReference(
        project_id=row["project_id"], registration_id="source-registration-" + row["command_id"],
        source_id=producer_id, source_record_id=row["operation_id"], reference=source_ref,
        metadata=metadata, observed_at_utc=observed_at,
    ), source_bytes=rfc8785.dumps(metadata.model_dump(mode="json")), authorization=archive.envelope)
    return source_ref
