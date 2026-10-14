"""Synthetic P0 preview fact checks, without tickets, browsers, network or storage."""

import json
import sys
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from packages.contracts.p0.engineering_contracts import EngineeringRef
from packages.contracts.p0.preview_contracts import (
    EVIDENCE_GROUPS, P0PreviewContracts, PreviewBinding, PreviewClientRoute,
    PreviewEvidence, PreviewExchange, PreviewProxyClosure, PreviewProxyControl,
    PreviewProxyIdentity, PreviewRawPortAccess, PreviewRevocation, check_client_route,
    check_preview_request, check_proxy_access, check_proxy_shutdown, check_redemption,
    revocation_status,
)

NOW = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)


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


def _ref(kind: str, name: str) -> EngineeringRef:
    return EngineeringRef(kind=kind, object_id=name, revision="synthetic-r1",
                          digest="sha256:" + "a" * 64, digest_algorithm="sha256")


def _fixtures() -> P0PreviewContracts:
    binding = PreviewBinding(
        authorization_id="auth-a", authorization_revision=2, subject_id="human-a", project_id="project-a",
        environment_ref=_ref("environment", "instance-a"), policy_ref=_ref("policy", "policy-a"),
        purpose="human_test", candidate_ref=_ref("candidate", "candidate-a"),
        input_set_ref=_ref("input_set", "input-a"), artifact_ref=_ref("artifact", "artifact-a"),
        human_test_session_id="test-a", test_round=1,
    )
    runtime = _ref("descriptor", "synthetic-linux-chromium")
    route = PreviewClientRoute(
        route="browser_linux_chromium", runtime_ref=runtime, dns_tls_verified=True,
        isolation_evidence=tuple(PreviewEvidence(
            group=group, client_route="browser_linux_chromium", runtime_ref=runtime,
            evidence_ref=_ref("evidence", "synthetic-" + group),
        ) for group in sorted(EVIDENCE_GROUPS)),
    )
    exchange = PreviewExchange(
        binding=binding, ticket_id="ticket-public-id", ticket_state_after="consumed",
        issued_at=NOW, checked_at=NOW + timedelta(seconds=1), ticket_expires_at=NOW + timedelta(seconds=60),
        authorization_expires_at=NOW + timedelta(minutes=15), environment_expires_at=NOW + timedelta(minutes=30),
        committed=True, redemption_id="redemption-a", session_ids=("session-public-id",),
        session_expires_at=NOW + timedelta(minutes=15), response_state="delivered",
    )
    control = PreviewProxyControl(
        clock_continuous=True, current_authorization_verified=True, session_authenticated=True,
        last_verified_control_mono_ms=1000, observed_mono_ms=2000, control_age_upper_ms=1001,
        new_access_enabled=True, remaining_connections=2,
    )
    proxies = tuple(PreviewProxyIdentity(proxy_id=name, boot_id="boot-a") for name in ("proxy-a", "proxy-b"))
    closures = tuple(PreviewProxyClosure(
        proxy=proxy, binding=binding, revoke_revision=3, hub_clock_epoch="hub-clock-a",
        received_elapsed_upper_ms=4000, new_access_denied=True, all_routes_closed=True, sessions_disabled=True,
        remaining_client_connections=0, remaining_upstream_connections=0,
        denied_at=NOW + timedelta(seconds=2), connections_closed_at=NOW + timedelta(seconds=3),
    ) for proxy in proxies)
    return P0PreviewContracts(
        binding=binding, client_route=route, exchange=exchange, proxy_control=control,
        raw_port_access=PreviewRawPortAccess(
            service="backend", port=8000, caller="preview_proxy", source_instance_id="instance-a",
            target_instance_id="instance-a", approved_mapping_ref=_ref("descriptor", "mapping-a"), purpose="human_test",
        ),
        revocation=PreviewRevocation(
            binding=binding, revoke_revision=3, requested_at=NOW, deadline_at=NOW + timedelta(seconds=10),
            hub_clock_epoch="hub-clock-a", observed_hub_clock_epoch="hub-clock-a", elapsed_upper_ms=5000,
            timing_evidence_current=True, required_proxies=proxies, closures=closures,
        ),
    )


