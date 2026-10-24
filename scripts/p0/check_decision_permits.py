"""Permit time bounds, first acceptance and current gate checks."""

from pydantic import BaseModel, ValidationError

from packages.contracts.p0.permit_contracts import (
    PermitBinding, PermitGate, StepPermit, TimeMapping, accept_grant, check_start, time_bounds,
)

DIGEST = "sha256:" + "a" * 64


def _changed(model: BaseModel, **updates):
    return type(model).model_validate(model.model_dump() | updates)


def _reject(action, reason: str) -> None:
    try:
        action()
    except (ValueError, ValidationError) as error:
        if reason in str(error):
            return
        raise AssertionError(f"unexpected rejection: {reason}") from error
    raise AssertionError(f"missing rejection: {reason}")


def run_checks() -> dict[str, bool]:
    binding = PermitBinding(
        operation_id="op", plan_digest=DIGEST, step_id="step", input_digest=DIGEST,
        executor_instance="executor", hub_incarnation="hub", generation=1,
        environment_execution_id="execution", environment_config_revision_id="config",
        expected_environment_revision_id="state", control_revision=1, authorization_revision=1,
        predecessor_results_digest=DIGEST, actual_state_digest=DIGEST,
    )
    mapping = TimeMapping(
        time_epoch="epoch", mapping_id="sample", mapping_epoch="mapping", clock_continuity_id="clock",
        hub_incarnation="hub", executor_instance="executor", channel_binding_id="channel",
        sample_nonce="0" * 32, support_evidence_digest=DIGEST, sent_mono_us=0, received_mono_us=100000,
        hub_sample_us=1000000, hub_sample_error_us=10, local_read_error_us=1, relative_rate_ppm=100,
    )
    grant = StepPermit(grant_id="grant", binding=binding, time_epoch="epoch",
                       channel_binding_id="channel", mapping_epoch="mapping", clock_continuity_id="clock",
                       issued_at=1000000, expires_at=31000000)
    gate = PermitGate(
        binding=binding, time_epoch="epoch", mapping_epoch="mapping", clock_continuity_id="clock",
        channel_binding_id="channel", verified_time_evidence_digest=DIGEST, now_mono_us=200000,
        authenticated=True, obtained_online=True, time_evidence_valid=True, authorized=True,
        prerequisites_met=True, resources_reserved=True, step_known_unstarted=True,
        other_grants_closed=True, maintenance_active=False,
    )
    assert time_bounds(mapping, gate.now_mono_us) == (1099977, 1200036)
    accepted = accept_grant(grant, mapping, gate)
    check_start(accepted, mapping, _changed(gate, now_mono_us=300000))
    _reject(lambda: check_start(accepted, mapping, _changed(gate, time_epoch="stale")), "TIME_BINDING_STALE")
    late = _changed(gate, now_mono_us=gate.now_mono_us + 5000000)
    _reject(lambda: check_start(accepted, mapping, late), "FIRST_ACCEPTANCE_WINDOW")
    return {"conservative_clock_bounds_and_first_acceptance_window": True, "stale_time_epoch_closes_start": True}
