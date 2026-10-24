"""Trusted target collection; no HTTP route can register capabilities or observations."""

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from database.readiness import assert_schema_ready, require_maintenance_role
from database.uow import require_transaction
from modules.collaboration.errors import TaskBoundaryError
from modules.delivery.deployment_tables import delivery_targets, target_observations
from modules.delivery.release_recipe import delivery_digest
from packages.contracts.p1.delivery_records import TargetObservation, TargetRegistration

_TARGET_PROOF = object()


class TargetFactProducer(Protocol):
    """Composition-root adapter must authenticate the target and query its actual ledger.

    P1.4-02 supplies the remote channel. Request bodies and caller-provided flags
    cannot implement this boundary. Unknown local ownership is reconciled=False.
    """

    def read_registration(self) -> TargetRegistration: ...
    def read_observation(self, binding) -> TargetObservation: ...


@dataclass(frozen=True, slots=True)
class _VerifiedTargetFact:
    value: TargetRegistration | TargetObservation
    _proof: object = field(repr=False, compare=False)


def collect_target_registration(producer: TargetFactProducer):
    value = producer.read_registration()
    if type(value) is not TargetRegistration:
        raise TaskBoundaryError("trusted_target_registration_required")
    return _VerifiedTargetFact(TargetRegistration.model_validate(value.model_dump(mode="python")), _TARGET_PROOF)


def collect_target_observation(producer: TargetFactProducer, binding):
    value = producer.read_observation(binding)
    if type(value) is not TargetObservation or value.binding_id != binding.binding_id:
        raise TaskBoundaryError("trusted_target_observation_required")
    return _VerifiedTargetFact(TargetObservation.model_validate(value.model_dump(mode="python")), _TARGET_PROOF)


def _verified(proof, schema):
    if type(proof) is not _VerifiedTargetFact or proof._proof is not _TARGET_PROOF or type(proof.value) is not schema:
        raise TaskBoundaryError("trusted_target_fact_required")
    return schema.model_validate(proof.value.model_dump(mode="python"))


def register_target(uow, project_id, proof):
    require_transaction(uow.connection)
    require_maintenance_role(uow.connection)
    value = _verified(proof, TargetRegistration)
    digest = delivery_digest(value)
    uow.connection.execute(insert(delivery_targets).values(
        project_id=project_id, target_id=value.target_id, installation_id=value.installation_id,
        registration_json=value.model_dump(mode="json"), digest=digest,
    ).on_conflict_do_nothing())
    current = read_target(uow.connection, project_id, value.target_id, value.installation_id)
    if current != value:
        raise TaskBoundaryError("target_registration_conflict")
    return digest


def read_target(connection, project_id, target_id, installation_id):
    row = connection.execute(select(delivery_targets).where(
        delivery_targets.c.project_id == project_id, delivery_targets.c.target_id == target_id,
        delivery_targets.c.installation_id == installation_id,
    )).mappings().one_or_none()
    if row is None:
        raise TaskBoundaryError("delivery_target_unavailable")
    value = TargetRegistration.model_validate(row["registration_json"])
    if (value.target_id != target_id or value.installation_id != installation_id
            or delivery_digest(value) != row["digest"]):
        raise TaskBoundaryError("delivery_target_invalid")
    return value


def register_observation(uow, project_id, proof):
    from modules.delivery.deployment_store import lock_binding

    require_transaction(uow.connection)
    value = _verified(proof, TargetObservation)
    _, binding = lock_binding(uow.connection, project_id, value.binding_id)
    target = read_target(uow.connection, project_id, binding.target_id, binding.installation_id)
    _match_target(value, target)
    digest = delivery_digest(value)
    uow.connection.execute(insert(target_observations).values(observation_id=value.observation_id,
        binding_id=value.binding_id, digest=digest, value_json=value.model_dump(mode="json"),
        observed_at=value.observed_at).on_conflict_do_nothing())
    existing = uow.connection.scalar(select(target_observations.c.digest).where(
        target_observations.c.observation_id == value.observation_id))
    if existing != digest:
        raise TaskBoundaryError("target_observation_identity_conflict")
    return digest


def _match_target(value, target):
    if any(getattr(value, key) != getattr(target, key) for key in (
        "target_id", "installation_id", "executor_instance", "generation",
    )):
        raise TaskBoundaryError("target_observation_binding_mismatch")


def latest_observation(connection, binding):
    row = connection.execute(select(target_observations).where(
        target_observations.c.binding_id == binding.binding_id,
    ).order_by(target_observations.c.observed_at.desc(), target_observations.c.observation_id.desc()).limit(1)).mappings().first()
    if row is None:
        return None
    value = TargetObservation.model_validate(row["value_json"])
    if delivery_digest(value) != row["digest"] or value.binding_id != binding.binding_id:
        raise TaskBoundaryError("target_observation_invalid")
    return value


def fresh_target(connection, binding):
    target = read_target(connection, binding.project_id, binding.target_id, binding.installation_id)
    value = latest_observation(connection, binding)
    if value is None:
        raise TaskBoundaryError("target_observation_missing")
    _match_target(value, target)
    now = connection.scalar(select(func.clock_timestamp()))
    if not value.reconciled:
        raise TaskBoundaryError("target_state_unknown")
    if not value.observed_at <= now < value.observed_at + timedelta(seconds=60):
        raise TaskBoundaryError("target_observation_stale")
    assert_schema_ready(connection)
    return target, value, now
