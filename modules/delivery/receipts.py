"""Trusted I/O first, then caller-owned metadata transaction; no public result writer."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import select

from database.readiness import assert_schema_ready
from database.uow import require_transaction
from modules.artifacts.content_store import ArtifactStore
from modules.collaboration.command_support import lock_task_access
from modules.collaboration.tables import task_inputs
from modules.delivery.errors import BuildBoundaryError
from modules.delivery.queries import (
    SETTLED_BUILD_CLOSURES, observation_event_id, read_build_content, read_build_execution, read_build_intent,
)
from modules.identity.actors import AuthoritativeResource, actor_for_command
from modules.identity.authorization import authorize_current
from modules.sync.events import append_event
from modules.sync.tables import event_log
from packages.contracts.p1.build_records import (
    BuildArtifactLocator, BuildArtifactRecord, BuildContentRegistration, BuildExecutionObservation,
    BuildObservationRegistration, BuildRunRecord, build_artifact_record,
)

_CONTENT_PROOF, _EXECUTION_PROOF = object(), object()


@dataclass(frozen=True, slots=True)
class _VerifiedBuildContent:
    operation_id: str
    build_input_digest: str
    artifacts: tuple[BuildArtifactRecord, ...]
    observed_at: datetime
    _proof: object = field(repr=False, compare=False)

    def __post_init__(self):
        if self._proof is not _CONTENT_PROOF:
            raise BuildBoundaryError("verified_build_content_required")


class BuildExecutionProducer(Protocol):
    """Trusted Runner adapter supplied by the composition root, never request data.

    Its implementation must query its durable operation journal and actual process,
    exporter/load/inspect and stopped-resource facts. A candidate script's status,
    an OCI DTO or a public allowed/passed flag cannot implement this boundary.
    """

    def read_verified_build_observation(self, operation_id: str) -> BuildExecutionObservation: ...


@dataclass(frozen=True, slots=True)
class _VerifiedBuildObservation:
    observation: BuildExecutionObservation
    _proof: object = field(repr=False, compare=False)

    def __post_init__(self):
        if self._proof is not _EXECUTION_PROOF:
            raise BuildBoundaryError("verified_build_observation_required")


def verify_build_content(record: BuildRunRecord, store: ArtifactStore,
                         artifacts: tuple[BuildArtifactLocator, ...]) -> _VerifiedBuildContent:
    """Outside any UoW, rehash all three archives through the real content store."""
    if type(record) is not BuildRunRecord or type(store) is not ArtifactStore:
        raise BuildBoundaryError("trusted_build_content_store_required")
    record = BuildRunRecord.model_validate(record.model_dump(mode="python"))
    try:
        locators = tuple(BuildArtifactLocator.model_validate(item.model_dump(mode="python")) for item in artifacts)
        if len(locators) != 3 or {item.role for item in locators} != set(record.fixed_inputs.definition.output_roles):
            raise ValueError
    except (ValueError, AttributeError):
        raise BuildBoundaryError("build_artifact_roles_incomplete") from None
    content = tuple(build_artifact_record(item.role, store.query(item.storage_id))
                    for item in sorted(locators, key=lambda item: item.role))
    return _VerifiedBuildContent(record.operation_id, record.build_input_digest, content, datetime.now(UTC), _CONTENT_PROOF)


def verify_build_observation(operation_id: str, producer: BuildExecutionProducer) -> _VerifiedBuildObservation:
    """Internal collector protocol; only a trusted adapter may supply producer.

    R7 binds the adapter to registered Runner operation identity and physical
    facts. This function has no API route and never accepts a raw observation.
    """
    try:
        receipt = producer.read_verified_build_observation(operation_id)
        if type(receipt) is not BuildExecutionObservation:
            raise ValueError
        receipt = BuildExecutionObservation.model_validate(receipt.model_dump(mode="python"))
        if receipt.operation_id != operation_id:
            raise ValueError
    except (ValueError, AttributeError):
        raise BuildBoundaryError("trusted_build_observation_required") from None
    return _VerifiedBuildObservation(receipt, _EXECUTION_PROOF)


def _archive_access(uow, operation_id):
    require_transaction(uow.connection)
    row, record = read_build_intent(uow.connection, operation_id)
    actor = actor_for_command(uow, record.command_id)
    task, _ = lock_task_access(uow, actor, record.task_id, "fact.archive")
    authorize_current(uow, actor, AuthoritativeResource(
        record.project_id, "operation", operation_id, task_id=record.task_id,
    ), "operation.query")
    # The Task row serializes archive/accept/complete; immutable rows need no UPDATE grant.
    row, record = read_build_intent(uow.connection, operation_id)
    assert_schema_ready(uow.connection)
    current = uow.connection.scalar(select(task_inputs.c.input_set_key).where(
        task_inputs.c.task_id == task["task_id"],
        task_inputs.c.input_validity_revision == task["input_validity_revision"],
    ))
    applicable = (task["state"] == "active" and not task["ordinary_progress_closed"]
                  and task["cancel_requested_at"] is None and task["input_status"] == "valid"
                  and task["control_revision"] == record.control_revision
                  and task["input_validity_revision"] == record.input_validity_revision
                  and current == row["input_set_key"])
    return record, applicable


def _append(uow, record, *, event_id, event_type, schema, payload):
    append_event(uow.connection, command_id=record.command_id, project_id=record.project_id,
                 aggregate_kind="build", aggregate_id=record.build_run_id, aggregate_version=1,
                 event_id=event_id, event_type=event_type, schema_version=schema, payload=payload)


def register_verified_build_content(uow, operation_id: str, verified: _VerifiedBuildContent):
    """Reauthorize before replay; late content is archived without changing Task."""
    if type(verified) is not _VerifiedBuildContent or verified._proof is not _CONTENT_PROOF:
        raise BuildBoundaryError("verified_build_content_required")
    record, applicable = _archive_access(uow, operation_id)
    if verified.operation_id != operation_id or verified.build_input_digest != record.build_input_digest:
        raise BuildBoundaryError("build_content_input_mismatch")
    existing = read_build_content(uow.connection, record)
    if existing is not None:
        if existing.artifacts != verified.artifacts:
            raise BuildBoundaryError("build_content_identity_conflict")
        return existing
    registration = BuildContentRegistration(
        operation_id=operation_id, build_input_digest=record.build_input_digest,
        artifacts=verified.artifacts, observed_at=verified.observed_at, applicable=applicable,
    )
    _append(uow, record, event_id="build-content-" + record.command_id, event_type="build.content_verified",
            schema="p1-build-content-event-r1", payload=registration)
    return registration


def register_verified_build_observation(uow, operation_id: str, verified: _VerifiedBuildObservation):
    """Archive trusted process facts; a successful exit still needs matching content."""
    if type(verified) is not _VerifiedBuildObservation or verified._proof is not _EXECUTION_PROOF:
        raise BuildBoundaryError("verified_build_observation_required")
    record, applicable = _archive_access(uow, operation_id)
    receipt = verified.observation
    if (receipt.operation_id != operation_id or receipt.request_digest != record.request_digest
            or receipt.build_input_digest != record.build_input_digest):
        raise BuildBoundaryError("build_execution_input_mismatch")
    event_id = observation_event_id(receipt.observation_id)
    existing = uow.connection.execute(select(event_log).where(event_log.c.event_id == event_id)).mappings().one_or_none()
    if existing is not None:
        read_build_execution(uow.connection, record)
        entry = BuildObservationRegistration.model_validate(existing["payload"])
        if entry.observation != receipt:
            raise BuildBoundaryError("build_observation_identity_conflict")
        return entry
    head = read_build_execution(uow.connection, record)
    if ((head is None and receipt.previous_observation_id is not None)
            or (head is not None and ((head.observation.closure in SETTLED_BUILD_CLOSURES and (
                    receipt.closure != head.observation.closure or receipt.exit_code != head.observation.exit_code))
                or receipt.previous_observation_id != head.observation.observation_id
                or receipt.executor_instance_id != head.observation.executor_instance_id
                or receipt.executor_generation != head.observation.executor_generation
                or receipt.observed_at < head.observation.observed_at))):
        raise BuildBoundaryError("build_observation_predecessor_conflict")
    entry = BuildObservationRegistration(observation=receipt, applicable=applicable)
    _append(uow, record, event_id=event_id, event_type="build.execution_observed",
            schema="p1-build-observation-event-r1", payload=entry)
    return entry
