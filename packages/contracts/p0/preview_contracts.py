"""Bounded public P0 preview facts; no credentials, network or atomic store."""

from datetime import timedelta
from typing import Annotated, Literal

from pydantic import Field, model_validator

from packages.contracts.p0.decision_common import Contract, Identifier, ProtocolRevision, Revision
from packages.contracts.p0.engineering_contracts import EngineeringRef, UtcTimestamp, expect_kind

Millis = Annotated[int, Field(strict=True, ge=0, le=9007199254740991)]
Count = Annotated[int, Field(strict=True, ge=0, le=1_000_000)]
Flag = Annotated[bool, Field(strict=True)]
REVOKE_TIMEOUT_MS = 10_000
CONTROL_MAX_GAP_MS = 3_000
CONNECTION_CLEANUP_MS = 2_000
EvidenceGroup = Literal["management", "cross_origin", "native", "revocation", "version", "secrets"]
EVIDENCE_GROUPS = frozenset({"management", "cross_origin", "native", "revocation", "version", "secrets"})
ClientRouteName = Literal[
    "browser_windows_edge", "browser_linux_chromium", "external_windows_edge",
    "external_linux_chromium", "tauri_windows_webview2", "tauri_linux_webkitgtk",
]


class PreviewBinding(Contract):
    authorization_id: Identifier
    authorization_revision: Revision
    subject_id: Identifier
    project_id: Identifier
    environment_ref: EngineeringRef
    policy_ref: EngineeringRef
    purpose: Literal["development", "candidate", "human_test"]
    permission: Literal["preview.access"] = "preview.access"
    scope: Literal["one_environment_instance"] = "one_environment_instance"
    workspace_id: Identifier | None = None
    candidate_ref: EngineeringRef | None = None
    input_set_ref: EngineeringRef | None = None
    artifact_ref: EngineeringRef | None = None
    human_test_session_id: Identifier | None = None
    test_round: Revision | None = None

    @model_validator(mode="after")
    def check_scope(self):
        expect_kind(self.environment_ref, "environment")
        expect_kind(self.policy_ref, "policy")
        fixed = (self.candidate_ref, self.input_set_ref, self.artifact_ref)
        if self.purpose == "development":
            if self.workspace_id is None or any(ref is not None for ref in fixed):
                raise ValueError("DEVELOPMENT_BINDING")
        elif self.workspace_id is not None or any(ref is None for ref in fixed):
            raise ValueError("FIXED_CANDIDATE_BINDING")
        for ref, kind in zip(fixed, ("candidate", "input_set", "artifact"), strict=True):
            if ref is not None:
                expect_kind(ref, kind)
        human = self.human_test_session_id is not None and self.test_round is not None
        if (self.purpose == "human_test") != human or (
            self.purpose != "human_test" and (self.human_test_session_id is not None or self.test_round is not None)
        ):
            raise ValueError("HUMAN_TEST_BINDING")
        return self


class PreviewEvidence(Contract):
    group: EvidenceGroup
    client_route: ClientRouteName
    runtime_ref: EngineeringRef
    evidence_ref: EngineeringRef

    @model_validator(mode="after")
    def check_reference(self):
        expect_kind(self.runtime_ref, "descriptor")
        expect_kind(self.evidence_ref, "evidence")
        return self


class PreviewClientRoute(Contract):
    route: ClientRouteName
    runtime_ref: EngineeringRef
    ticket_location: Literal["protected_post_body"] = "protected_post_body"
    redemption_method: Literal["POST"] = "POST"
    redemption_path: Literal["/__cloudhelm/redeem"] = "/__cloudhelm/redeem"
    cookie_same_site: Literal["Strict"] = "Strict"
    dns_tls_verified: Flag = False
    isolation_evidence: tuple[PreviewEvidence, ...] = Field(default=(), max_length=6)


def check_client_route(route: PreviewClientRoute) -> None:
    expect_kind(route.runtime_ref, "descriptor")
    if not route.dns_tls_verified or {item.group for item in route.isolation_evidence} != EVIDENCE_GROUPS:
        raise ValueError("UNVERIFIED_CLIENT_ROUTE")
    if any(item.client_route != route.route or item.runtime_ref != route.runtime_ref for item in route.isolation_evidence):
        raise ValueError("CLIENT_EVIDENCE_BINDING")


