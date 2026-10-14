"""Small synthetic checks for P0 permit decisions, with no clock or network probe."""

import json
import sys
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from packages.contracts.p0.permit_contracts import (
    P0PermitContracts, PermitBinding, PermitGate, PlanStep, STEP_LIMITS,
    StepPermit, TimeMapping, accept_grant, check_start, time_bounds,
)

DIGEST = "sha256:" + "a" * 64


def _changed(model: BaseModel, **changes):
    return type(model).model_validate(model.model_dump() | changes)


def _reject(action: Callable[[], object], reason: str) -> None:
    try:
        action()
    except ValueError as exc:
        if reason not in str(exc):
            raise AssertionError(f"unexpected rejection; expected {reason}") from exc
        return
    raise AssertionError(f"missing rejection: {reason}")


def _fixtures() -> tuple[StepPermit, TimeMapping, PermitGate]:
    binding = PermitBinding(
        operation_id="op-a", plan_digest=DIGEST, step_id="step-a", input_digest=DIGEST,
        executor_instance="executor-a", hub_incarnation="hub-a", generation=1,
        environment_execution_id="environment-execution-a",
        environment_config_revision_id="config-r1", expected_environment_revision_id="state-r1",
        control_revision=1, authorization_revision=1,
        predecessor_results_digest=DIGEST, actual_state_digest=DIGEST,
    )
    mapping = TimeMapping(
        time_epoch="time-a", mapping_id="sample-a", mapping_epoch="mapping-a",
        clock_continuity_id="clock-a", hub_incarnation="hub-a", executor_instance="executor-a",
        channel_binding_id="channel-a", sample_nonce="0" * 32, support_evidence_digest=DIGEST,
        sent_mono_us=0, received_mono_us=100_000, hub_sample_us=1_000_000,
        hub_sample_error_us=10, local_read_error_us=1, relative_rate_ppm=100,
    )
    grant = StepPermit(
        grant_id="grant-a", binding=binding, time_epoch="time-a", channel_binding_id="channel-a",
        mapping_epoch="mapping-a", clock_continuity_id="clock-a",
        issued_at=1_000_000, expires_at=31_000_000,
    )
    gate = PermitGate(
        binding=binding, time_epoch="time-a", mapping_epoch="mapping-a",
        clock_continuity_id="clock-a", channel_binding_id="channel-a",
        verified_time_evidence_digest=DIGEST, now_mono_us=200_000,
        authenticated=True, obtained_online=True, time_evidence_valid=True, authorized=True,
        prerequisites_met=True, resources_reserved=True, step_known_unstarted=True,
        other_grants_closed=True, maintenance_active=False,
    )
    return grant, mapping, gate


def _check_grant_windows() -> dict[str, bool]:
    grant, mapping, gate = _fixtures()
    accepted = accept_grant(grant, mapping, gate)
    start = _changed(gate, now_mono_us=300_000)
    check_start(accepted, mapping, start)
    result = {"valid_accept_and_start": True}

    boundary = _changed(grant, expires_at=time_bounds(mapping, gate.now_mono_us)[1])
    _reject(lambda: accept_grant(boundary, mapping, gate), "GRANT_TIME_WINDOW")
    boundary = _changed(grant, expires_at=time_bounds(mapping, start.now_mono_us)[1])
    boundary_accept = accept_grant(boundary, mapping, gate)
    _reject(lambda: check_start(boundary_accept, mapping, start), "GRANT_TIME_WINDOW")
    _reject(lambda: _changed(grant, expires_at=31_000_001), "GRANT_LIFETIME")
    _reject(lambda: _changed(grant, time_domain="utc"), "time_domain")
    future = _changed(grant, issued_at=1_500_000, expires_at=31_500_000)
    _reject(lambda: accept_grant(future, mapping, gate), "GRANT_TIME_WINDOW")
    result["expiry_equality_both_boundaries_and_domain"] = True

    late = _changed(gate, now_mono_us=gate.now_mono_us + 5_000_000)
    repeated = accept_grant(grant, mapping, late, previous=accepted)
    if repeated is not accepted:
        raise AssertionError("re-delivery replaced first acceptance")
    _reject(lambda: check_start(repeated, mapping, late), "FIRST_ACCEPTANCE_WINDOW")
    check_start(accepted, mapping, _changed(gate, now_mono_us=gate.now_mono_us + 4_999_000))
    changed_grant = _changed(grant, issued_at=2_000_000, expires_at=32_000_000)
    _reject(lambda: accept_grant(changed_grant, mapping, late, previous=accepted), "GRANT_REBIND")
    refreshed = _changed(
        mapping, mapping_id="sample-b", sample_nonce="1" * 32,
        sent_mono_us=5_000_000, received_mono_us=5_100_000, hub_sample_us=6_000_000,
    )
    _reject(lambda: check_start(accepted, refreshed, late), "FIRST_ACCEPTANCE_WINDOW")
    result["original_grant_and_first_anchor_never_renew"] = True
    return result


