"""P0 permit decisions and arithmetic only; callers supply verified clock evidence."""

from types import MappingProxyType
from typing import Annotated, Literal

from pydantic import Field, model_validator

from packages.contracts.p0.decision_common import (
    Contract, Digest, Identifier, ProtocolRevision, Revision,
)

Micros = Annotated[int, Field(strict=True, ge=0, le=9007199254740991)]
Flag = Annotated[bool, Field(strict=True)]
TimeDomain = Literal["hub-monotonic-us-v1"]
StepKind = Literal[
    "artifact_prepare", "runtime_input_check", "database_migrate",
    "service_update", "health_verify", "approved_compensation",
]
StopMode = Literal[
    "cancel_transfer_then_reconcile", "stop_read_only",
    "database_transaction_boundary", "reconcile_service_transition",
]
GRANT_LIFETIME_US = 30_000_000
START_WINDOW_US = 5_000_000
MAX_UNCERTAINTY_US = 2_000_000
MAX_SAMPLE_AGE_US = 60_000_000
MAX_ROUND_TRIP_US = 2_000_000
STEP_LIMITS = MappingProxyType({
    "artifact_prepare": (600, "cancel_transfer_then_reconcile"),
    "runtime_input_check": (60, "stop_read_only"),
    "database_migrate": (600, "database_transaction_boundary"),
    "service_update": (300, "reconcile_service_transition"),
    "health_verify": (300, "stop_read_only"),
    "approved_compensation": (300, "reconcile_service_transition"),
})


class PlanStep(Contract):
    protocol_revision: ProtocolRevision = "p0-decisions-r1"
    step_id: Identifier
    kind: StepKind
    type_revision: Literal["1"] = "1"
    input_ref: Identifier
    input_digest: Digest
    preconditions_digest: Digest
    postconditions_digest: Digest
    max_runtime_seconds: Annotated[int, Field(strict=True, gt=0)]
    stop_mode: StopMode
    result_query_ref: Identifier
    on_failure: Literal["stop_and_reconcile", "approved_compensation"] = "stop_and_reconcile"
    compensation_step_id: Identifier | None = None

    @model_validator(mode="after")
    def supported_step(self) -> "PlanStep":
        limit, stop_mode = STEP_LIMITS[self.kind]
        if self.max_runtime_seconds > limit or self.stop_mode != stop_mode:
            raise ValueError("UNSUPPORTED_STEP_BOUNDARY")
        if (self.on_failure == "approved_compensation") != (self.compensation_step_id is not None):
            raise ValueError("COMPENSATION_REFERENCE_REQUIRED")
        if self.compensation_step_id == self.step_id or (
            self.kind == "approved_compensation" and self.compensation_step_id is not None
        ):
            raise ValueError("COMPENSATION_MUST_STOP")
        return self


class PermitBinding(Contract):
    operation_id: Identifier
    plan_digest: Digest
    step_id: Identifier
    input_digest: Digest
    executor_instance: Identifier
    hub_incarnation: Identifier
    generation: Revision
    environment_execution_id: Identifier
    environment_config_revision_id: Identifier
    expected_environment_revision_id: Identifier
    control_revision: Revision
    authorization_revision: Revision
    predecessor_results_digest: Digest
    actual_state_digest: Digest


class TimeMapping(Contract):
    protocol_revision: ProtocolRevision = "p0-decisions-r1"
    time_domain: TimeDomain = "hub-monotonic-us-v1"
    time_epoch: Identifier
    mapping_id: Identifier
    mapping_epoch: Identifier
    clock_continuity_id: Identifier
    hub_incarnation: Identifier
    executor_instance: Identifier
    channel_binding_id: Identifier
    sample_nonce: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
    support_evidence_digest: Digest
    sent_mono_us: Micros
    received_mono_us: Micros
    hub_sample_us: Micros
    hub_sample_error_us: Annotated[int, Field(strict=True, ge=1, le=10_000)]
    local_read_error_us: Annotated[int, Field(strict=True, ge=1, le=1_000)]
    relative_rate_ppm: Annotated[int, Field(strict=True, ge=0, le=100)]

    @model_validator(mode="after")
    def bounded_sample(self) -> "TimeMapping":
        if not 0 <= self.received_mono_us - self.sent_mono_us <= MAX_ROUND_TRIP_US:
            raise ValueError("TIME_SAMPLE_ROUND_TRIP")
        return self


class StepPermit(Contract):
    protocol_revision: ProtocolRevision = "p0-decisions-r1"
    grant_id: Identifier
    binding: PermitBinding
    time_domain: TimeDomain = "hub-monotonic-us-v1"
    time_epoch: Identifier
    mapping_epoch: Identifier
    clock_continuity_id: Identifier
    channel_binding_id: Identifier
    issued_at: Micros
    expires_at: Micros

    @model_validator(mode="after")
    def bounded_lifetime(self) -> "StepPermit":
        if not 0 < self.expires_at - self.issued_at <= GRANT_LIFETIME_US:
            raise ValueError("GRANT_LIFETIME")
        return self