class PreviewRawPortAccess(Contract):
    service: Literal["frontend", "backend", "hmr", "database"]
    port: Annotated[int, Field(strict=True, ge=1, le=65535)]
    transport: Literal["tcp"] = "tcp"
    address_family: Literal["ipv4"] = "ipv4"
    caller: Literal["preview_proxy", "same_instance_frontend", "same_instance_backend"]
    source_instance_id: Identifier
    target_instance_id: Identifier
    approved_mapping_ref: EngineeringRef
    purpose: Literal["development", "candidate", "human_test"]

    @model_validator(mode="after")
    def check_allowlist(self):
        allowed = {
            ("frontend", 80, "preview_proxy"), ("backend", 8000, "preview_proxy"),
            ("backend", 8000, "same_instance_frontend"), ("hmr", 5173, "preview_proxy"),
            ("database", 5432, "same_instance_backend"),
        }
        expect_kind(self.approved_mapping_ref, "descriptor")
        if self.source_instance_id != self.target_instance_id or (
            self.service, self.port, self.caller
        ) not in allowed or (self.service == "hmr" and self.purpose != "development"):
            raise ValueError("RAW_PORT_ACCESS_DENIED")
        return self


class PreviewExchange(Contract):
    binding: PreviewBinding
    ticket_id: Identifier
    ticket_state_before: Literal["unused"] = "unused"
    ticket_state_after: Literal["unused", "consumed"]
    issued_at: UtcTimestamp
    checked_at: UtcTimestamp
    ticket_expires_at: UtcTimestamp
    authorization_expires_at: UtcTimestamp
    environment_expires_at: UtcTimestamp
    committed: Flag
    redemption_id: Identifier | None = None
    session_ids: tuple[Identifier, ...] = Field(default=(), max_length=1)
    session_expires_at: UtcTimestamp | None = None
    response_state: Literal["not_sent", "delivered", "lost"] = "not_sent"
    credential_reissued: Literal[False] = False

    @model_validator(mode="after")
    def check_exchange_facts(self):
        limit = min(self.authorization_expires_at, self.environment_expires_at)
        if not self.issued_at <= self.checked_at < self.ticket_expires_at <= min(
            limit, self.issued_at + timedelta(seconds=60)
        ):
            raise ValueError("TICKET_TIME_WINDOW")
        if self.committed:
            if self.ticket_state_after != "consumed" or self.redemption_id is None or len(self.session_ids) != 1:
                raise ValueError("UNIQUE_ATOMIC_EXCHANGE_FACTS_REQUIRED")
            if self.session_expires_at is None or not self.checked_at < self.session_expires_at <= limit:
                raise ValueError("SESSION_SCOPE_EXPIRY")
        elif self.ticket_state_after != "unused" or self.redemption_id is not None or (
            self.session_ids or self.session_expires_at is not None or self.response_state != "not_sent"
        ):
            raise ValueError("UNCOMMITTED_EXCHANGE_HAS_NO_SESSION")
        return self


def check_redemption(exchange: PreviewExchange, route: PreviewClientRoute,
                     current_binding: PreviewBinding, currently_authorized: bool) -> None:
    """Validate supplied admission facts; never consumes a ticket or creates a session."""
    check_client_route(route)
    if currently_authorized is not True or exchange.binding != current_binding:
        raise ValueError("CURRENT_PREVIEW_BINDING_DENIED")


class PreviewProxyControl(Contract):
    clock_continuous: Flag = False
    current_authorization_verified: Flag = False
    session_authenticated: Flag = False
    last_verified_control_mono_ms: Millis
    observed_mono_ms: Millis
    control_age_upper_ms: Millis
    failure_detected_mono_ms: Millis | None = None
    failure_age_upper_ms: Millis | None = None
    new_access_enabled: Flag = False
    remaining_connections: Count = 0


def check_proxy_access(control: PreviewProxyControl) -> None:
    raw_age = control.observed_mono_ms - control.last_verified_control_mono_ms
    if not control.new_access_enabled or not control.clock_continuous or not control.current_authorization_verified or not control.session_authenticated or (
        control.failure_detected_mono_ms is not None or not 0 <= raw_age <= control.control_age_upper_ms < CONTROL_MAX_GAP_MS
    ):
        raise ValueError("PROXY_ACCESS_FAIL_CLOSED")


def check_preview_request(session: PreviewExchange, route: PreviewClientRoute, control: PreviewProxyControl,
                          current_binding: PreviewBinding, checked_at: UtcTimestamp) -> None:
    check_client_route(route)
    if not session.committed or session.binding != current_binding or session.session_expires_at is None or (
        not session.checked_at <= checked_at < session.session_expires_at
    ):
        raise ValueError("PREVIEW_SESSION_BINDING_OR_EXPIRY")
    check_proxy_access(control)


