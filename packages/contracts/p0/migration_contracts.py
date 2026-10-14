"""P0 migration contracts only; no database, durable ledger, or execution adapter."""

from datetime import timedelta
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from packages.contracts.p0.decision_common import (
    Contract, Digest, Identifier, ProtocolRevision, Revision,
)

Flag = Annotated[bool, Field(strict=True)]
SchemaName = Annotated[str, Field(pattern=r"^[a-z_][a-z0-9_]{0,62}$")]
MigrationStatus = Literal["not_started", "running", "succeeded", "failed_known", "unknown"]
PostcheckId = Literal["schema_integrity", "data_integrity", "application_probe"]
REQUIRED_POSTCHECKS = frozenset(("schema_integrity", "data_integrity", "application_probe"))


class MigrationBinding(Contract):
    operation_id: Identifier
    step_id: Identifier
    request_digest: Digest


class MigrationRevision(Contract):
    revision: Identifier
    down_revision: Identifier | None
    script_digest: Digest
    change_kinds: Annotated[
        tuple[Literal["create_table", "create_index"], ...], Field(min_length=1, max_length=8)
    ]


class MigrationPlan(Contract):
    """Public fixed request body; its digest belongs in MigrationBinding, not itself."""

    protocol_revision: ProtocolRevision = "p0-decisions-r1"
    boundary: Literal["delivered_project"] = "delivered_project"
    step_kind: Literal["database_migrate"] = "database_migrate"
    step_id: Identifier
    plan_digest: Digest
    control_revision: Revision
    input_set_digest: Digest
    database_instance_id: Identifier
    schema_name: SchemaName
    postgres_version: Literal["16.13"] = "16.13"
    alembic_version: Literal["1.20.0"] = "1.20.0"
    migration_artifact_digest: Digest
    revisions: Annotated[tuple[MigrationRevision, ...], Field(min_length=1, max_length=64)]
    start_revision: Identifier | None
    target_revision: Identifier
    execution_lock_id: Identifier
    mode: Literal["transactional_ddl"] = "transactional_ddl"
    transaction_mode: Literal["single_transaction"] = "single_transaction"
    direction: Literal["upgrade"] = "upgrade"
    max_runtime_seconds: Literal[600] = 600
    lock_timeout_seconds: Literal[5] = 5
    statement_timeout_seconds: Literal[300] = 300
    backup_mode: Literal["restore_verified", "empty_target_verified"]
    backup_evidence_ref: Identifier
    compatibility_mode: Literal["fresh_install", "old_and_new_compatible"]
    compatibility_evidence_ref: Identifier
    execution_order: Literal["before_service_update"] = "before_service_update"
    postconditions_digest: Digest

    @model_validator(mode="after")
    def supported_chain(self) -> "MigrationPlan":
        names = tuple(item.revision for item in self.revisions)
        if len(set(names)) != len(names) or self.revisions[0].down_revision is not None:
            raise ValueError("MIGRATION_CHAIN_NOT_LINEAR")
        if any(current.down_revision != previous.revision for previous, current in
               zip(self.revisions, self.revisions[1:])):
            raise ValueError("MIGRATION_CHAIN_NOT_LINEAR")
        if self.target_revision != names[-1]:
            raise ValueError("MIGRATION_TARGET_NOT_HEAD")
        if self.start_revision is not None and self.start_revision not in names[:-1]:
            raise ValueError("MIGRATION_START_NOT_SUPPORTED")
        if self.execution_lock_id != f"migration:{self.database_instance_id}":
            raise ValueError("MIGRATION_LOCK_SCOPE_MISMATCH")
        fresh = self.start_revision is None
        if (self.compatibility_mode == "fresh_install") != fresh:
            raise ValueError("MIGRATION_COMPATIBILITY_MISMATCH")
        if not fresh and self.backup_mode != "restore_verified":
            raise ValueError("MIGRATION_RESTORE_EVIDENCE_REQUIRED")
        return self


class MigrationPostcheck(Contract):
    check_id: PostcheckId
    outcome: Literal["passed", "failed", "not_run"]
    evidence_ref: Identifier


class MigrationQueryResult(Contract):
    """Trusted observations; boolean declarations supplied by clients are not evidence."""

    protocol_revision: ProtocolRevision = "p0-decisions-r1"
    binding: MigrationBinding
    plan_digest: Digest
    database_instance_id: Identifier
    schema_name: SchemaName
    migration_artifact_digest: Digest
    status: MigrationStatus
    observation_id: Identifier
    attempt_id: Identifier | None = None
    observed_at: AwareDatetime
    executor_ledger_complete: Flag = False
    database_ledger_complete: Flag = False
    database_revision_observed: Flag = False
    executor_evidence_ref: Identifier | None = None
    database_evidence_ref: Identifier | None = None
    physical_evidence_ref: Identifier | None = None
    actual_heads: Annotated[tuple[Identifier, ...], Field(max_length=64)] = ()
    process_state: Literal["absent", "running", "stopped", "unknown"] = "unknown"
    lock_state: Literal["held_by_operation", "free", "unknown"] = "unknown"
    database_running: Flag = False
    never_started_evidence_ref: Identifier | None = None
    postconditions_digest: Digest | None = None
    postchecks: Annotated[tuple[MigrationPostcheck, ...], Field(max_length=3)] = ()
    known_effects_ref: Identifier | None = None
    failure_ref: Identifier | None = None

    @model_validator(mode="after")
    def utc_observation(self) -> "MigrationQueryResult":
        if self.observed_at.utcoffset() != timedelta(0):
            raise ValueError("MIGRATION_OBSERVATION_MUST_BE_UTC")
        return self


