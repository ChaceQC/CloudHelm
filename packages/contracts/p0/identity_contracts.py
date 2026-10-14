"""P0 identity decisions and pure checks; no authentication or persistent ledger."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Literal

import rfc8785
from pydantic import Field, StrictBool, field_validator, model_validator

from packages.contracts.p0.decision_common import (
    Contract, Digest, Identifier, ProtocolRevision, Revision,
)
from packages.contracts.p0.engineering_contracts import EngineeringRef, expect_kind

Action = Literal[
    "resource.read", "project.manage", "task.command", "task.cancel",
    "workspace.write", "candidate.submit", "review.submit", "human_test.enter",
    "human_test.pass", "human_test.request_changes", "human_test.skip",
    "deployment.approve", "operation.request", "operation.query", "operation.stop",
    "operation.reconcile", "fact.archive", "step.execute", "emergency.execute",
    "emergency.handover",
]
Role = Literal[
    "project_owner", "developer", "reviewer", "tester", "deployment_approver",
    "agent", "executor", "emergency_admin",
]


class Principal(Contract):
    kind: Literal["human", "agent", "executor"]
    subject_id: Identifier
    delegator_id: Identifier | None = None

    @model_validator(mode="after")
    def delegation_shape(self) -> Principal:
        if (self.kind == "agent") != (self.delegator_id is not None):
            raise ValueError("agent_delegator_required_only_for_agent")
        return self


class ResourceScope(Contract):
    project_id: Identifier
    resource_kind: Identifier
    resource_id: Identifier


class CommandIntent(Contract):
    protocol_revision: ProtocolRevision = "p0-decisions-r1"
    digest_profile: Literal["cloudhelm-jcs-sha256-r1"] = "cloudhelm-jcs-sha256-r1"
    request_schema_revision: Identifier
    caller: Principal
    scope: ResourceScope
    target: ResourceScope
    action: Action
    expected_resource_revision: Revision
    references: tuple[EngineeringRef, ...] = Field(default=(), max_length=32)

    @field_validator("references")
    @classmethod
    def supported_references(cls, refs: tuple[EngineeringRef, ...]) -> tuple[EngineeringRef, ...]:
        for ref in refs:
            expect_kind(ref, "artifact", "environment_config", "input_set",
                        "deployment_plan", "secret_version")
        return refs

    @model_validator(mode="after")
    def target_project(self) -> CommandIntent:
        if self.scope.project_id != self.target.project_id:
            raise ValueError("target_project_mismatch")
        return self


class CommandEnvelope(CommandIntent):
    command_id: Identifier
    idempotency_key: Identifier
    request_digest: Digest


class AuthorizationEnvelope(Contract):
    """Trusted adapter's fresh authorization facts, never a client capability."""

    protocol_revision: ProtocolRevision = "p0-decisions-r1"
    caller: Principal
    role: Role
    scope: ResourceScope
    target: ResourceScope
    action: Action
    permission_revision: Revision
    policy_revision: Revision
    resource_revision: Revision
    audit_session_id: Identifier
    decision_id: Identifier
    allowed: StrictBool = False
    delegation_current: StrictBool = False


class IdempotencyRecord(Contract):
    caller: Principal
    scope: ResourceScope
    idempotency_key: Identifier
    command_id: Identifier
    request_digest: Digest
    operation_id: Identifier | None = None
    report_id: Identifier | None = None
    result_ref: Identifier | None = None


class P0IdentityContracts(Contract):
    """Schema collection only; these fields do not form a runtime aggregate."""

    command: CommandEnvelope
    authorization: AuthorizationEnvelope
    idempotency_record: IdempotencyRecord


_CONTROL = {"task.command", "task.cancel", "operation.request", "operation.query",
            "operation.stop", "operation.reconcile", "fact.archive"}
_ROLE_ACTIONS: dict[str, set[str]] = {
    "project_owner": _CONTROL | {"resource.read", "project.manage", "deployment.approve"},
    "developer": _CONTROL | {"resource.read", "workspace.write", "candidate.submit"},
    "reviewer": {"resource.read", "review.submit"},
    "tester": {"human_test.enter", "human_test.pass", "human_test.request_changes",
               "human_test.skip"},
    "deployment_approver": {"resource.read", "deployment.approve"},
    "agent": _CONTROL | {"resource.read", "workspace.write", "candidate.submit"},
    "executor": {"step.execute", "operation.query", "fact.archive"},
    "emergency_admin": {"emergency.execute", "emergency.handover"},
}


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ValueError("nonfinite_json_number")


def _load_json(raw: str) -> object:
    try:
        return json.loads(raw, object_pairs_hook=_unique_object,
                          parse_constant=_reject_constant)
    except (ValueError, TypeError, UnicodeError):
        raise ValueError("invalid_json_input") from None


def _jcs(value: object) -> bytes:
    try:
        return rfc8785.dumps(value)
    except (ValueError, TypeError, UnicodeError):
        raise ValueError("invalid_jcs_input") from None


def canonical_json(raw: str) -> bytes:
    """Reject duplicate keys, nonfinite numbers and integers outside JCS bounds."""
    return _jcs(_load_json(raw))


def parse_request(raw: str, schema: type[Contract]) -> Contract:
    """Use the route's fixed public-only schema before digesting any request."""
    value = _load_json(raw)
    _jcs(value)
    try:
        return schema.model_validate(value)
    except ValueError:
        raise ValueError("request_schema_invalid") from None


def canonical_decimal(value: str) -> str:
    """For schema-declared decimal strings only; never normalize ordinary text."""
    if not re.fullmatch(r"-?(0|[1-9][0-9]*)(\.[0-9]+)?", value):
        raise ValueError("invalid_decimal_string")
    integer, separator, fraction = value.partition(".")
    fraction = fraction.rstrip("0")
    normalized = integer + (separator + fraction if fraction else "")
    return "0" if normalized == "-0" else normalized


def request_digest(intent: CommandIntent, request: Contract) -> str:
    """The adapter supplies a schema-validated body with resolved public refs."""
    envelope = intent.model_dump(mode="json", include=set(CommandIntent.model_fields))
    envelope["normalized_request"] = request.model_dump(mode="json")
    return "sha256:" + hashlib.sha256(_jcs(envelope)).hexdigest()


def check_command(
    command: CommandEnvelope,
    authorization: AuthorizationEnvelope,
    existing: IdempotencyRecord | None = None,
) -> Literal["new", "replay"]:
    """Check fresh facts then dedupe then version; no I/O or side effects."""
    for field in ("caller", "scope", "target", "action"):
        if getattr(command, field) != getattr(authorization, field):
            raise ValueError("authorization_binding_mismatch")
    expected_kind = authorization.role if authorization.role in {"agent", "executor"} else "human"
    if command.caller.kind != expected_kind:
        raise ValueError("principal_kind_mismatch")
    if not authorization.allowed:
        raise ValueError("permission_denied")
    if command.action not in _ROLE_ACTIONS[authorization.role]:
        raise ValueError("role_action_denied")
    if command.caller.kind == "agent" and not authorization.delegation_current:
        raise ValueError("delegation_not_current")
    if command.action.startswith("emergency."):
        raise ValueError("emergency_not_enabled_before_p4")
    if existing is not None:
        for field in ("caller", "scope", "idempotency_key"):
            if getattr(command, field) != getattr(existing, field):
                raise ValueError("idempotency_scope_mismatch")
        if command.request_digest != existing.request_digest:
            raise ValueError("idempotency_digest_conflict")
        return "replay"
    if command.expected_resource_revision != authorization.resource_revision:
        raise ValueError("resource_revision_conflict")
    return "new"