class PermitGate(Contract):
    """Trusted current facts, never a client-controlled authorization request."""

    binding: PermitBinding
    time_epoch: Identifier
    mapping_epoch: Identifier
    clock_continuity_id: Identifier
    channel_binding_id: Identifier
    verified_time_evidence_digest: Digest
    now_mono_us: Micros
    authenticated: Flag = False
    obtained_online: Flag = False
    time_evidence_valid: Flag = False
    authorized: Flag = False
    prerequisites_met: Flag = False
    resources_reserved: Flag = False
    step_known_unstarted: Flag = False
    other_grants_closed: Flag = False
    maintenance_active: Flag = True


class GrantAcceptance(Contract):
    """Persist once under the start lock; re-delivery retrieves this exact record."""

    grant: StepPermit
    first_mapping: TimeMapping
    first_accepted_mono_us: Micros


def _upper_elapsed(delta: int, read_error: int, ppm: int) -> int:
    return ((delta + read_error) * (1_000_000 + ppm) + 999_999) // 1_000_000


def time_bounds(mapping: TimeMapping, now_mono_us: int) -> tuple[int, int]:
    """Return conservative [L, U] in Hub microseconds, using the entire RTT."""

    if type(now_mono_us) is not int or now_mono_us < mapping.received_mono_us:
        raise ValueError("TIME_CONTINUITY_LOST")
    age = now_mono_us - mapping.received_mono_us
    error = 2 * mapping.local_read_error_us
    age_upper = _upper_elapsed(age, error, mapping.relative_rate_ppm)
    if age_upper > MAX_SAMPLE_AGE_US:
        raise ValueError("TIME_SAMPLE_TOO_OLD")
    drift = age_upper - age - error
    round_trip = _upper_elapsed(
        mapping.received_mono_us - mapping.sent_mono_us, error, mapping.relative_rate_ppm,
    )
    lower = mapping.hub_sample_us - mapping.hub_sample_error_us + age - error - drift
    upper = mapping.hub_sample_us + mapping.hub_sample_error_us + round_trip + age + error + drift
    return lower, upper


def _require_eligible(grant: StepPermit, mapping: TimeMapping, gate: PermitGate) -> None:
    if not all((
        gate.authenticated, gate.obtained_online, gate.time_evidence_valid,
        gate.authorized, gate.prerequisites_met, gate.resources_reserved,
        gate.step_known_unstarted, gate.other_grants_closed,
    )) or gate.maintenance_active:
        raise ValueError("CURRENT_GATE_CLOSED")
    if grant.binding != gate.binding:
        raise ValueError("PERMIT_BINDING_STALE")
    if (
        grant.time_domain != mapping.time_domain
        or grant.time_epoch != mapping.time_epoch or grant.time_epoch != gate.time_epoch
        or grant.mapping_epoch != mapping.mapping_epoch
        or grant.clock_continuity_id != mapping.clock_continuity_id
        or mapping.hub_incarnation != grant.binding.hub_incarnation
        or mapping.executor_instance != grant.binding.executor_instance
        or mapping.mapping_epoch != gate.mapping_epoch
        or mapping.clock_continuity_id != gate.clock_continuity_id
        or mapping.channel_binding_id != grant.channel_binding_id
        or mapping.channel_binding_id != gate.channel_binding_id
        or mapping.support_evidence_digest != gate.verified_time_evidence_digest
    ):
        raise ValueError("TIME_BINDING_STALE")
    lower, upper = time_bounds(mapping, gate.now_mono_us)
    if upper - lower > 2 * MAX_UNCERTAINTY_US:
        raise ValueError("TIME_UNCERTAINTY")
    if lower < grant.issued_at or upper >= grant.expires_at:
        raise ValueError("GRANT_TIME_WINDOW")


def accept_grant(
    grant: StepPermit, mapping: TimeMapping, gate: PermitGate,
    *, previous: GrantAcceptance | None = None,
) -> GrantAcceptance:
    """First acceptance, or an unchanged query result; never a second start right."""

    if previous is not None:
        if previous.grant != grant:
            raise ValueError("GRANT_REBIND")
        return previous
    _require_eligible(grant, mapping, gate)
    return GrantAcceptance(
        grant=grant, first_mapping=mapping, first_accepted_mono_us=gate.now_mono_us,
    )


def check_start(acceptance: GrantAcceptance, mapping: TimeMapping, gate: PermitGate) -> None:
    """Check the persisted original grant at the actual side-effect boundary."""

    _require_eligible(acceptance.grant, mapping, gate)
    original = acceptance.first_mapping
    if any(getattr(original, field) != getattr(mapping, field) for field in (
        "time_epoch", "mapping_epoch", "clock_continuity_id", "executor_instance",
        "hub_incarnation", "channel_binding_id", "support_evidence_digest",
    )):
        raise ValueError("ACCEPTANCE_CONTINUITY_LOST")
    elapsed = gate.now_mono_us - acceptance.first_accepted_mono_us
    if elapsed < 0 or _upper_elapsed(
        elapsed, original.local_read_error_us + mapping.local_read_error_us,
        max(original.relative_rate_ppm, mapping.relative_rate_ppm),
    ) > START_WINDOW_US:
        raise ValueError("FIRST_ACCEPTANCE_WINDOW")


class P0PermitContracts(Contract):
    """Schema collection only; this wrapper is not a runtime operation."""

    protocol_revision: ProtocolRevision = "p0-decisions-r1"
    plan_step: PlanStep
    time_mapping: TimeMapping
    step_permit: StepPermit
    gate: PermitGate
    acceptance: GrantAcceptance