def check_proxy_shutdown(control: PreviewProxyControl) -> None:
    """Check closure observations separately; denial is not evidence of termination."""
    now, last = control.observed_mono_ms, control.last_verified_control_mono_ms
    if not control.clock_continuous or now < last:
        if control.new_access_enabled or control.remaining_connections:
            raise ValueError("UNKNOWN_CLOCK_REQUIRES_CLOSED_PROXY")
        return
    failure = control.failure_detected_mono_ms
    if control.control_age_upper_ms < now - last or (failure is None) != (control.failure_age_upper_ms is None):
        raise ValueError("INVALID_CONTROL_TIME_BOUND")
    if failure is not None and (not last <= failure <= now or control.failure_age_upper_ms < now - failure):
        raise ValueError("INVALID_FAILURE_ANCHOR")
    gap_expired = control.control_age_upper_ms >= CONTROL_MAX_GAP_MS
    failed = failure is not None or not control.current_authorization_verified or gap_expired
    if failed and control.new_access_enabled:
        raise ValueError("FAILED_CONTROL_MUST_DENY_NEW_ACCESS")
    if failed and failure is None and not gap_expired:
        raise ValueError("FIRST_FAILURE_ANCHOR_REQUIRED")
    cleanup_due = control.control_age_upper_ms >= CONTROL_MAX_GAP_MS + CONNECTION_CLEANUP_MS or (
        control.failure_age_upper_ms is not None and control.failure_age_upper_ms >= CONNECTION_CLEANUP_MS
    )
    if failed and cleanup_due and control.remaining_connections:
        raise ValueError("CONTROL_GAP_CONNECTIONS_NOT_CLOSED")


class PreviewProxyIdentity(Contract):
    proxy_id: Identifier
    boot_id: Identifier


class PreviewProxyClosure(Contract):
    proxy: PreviewProxyIdentity
    binding: PreviewBinding
    revoke_revision: Revision
    hub_clock_epoch: Identifier
    received_elapsed_upper_ms: Millis
    new_access_denied: Flag = False
    all_routes_closed: Flag = False
    sessions_disabled: Flag = False
    remaining_client_connections: Count
    remaining_upstream_connections: Count
    denied_at: UtcTimestamp | None = None
    connections_closed_at: UtcTimestamp | None = None


class PreviewRevocation(Contract):
    binding: PreviewBinding
    revoke_revision: Revision
    requested_at: UtcTimestamp
    deadline_at: UtcTimestamp
    hub_clock_epoch: Identifier
    observed_hub_clock_epoch: Identifier
    elapsed_upper_ms: Millis
    timing_evidence_current: Flag = False
    required_proxies: tuple[PreviewProxyIdentity, ...] = Field(min_length=1, max_length=32)
    additional_possible_proxies: tuple[PreviewProxyIdentity, ...] = Field(default=(), max_length=32)
    closures: tuple[PreviewProxyClosure, ...] = Field(default=(), max_length=64)

    @model_validator(mode="after")
    def check_revocation_facts(self):
        if self.revoke_revision <= self.binding.authorization_revision:
            raise ValueError("REVOCATION_REVISION_MUST_ADVANCE")
        if self.deadline_at != self.requested_at + timedelta(milliseconds=REVOKE_TIMEOUT_MS):
            raise ValueError("REVOCATION_DEADLINE_NOT_RESETTABLE")
        expected = set(self.required_proxies) | set(self.additional_possible_proxies)
        if len(expected) != len(self.required_proxies) + len(self.additional_possible_proxies):
            raise ValueError("DUPLICATE_REQUIRED_PROXY")
        identities = [item.proxy for item in self.closures]
        if len(set(identities)) != len(identities) or any(proxy not in expected for proxy in identities):
            raise ValueError("DUPLICATE_OR_UNREGISTERED_PROXY_CONFIRMATION")
        for item in self.closures:
            if item.binding != self.binding or item.revoke_revision != self.revoke_revision or (
                item.hub_clock_epoch != self.hub_clock_epoch or item.received_elapsed_upper_ms > self.elapsed_upper_ms
            ):
                raise ValueError("REVOCATION_CONFIRMATION_BINDING")
            if item.denied_at is not None and item.connections_closed_at is not None and item.denied_at > item.connections_closed_at:
                raise ValueError("CLOSE_INGRESS_BEFORE_CONNECTIONS")
        return self


def revocation_status(record: PreviewRevocation) -> str:
    if not record.timing_evidence_current or record.hub_clock_epoch != record.observed_hub_clock_epoch:
        return "pending_time_unknown"
    expected = set(record.required_proxies) | set(record.additional_possible_proxies)
    closed = {
        item.proxy for item in record.closures
        if item.new_access_denied and item.all_routes_closed and item.sessions_disabled
        and item.remaining_client_connections == item.remaining_upstream_connections == 0
        and item.denied_at is not None and item.connections_closed_at is not None
    }
    if closed != expected:
        return "timed_out" if record.elapsed_upper_ms >= REVOKE_TIMEOUT_MS else "pending"
    last_confirmation = max(item.received_elapsed_upper_ms for item in record.closures)
    return "effective" if last_confirmation <= REVOKE_TIMEOUT_MS else "effective_late"


class P0PreviewContracts(Contract):
    protocol_revision: ProtocolRevision = "p0-decisions-r1"
    binding: PreviewBinding
    client_route: PreviewClientRoute
    raw_port_access: PreviewRawPortAccess
    exchange: PreviewExchange
    proxy_control: PreviewProxyControl
    revocation: PreviewRevocation
