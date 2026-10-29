"""Preview instance and public authorization facts; credentials stay transient."""

from dataclasses import dataclass, field
from ipaddress import ip_address
import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator

from packages.contracts.p0.decision_common import Contract, Identifier, Revision
from packages.contracts.p0.engineering_contracts import EngineeringRef, UtcTimestamp, expect_kind
from packages.contracts.p0.preview_contracts import (
    PreviewBinding, PreviewClientRoute, PreviewProxyIdentity, PreviewRevocation,
)


def _origin(value: str) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.path or parsed.query or parsed.fragment
            or value != f"https://{parsed.hostname}" or parsed.port is not None
            or re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+",
                            parsed.hostname) is None):
        raise ValueError("preview_https_origin_required")
    try:
        ip_address(parsed.hostname)
    except ValueError:
        return parsed.hostname
    raise ValueError("preview_dns_name_required")


class PreviewUpstream(Contract):
    """Runner-registered mapping, never supplied in a user access request."""

    service: Literal["frontend", "backend", "hmr"]
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(strict=True, ge=1, le=65535)
    scheme: Literal["http"] = "http"

    @model_validator(mode="after")
    def check_mapping(self):
        if (self.port != {"frontend": 80, "backend": 8000, "hmr": 5173}[self.service]
                or re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9.-]*", self.host) is None):
            raise ValueError("preview_upstream_port_not_allowed")
        return self


class PreviewEnvironmentRecord(Contract):
    environment_id: Identifier
    project_id: Identifier
    task_id: Identifier
    purpose: Literal["development", "candidate", "human_test"]
    revision: Revision
    actual_revision: str | None = Field(default=None, min_length=1, max_length=256)
    environment_ref: EngineeringRef
    policy_ref: EngineeringRef
    expires_at: UtcTimestamp
    state: Literal["preparing", "ready", "stopping", "stopped", "failed"]
    resource_reservation_id: Identifier | None = None
    entry_origin: str | None = Field(default=None, max_length=512)
    management_origin: str | None = Field(default=None, max_length=512)
    client_route: PreviewClientRoute | None = None
    required_proxies: tuple[PreviewProxyIdentity, ...] = Field(default=(), max_length=32)
    upstreams: tuple[PreviewUpstream, ...] = Field(default=(), max_length=3)
    workspace_id: Identifier | None = None
    candidate_id: Identifier | None = None
    candidate_ref: EngineeringRef | None = None
    input_set_ref: EngineeringRef | None = None
    artifact_ref: EngineeringRef | None = None
    human_test_session_id: Identifier | None = None
    test_round: Revision | None = None

    @model_validator(mode="after")
    def check_binding(self):
        expect_kind(self.environment_ref, "environment")
        expect_kind(self.policy_ref, "policy")
        fixed = (self.candidate_id, self.candidate_ref, self.input_set_ref, self.artifact_ref)
        if self.purpose == "development":
            if self.workspace_id is None or any(item is not None for item in fixed):
                raise ValueError("preview_development_binding_invalid")
        elif self.workspace_id is not None or any(item is None for item in fixed):
            raise ValueError("preview_candidate_binding_invalid")
        for ref, kind in ((self.candidate_ref, "candidate"), (self.input_set_ref, "input_set"),
                          (self.artifact_ref, "artifact")):
            if ref is not None:
                expect_kind(ref, kind)
        if self.purpose == "human_test":
            if self.human_test_session_id is None or self.test_round != 1:
                raise ValueError("preview_human_round_invalid")
        elif self.human_test_session_id is not None or self.test_round is not None:
            raise ValueError("preview_human_round_invalid")
        if self.entry_origin is not None and self.management_origin is not None:
            if _origin(self.entry_origin) == _origin(self.management_origin):
                raise ValueError("preview_management_host_must_differ")
        elif self.entry_origin is not None:
            _origin(self.entry_origin)
        elif self.management_origin is not None:
            _origin(self.management_origin)
        if (len(set(self.required_proxies)) != len(self.required_proxies)
                or len({item.service for item in self.upstreams}) != len(self.upstreams)
                or self.purpose != "development" and any(item.service == "hmr" for item in self.upstreams)):
            raise ValueError("preview_mapping_invalid")
        if self.state == "ready" and (not self.actual_revision or not self.resource_reservation_id
                                      or not self.entry_origin or not self.management_origin
                                      or self.client_route is None or not self.required_proxies or not self.upstreams):
            raise ValueError("preview_ready_descriptor_incomplete")
        return self


class PreviewAccessRequest(Contract):
    expected_version: Revision
    expected_control_revision: Revision
    expected_input_validity_revision: Revision
    expected_environment_revision: Revision
    expires_at: UtcTimestamp


class PreviewLocalClosure(Contract):
    proxy: PreviewProxyIdentity
    denied_at: UtcTimestamp
    closed_at: UtcTimestamp
    client_connections: int = Field(strict=True, ge=0)
    upstream_connections: int = Field(strict=True, ge=0)

    @model_validator(mode="after")
    def check_order(self):
        if self.closed_at < self.denied_at:
            raise ValueError("preview_closure_order_invalid")
        return self


class PreviewAuthorizationRecord(Contract):
    command_id: Identifier
    environment_id: Identifier
    environment_revision: Revision
    binding: PreviewBinding
    control_revision: Revision
    input_validity_revision: Revision
    issued_at: UtcTimestamp
    expires_at: UtcTimestamp
    ticket_expires_at: UtcTimestamp
    required_proxies: tuple[PreviewProxyIdentity, ...] = Field(min_length=1, max_length=32)
    ticket_state: Literal["unused", "consumed"] = "unused"
    redemption_id: Identifier | None = None
    session_id: Identifier | None = None
    state: Literal["active", "revoking", "revoked"] = "active"
    revocation: PreviewRevocation | None = None
    local_closures: tuple[PreviewLocalClosure, ...] = Field(default=(), max_length=64)


@dataclass(frozen=True, slots=True)
class PreviewIssueResult:
    authorization: PreviewAuthorizationRecord
    ticket: SecretStr | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class PreviewRedeemResult:
    authorization: PreviewAuthorizationRecord
    session_id: str
    cookie: SecretStr = field(repr=False)


@dataclass(frozen=True, slots=True)
class PreviewAuthenticated:
    authorization: PreviewAuthorizationRecord
    environment: PreviewEnvironmentRecord