def _delivery_checks(sample: P0PreviewContracts) -> dict[str, bool]:
    route = sample.client_route
    check_client_route(route)
    for location in ("url_path", "url_query", "url_fragment"):
        _reject(lambda: _changed(route, ticket_location=location), "ticket_location")
    for suffix in ("/synthetic-value", "?ticket=synthetic-value", "#synthetic-value"):
        _reject(lambda: _changed(route, redemption_path=route.redemption_path + suffix), "redemption_path")
    _reject(lambda: _changed(route, redemption_method="GET"), "redemption_method")
    _reject(lambda: _changed(route, route="unknown-browser"), "route")
    for name in ("browser_windows_edge", "external_windows_edge", "external_linux_chromium",
                 "tauri_windows_webview2", "tauri_linux_webkitgtk", "browser_linux_chromium"):
        _reject(lambda: check_client_route(_changed(route, route=name, isolation_evidence=())), "UNVERIFIED_CLIENT_ROUTE")
    _reject(lambda: check_client_route(_changed(route, dns_tls_verified=False)), "UNVERIFIED_CLIENT_ROUTE")
    _reject(lambda: check_client_route(_changed(route, route="tauri_windows_webview2")), "CLIENT_EVIDENCE_BINDING")
    _reject(lambda: check_client_route(_changed(route, runtime_ref=_ref("descriptor", "runtime-b"))), "CLIENT_EVIDENCE_BINDING")
    return {"ticket_url_locations_and_get_rejected": True, "unknown_unverified_and_mismatched_clients_rejected": True}


def _exchange_checks(sample: P0PreviewContracts) -> dict[str, bool]:
    exchange, route, binding = sample.exchange, sample.client_route, sample.binding
    check_redemption(exchange, route, binding, True)
    check_redemption(_changed(exchange, response_state="lost"), route, binding, True)
    _reject(lambda: _changed(exchange, ticket_state_before="consumed"), "ticket_state_before")
    _reject(lambda: _changed(exchange, committed=False), "UNCOMMITTED_EXCHANGE_HAS_NO_SESSION")
    _reject(lambda: _changed(exchange, session_ids=("session-a", "session-b")), "session_ids")
    _reject(lambda: _changed(exchange, credential_reissued=True), "credential_reissued")
    _reject(lambda: _changed(exchange, checked_at=exchange.ticket_expires_at), "TICKET_TIME_WINDOW")
    _reject(lambda: _changed(exchange, session_expires_at=exchange.environment_expires_at), "SESSION_SCOPE_EXPIRY")
    _reject(lambda: check_redemption(exchange, route, binding, False), "CURRENT_PREVIEW_BINDING_DENIED")
    for change in ({"subject_id": "human-b"}, {"authorization_revision": 3}, {"test_round": 2},
                   {"candidate_ref": _ref("candidate", "candidate-b")}, {"environment_ref": _ref("environment", "instance-b")}):
        changed = _changed(binding, **change)
        _reject(lambda: check_redemption(exchange, route, changed, True), "CURRENT_PREVIEW_BINDING_DENIED")
    _reject(lambda: _changed(binding, input_set_ref=None), "FIXED_CANDIDATE_BINDING")
    _reject(lambda: _changed(binding, test_round=None), "HUMAN_TEST_BINDING")
    check_preview_request(exchange, route, sample.proxy_control, binding, NOW + timedelta(minutes=2))
    _reject(lambda: check_preview_request(exchange, route, sample.proxy_control, binding, exchange.session_expires_at),
            "PREVIEW_SESSION_BINDING_OR_EXPIRY")
    _reject(lambda: check_proxy_access(_changed(sample.proxy_control, session_authenticated=False)), "PROXY_ACCESS_FAIL_CLOSED")
    return {"single_exchange_lost_response_and_bound_session": True, "current_binding_and_expiry_gates": True}