class MigrationRetryGate(Contract):
    """Current trusted facts checked under the start lock, not persisted permissions."""

    binding: MigrationBinding
    plan_digest: Digest
    control_revision: Revision
    observation_id: Identifier
    authorized: Flag = False
    approval_current: Flag = False
    inputs_current: Flag = False
    preconditions_verified: Flag = False
    resources_reserved: Flag = False
    fresh_permit_valid: Flag = False
    start_lock_held: Flag = False
    old_grants_closed: Flag = False
    no_conflicting_execution: Flag = False


def check_migration_query(
    plan: MigrationPlan, binding: MigrationBinding, result: MigrationQueryResult,
) -> MigrationStatus:
    """Validate a query conclusion without promoting unknown or performing a query."""

    if binding.step_id != plan.step_id or result.binding != binding or any(
        getattr(result, field) != getattr(plan, field) for field in (
            "plan_digest", "database_instance_id", "schema_name", "migration_artifact_digest",
        )
    ):
        raise ValueError("MIGRATION_QUERY_BINDING_MISMATCH")
    if result.status == "unknown":
        return "unknown"
    if not all((
        result.executor_ledger_complete, result.database_ledger_complete,
        result.database_revision_observed, result.executor_evidence_ref,
        result.database_evidence_ref, result.physical_evidence_ref,
    )):
        raise ValueError("MIGRATION_QUERY_EVIDENCE_INCOMPLETE")
    if result.status == "not_started":
        expected = () if plan.start_revision is None else (plan.start_revision,)
        if not result.never_started_evidence_ref or result.actual_heads != expected or (
            result.process_state not in ("absent", "stopped")
            or result.lock_state != "free" or result.database_running
        ):
            raise ValueError("MIGRATION_NOT_STARTED_UNPROVEN")
        return "not_started"
    if result.attempt_id is None:
        raise ValueError("MIGRATION_ATTEMPT_EVIDENCE_REQUIRED")
    if result.status == "running":
        if not (result.process_state == "running" and result.database_running
                and result.lock_state == "held_by_operation"):
            raise ValueError("MIGRATION_RUNNING_UNPROVEN")
        return "running"
    if result.process_state != "stopped" or result.database_running or result.lock_state == "unknown":
        raise ValueError("MIGRATION_STOP_UNPROVEN")
    if result.postconditions_digest != plan.postconditions_digest or (
        len(result.postchecks) != len(REQUIRED_POSTCHECKS)
        or {check.check_id for check in result.postchecks} != REQUIRED_POSTCHECKS
    ):
        raise ValueError("MIGRATION_POSTCHECKS_INCOMPLETE")
    if result.status == "succeeded":
        if result.actual_heads != (plan.target_revision,):
            raise ValueError("MIGRATION_HEAD_MISMATCH")
        if any(check.outcome != "passed" for check in result.postchecks) or result.failure_ref:
            raise ValueError("MIGRATION_SUCCESS_UNPROVEN")
    elif not result.failure_ref or not result.known_effects_ref:
        raise ValueError("MIGRATION_KNOWN_FAILURE_UNPROVEN")
    return result.status


def migration_succeeded(
    plan: MigrationPlan, binding: MigrationBinding, result: MigrationQueryResult,
) -> bool:
    return check_migration_query(plan, binding, result) == "succeeded"


def check_migration_retry(
    plan: MigrationPlan, binding: MigrationBinding, result: MigrationQueryResult,
    gate: MigrationRetryGate,
) -> None:
    """Check eligibility only; the caller must atomically fence and register an attempt."""

    if check_migration_query(plan, binding, result) != "not_started":
        raise ValueError("MIGRATION_RETRY_REQUIRES_NOT_STARTED")
    if gate.binding != binding or gate.plan_digest != plan.plan_digest or (
        gate.control_revision != plan.control_revision or gate.observation_id != result.observation_id
    ):
        raise ValueError("MIGRATION_RETRY_BINDING_STALE")
    if not all((
        gate.authorized, gate.approval_current, gate.inputs_current, gate.preconditions_verified,
        gate.resources_reserved, gate.fresh_permit_valid, gate.start_lock_held,
        gate.old_grants_closed, gate.no_conflicting_execution,
    )):
        raise ValueError("MIGRATION_RETRY_GATE_CLOSED")


class P0MigrationContracts(Contract):
    """Schema collection only; this wrapper does not execute a migration."""

    protocol_revision: ProtocolRevision = "p0-decisions-r1"
    plan: MigrationPlan
    binding: MigrationBinding
    query_result: MigrationQueryResult
    retry_gate: MigrationRetryGate