def _check_clock_and_gates() -> dict[str, bool]:
    grant, mapping, gate = _fixtures()
    accepted = accept_grant(grant, mapping, gate)
    start = _changed(gate, now_mono_us=300_000)

    _reject(lambda: check_start(accepted, mapping, _changed(start, time_epoch="time-b")), "TIME_BINDING_STALE")
    new_mapping = _changed(mapping, mapping_epoch="mapping-b")
    new_gate = _changed(start, mapping_epoch="mapping-b")
    _reject(lambda: check_start(accepted, new_mapping, new_gate), "TIME_BINDING_STALE")
    _reject(lambda: accept_grant(grant, new_mapping, new_gate), "TIME_BINDING_STALE")
    new_grant = _changed(grant, grant_id="grant-b", mapping_epoch="mapping-b")
    check_start(accept_grant(new_grant, new_mapping, new_gate), new_mapping, new_gate)
    new_mapping = _changed(mapping, clock_continuity_id="clock-b")
    new_gate = _changed(start, clock_continuity_id="clock-b")
    _reject(lambda: check_start(accepted, new_mapping, new_gate), "TIME_BINDING_STALE")
    rebooted = _changed(start.binding, executor_instance="executor-b")
    _reject(lambda: check_start(accepted, mapping, _changed(start, binding=rebooted)), "PERMIT_BINDING_STALE")
    _reject(lambda: check_start(accepted, mapping, _changed(start, time_evidence_valid=False)), "CURRENT_GATE_CLOSED")
    result = {"epoch_reboot_pause_and_lost_trust_close_old_grant": True}

    early = time_bounds(mapping, gate.now_mono_us)
    if early != (1_099_977, 1_200_036):
        raise AssertionError("full RTT and rounded drift differ from the fixed arithmetic vector")
    aged = time_bounds(mapping, gate.now_mono_us + 20_000_000)
    if aged[1] - aged[0] <= early[1] - early[0]:
        raise AssertionError("sample aging did not grow uncertainty")
    _reject(lambda: time_bounds(mapping, 60_100_000), "TIME_SAMPLE_TOO_OLD")
    _reject(lambda: time_bounds(mapping, 99_999), "TIME_CONTINUITY_LOST")
    _reject(lambda: _changed(mapping, received_mono_us=2_000_001), "TIME_SAMPLE_ROUND_TRIP")
    _reject(lambda: _changed(mapping, relative_rate_ppm=101), "relative_rate_ppm")
    result["round_trip_aging_and_error_evidence_limits"] = True

    for field in ("control_revision", "authorization_revision", "generation"):
        stale = _changed(start.binding, **{field: 2})
        _reject(lambda: check_start(accepted, mapping, _changed(start, binding=stale)), "PERMIT_BINDING_STALE")
    for field in ("obtained_online", "authorized", "other_grants_closed", "step_known_unstarted"):
        _reject(lambda: accept_grant(grant, mapping, _changed(gate, **{field: False})), "CURRENT_GATE_CLOSED")
        _reject(lambda: check_start(accepted, mapping, _changed(start, **{field: False})), "CURRENT_GATE_CLOSED")
    _reject(lambda: check_start(accepted, mapping, _changed(start, maintenance_active=True)), "CURRENT_GATE_CLOSED")
    result["current_control_authorization_reconciliation_and_online_gates"] = True
    return result


def _check_step_bounds() -> dict[str, bool]:

    for kind, (limit, stop_mode) in STEP_LIMITS.items():
        step = PlanStep(
            step_id="step-a", kind=kind, input_ref="input-a", input_digest=DIGEST,
            preconditions_digest=DIGEST, postconditions_digest=DIGEST,
            max_runtime_seconds=limit, stop_mode=stop_mode, result_query_ref="query-original-step",
        )
        _reject(lambda: _changed(step, max_runtime_seconds=limit + 1), "UNSUPPORTED_STEP_BOUNDARY")
        _reject(lambda: _changed(step, max_runtime_seconds=0), "max_runtime_seconds")
    _reject(lambda: _changed(step, kind="shell"), "kind")
    _reject(lambda: _changed(step, stop_mode="stop_read_only"), "UNSUPPORTED_STEP_BOUNDARY")
    P0PermitContracts.model_json_schema()
    return {"finite_step_types_duration_and_stop_boundaries": True}


def run_checks() -> dict[str, bool]:
    result = _check_grant_windows()
    result.update(_check_clock_and_gates())
    result.update(_check_step_bounds())
    return result


if __name__ == "__main__":
    print(json.dumps(run_checks(), ensure_ascii=False, indent=2))