def _network_and_control_checks(sample: P0PreviewContracts) -> dict[str, bool]:
    raw, control = sample.raw_port_access, sample.proxy_control
    for change, reason in (({"port": 8001}, "RAW_PORT_ACCESS_DENIED"), ({"address_family": "ipv6"}, "address_family"),
                           ({"source_instance_id": "other-sandbox"}, "RAW_PORT_ACCESS_DENIED"),
                           ({"service": "hmr", "port": 5173}, "RAW_PORT_ACCESS_DENIED")):
        _reject(lambda: _changed(raw, **change), reason)
    check_proxy_access(control)
    _reject(lambda: check_proxy_access(_changed(control, new_access_enabled=False)), "PROXY_ACCESS_FAIL_CLOSED")
    boundary = _changed(control, observed_mono_ms=4000, control_age_upper_ms=3000)
    _reject(lambda: check_proxy_access(boundary), "PROXY_ACCESS_FAIL_CLOSED")
    _reject(lambda: check_proxy_shutdown(boundary), "FAILED_CONTROL_MUST_DENY_NEW_ACCESS")
    overdue = _changed(control, observed_mono_ms=6000, control_age_upper_ms=5000, new_access_enabled=False)
    _reject(lambda: check_proxy_shutdown(overdue), "CONTROL_GAP_CONNECTIONS_NOT_CLOSED")
    check_proxy_shutdown(_changed(overdue, remaining_connections=0))
    explicit = _changed(control, observed_mono_ms=3200, control_age_upper_ms=2200,
                        failure_detected_mono_ms=1200, failure_age_upper_ms=2000, new_access_enabled=False)
    _reject(lambda: check_proxy_shutdown(explicit), "CONTROL_GAP_CONNECTIONS_NOT_CLOSED")
    restarted = _changed(control, clock_continuous=False, new_access_enabled=False)
    _reject(lambda: check_proxy_access(restarted), "PROXY_ACCESS_FAIL_CLOSED")
    _reject(lambda: check_proxy_shutdown(restarted), "UNKNOWN_CLOCK_REQUIRES_CLOSED_PROXY")
    check_proxy_shutdown(_changed(restarted, remaining_connections=0))
    return {"raw_port_family_and_instance_allowlist": True, "control_gap_cleanup_and_restart_fail_closed": True}


def _revocation_checks(sample: P0PreviewContracts) -> dict[str, bool]:
    record = sample.revocation
    if revocation_status(record) != "effective":
        raise AssertionError("complete closure rejected")
    missing = _changed(record, closures=record.closures[:1])
    if revocation_status(missing) != "pending" or revocation_status(_changed(missing, elapsed_upper_ms=10_000)) != "timed_out":
        raise AssertionError("missing proxy confirmation treated as effective")
    for change in ({"remaining_client_connections": 1}, {"remaining_upstream_connections": 1},
                   {"all_routes_closed": False}, {"connections_closed_at": None}):
        partial = _changed(record.closures[0], **change)
        if revocation_status(_changed(record, closures=(partial, record.closures[1]))) != "pending":
            raise AssertionError("incomplete closure treated as effective")
    extra = PreviewProxyIdentity(proxy_id="proxy-a", boot_id="boot-b")
    if revocation_status(_changed(record, additional_possible_proxies=(extra,))) != "pending":
        raise AssertionError("new proxy boot omitted")
    _reject(lambda: _changed(record, closures=(record.closures[0], record.closures[0])), "DUPLICATE_OR_UNREGISTERED_PROXY_CONFIRMATION")
    _reject(lambda: _changed(record, deadline_at=NOW + timedelta(seconds=11)), "REVOCATION_DEADLINE_NOT_RESETTABLE")
    stale = _changed(record.closures[0], revoke_revision=2)
    _reject(lambda: _changed(record, closures=(stale, record.closures[1])), "REVOCATION_CONFIRMATION_BINDING")
    for elapsed, expected in ((10_000, "effective"), (10_001, "effective_late")):
        last = _changed(record.closures[1], received_elapsed_upper_ms=elapsed)
        if revocation_status(_changed(record, elapsed_upper_ms=elapsed, closures=(record.closures[0], last))) != expected:
            raise AssertionError("revocation boundary misclassified")
    if revocation_status(_changed(record, observed_hub_clock_epoch="restarted-hub")) != "pending_time_unknown":
        raise AssertionError("restart renewed revocation timer")
    return {"missing_live_connections_and_proxy_boots_remain_pending": True, "fixed_deadline_late_and_unknown_timing": True}


def run_checks() -> dict[str, bool]:
    sample = _fixtures()
    result = {}
    for method in (_delivery_checks, _exchange_checks, _network_and_control_checks, _revocation_checks):
        result.update(method(sample))
    if "PreviewRevocation" not in P0PreviewContracts.model_json_schema().get("$defs", {}):
        raise AssertionError("preview wrapper schema missing")
    result["bounded_public_schema"] = True
    return result


if __name__ == "__main__":
    print(json.dumps({"method": "p0-preview-decisions-r1", "synthetic_only": True, "checks": run_checks()}, ensure_ascii=False))
