"""Canonical request identity and current authorization gates."""

from pydantic import Field, JsonValue, ValidationError

from packages.contracts.p0.decision_common import Contract
from packages.contracts.p0.engineering_contracts import EngineeringRef
from packages.contracts.p0.identity_contracts import (
    AuthorizationEnvelope, CommandEnvelope, CommandIntent, IdempotencyRecord,
    Principal, ResourceScope, canonical_json, check_command, parse_request, request_digest,
)


class PublicRequest(Contract):
    options: dict[str, JsonValue] = Field(default_factory=dict)


def _reject(action, reason: str | None = None) -> None:
    try:
        action()
    except (ValueError, ValidationError) as error:
        if reason is not None and reason not in str(error):
            raise AssertionError(f"unexpected rejection: {reason}") from error
        return
    raise AssertionError(f"missing rejection: {reason or 'invalid request'}")


def run_checks() -> dict[str, bool]:
    person = Principal(kind="human", subject_id="person")
    scope = ResourceScope(project_id="project", resource_kind="task", resource_id="task")
    intent = CommandIntent(
        request_schema_revision="public-r1", caller=person, scope=scope, target=scope,
        action="task.command", expected_resource_revision=3,
    )
    first = parse_request('{"options":{"b":2,"a":1}}', PublicRequest)
    reordered = parse_request('{"options":{"a":1,"b":2}}', PublicRequest)
    changed = parse_request('{"options":{"a":1,"b":3}}', PublicRequest)
    digest = request_digest(intent, first)
    assert request_digest(intent, reordered) == digest
    assert request_digest(intent, changed) != digest
    assert canonical_json('{"value":-0.0}') == b'{"value":0}'
    _reject(lambda: canonical_json('{"x":1,"x":2}'))

    secret = EngineeringRef(kind="secret_version", object_id="secret-ref", revision="r1",
                            authority="secret-store")
    _reject(lambda: EngineeringRef.model_validate({**secret.model_dump(), "value": "synthetic-secret"}))

    command = CommandEnvelope(**intent.model_dump(), command_id="command", idempotency_key="key",
                              request_digest=digest)
    authorization = AuthorizationEnvelope(
        caller=person, role="developer", scope=scope, target=scope, action="task.command",
        permission_revision=1, policy_revision=1, resource_revision=3,
        audit_session_id="audit", decision_id="decision", allowed=True,
    )
    prior = IdempotencyRecord(
        caller=person, scope=scope, idempotency_key="key", command_id="command",
        request_digest=digest, operation_id="operation", result_ref="result",
    )
    assert check_command(command, authorization) == "new"
    assert check_command(command, authorization, prior) == "replay"
    denied = authorization.model_copy(update={"allowed": False})
    _reject(lambda: check_command(command, denied, prior), "permission_denied")
    return {"canonical_digest_and_secret_reference": True, "authorization_precedes_replay": True}
