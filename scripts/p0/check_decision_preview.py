"""Preview route secrecy and revocation require live closure facts."""

from datetime import datetime, timedelta, timezone

from pydantic import ValidationError

from packages.contracts.p0.engineering_contracts import EngineeringRef
from packages.contracts.p0.preview_contracts import (
    PreviewBinding, PreviewClientRoute, PreviewProxyClosure, PreviewProxyIdentity, PreviewRawPortAccess,
    PreviewRevocation, revocation_status,
)

DIGEST = "sha256:" + "a" * 64
NOW = datetime(2026, 10, 14, tzinfo=timezone.utc)


def _ref(kind: str) -> EngineeringRef:
    return EngineeringRef(kind=kind, object_id=kind, revision="r1", digest=DIGEST, digest_algorithm="sha256")


def _changed(model, **updates):
    return type(model).model_validate(model.model_dump() | updates)


def _reject(action, reason: str) -> None:
    try:
        action()
    except (ValueError, ValidationError) as error:
        if reason in str(error):
            return
        raise AssertionError(f"unexpected rejection: {reason}") from error
    raise AssertionError(f"missing rejection: {reason}")


def _revocation():
    binding = PreviewBinding(
        authorization_id="auth", authorization_revision=2, subject_id="human", project_id="project",
        environment_ref=_ref("environment"), policy_ref=_ref("policy"), purpose="human_test",
        candidate_ref=_ref("candidate"), input_set_ref=_ref("input_set"), artifact_ref=_ref("artifact"),
        human_test_session_id="session", test_round=1,
    )
    proxy = PreviewProxyIdentity(proxy_id="proxy", boot_id="boot")
    closure = PreviewProxyClosure(
        proxy=proxy, binding=binding, revoke_revision=3, hub_clock_epoch="clock", received_elapsed_upper_ms=4000,
        new_access_denied=True, all_routes_closed=True, sessions_disabled=True,
        remaining_client_connections=0, remaining_upstream_connections=0,
        denied_at=NOW + timedelta(seconds=2), connections_closed_at=NOW + timedelta(seconds=3),
    )
    return PreviewRevocation(
        binding=binding, revoke_revision=3, requested_at=NOW,
        deadline_at=NOW + timedelta(seconds=10), hub_clock_epoch="clock", observed_hub_clock_epoch="clock",
        elapsed_upper_ms=5000, timing_evidence_current=True, required_proxies=(proxy,), closures=(closure,),
    )


def run_checks() -> dict[str, bool]:
    record = _revocation()
    assert revocation_status(record) == "effective"
    assert revocation_status(_changed(record, closures=())) == "pending"
    assert revocation_status(_changed(record, observed_hub_clock_epoch="restarted")) == "pending_time_unknown"
    possible = PreviewProxyIdentity(proxy_id="proxy", boot_id="new-boot")
    assert revocation_status(_changed(record, additional_possible_proxies=(possible,))) == "pending"

    _reject(lambda: PreviewClientRoute(route="browser_linux_chromium", runtime_ref=_ref("descriptor"),
                                      ticket_location="url_query"), "literal_error")
    allowed = PreviewRawPortAccess(
        service="backend", port=8000, caller="preview_proxy", source_instance_id="instance",
        target_instance_id="instance", approved_mapping_ref=_ref("descriptor"), purpose="human_test",
    )
    _reject(lambda: _changed(allowed, port=8001), "RAW_PORT_ACCESS_DENIED")
    return {"all_possible_proxies_must_close_before_revocation": True, "ticket_and_raw_port_boundaries": True}
