"""Fixed P0 contract examples only; no claim of product authorization coverage."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Callable

from pydantic import Field, JsonValue

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from packages.contracts.p0.decision_common import Contract
from packages.contracts.p0.engineering_contracts import EngineeringRef
from packages.contracts.p0.identity_contracts import (
    AuthorizationEnvelope, CommandEnvelope, CommandIntent, IdempotencyRecord,
    Principal, ResourceScope, canonical_decimal, canonical_json,
    check_command, parse_request, request_digest,
)


class FixedPublicRequest(Contract):
    mode: str = "inspect"
    options: dict[str, JsonValue] = Field(default_factory=dict)


def _reject(action: Callable[[], object], code: str | None = None) -> None:
    try:
        action()
    except ValueError as error:
        if code is not None and str(error) != code:
            raise AssertionError("unexpected_rejection_code") from None
        return
    raise AssertionError("invalid_contract_accepted")


def _check_references(intent: CommandIntent, request: Contract, digest: str) -> None:
    refs = tuple(EngineeringRef(kind=kind, object_id=f"{kind}-fixture", revision="r1",
                               authority="hub-fixture", digest=digest, digest_algorithm="sha256")
                 for kind in ("artifact", "environment_config", "input_set", "deployment_plan"))
    secret = EngineeringRef(kind="secret_version", object_id="secret-ref", revision="r1",
                            authority="secret-store-fixture")
    bound = CommandIntent.model_validate({**intent.model_dump(), "references": (*refs, secret)})
    assert bound.references == (*refs, secret)
    bound_digest = request_digest(bound, request)
    assert bound_digest != digest
    changed = CommandIntent.model_validate({**bound.model_dump(), "references": (
        *refs, secret.model_copy(update={"revision": "r2"}),
    )})
    assert request_digest(changed, request) != bound_digest
    _reject(lambda: EngineeringRef(**{**secret.model_dump(), "digest": digest,
                                      "digest_algorithm": "sha256"}))
    _reject(lambda: EngineeringRef.model_validate({**secret.model_dump(), "value": "synthetic-forbidden-field"}))
    unsupported = EngineeringRef(kind="evidence", object_id="evidence-fixture", revision="r1",
                                 digest=digest, digest_algorithm="sha256")
    _reject(lambda: CommandIntent.model_validate({**intent.model_dump(), "references": (unsupported,)}))


def run_checks() -> dict[str, bool]:
    scope = ResourceScope(project_id="project-fixture", resource_kind="task", resource_id="task-fixture")
    principal = Principal(kind="human", subject_id="developer-fixture")
    intent = CommandIntent(
        request_schema_revision="fixed-public-request-r1", caller=principal,
        scope=scope, target=scope, action="task.command", expected_resource_revision=7,
    )
    request = parse_request('{"options":{"b":2,"a":1}}', FixedPublicRequest)
    digest = request_digest(intent, request)
    same = parse_request('{"mode":"inspect","options":{"a":1,"b":2}}', FixedPublicRequest)
    assert request_digest(intent, same) == digest
    changed = parse_request('{"options":{"a":1,"b":3}}', FixedPublicRequest)
    assert request_digest(intent, changed) != digest
    absent = parse_request('{}', FixedPublicRequest)
    null_member = parse_request('{"options":{"note":null}}', FixedPublicRequest)
    assert request_digest(intent, absent) != request_digest(intent, null_member)
    assert canonical_json('{"z":-0.0,"a":[1,2]}') == b'{"a":[1,2],"z":0}'
    assert canonical_json('[1,2]') != canonical_json('[2,1]')
    for invalid in ('{"x":1,"x":2}', '[NaN]', '[Infinity]', '[1e400]',
                    '[9007199254740992]', '[-9007199254740992]'):
        _reject(lambda invalid=invalid: canonical_json(invalid))
    assert canonical_decimal("123456789012345678901.2300") == "123456789012345678901.23"
    assert canonical_decimal("-0.000") == "0"
    for invalid in ("+1", "01", "1e2", ".5", "1."):
        _reject(lambda invalid=invalid: canonical_decimal(invalid))
    _reject(lambda: parse_request('{"secret_value":"synthetic-forbidden-field"}', FixedPublicRequest))
    _check_references(intent, request, digest)

    command = CommandEnvelope(**intent.model_dump(), command_id="command-fixture",
                              idempotency_key="key-fixture", request_digest=digest)
    authorization = AuthorizationEnvelope(
        caller=principal, role="developer", scope=scope, target=scope,
        action="task.command", permission_revision=3, policy_revision=2,
        resource_revision=7, audit_session_id="session-fixture", decision_id="decision-fixture",
        allowed=True,
    )
    assert check_command(command, authorization) == "new"
    existing = IdempotencyRecord(
        caller=principal, scope=scope, idempotency_key="key-fixture",
        command_id="command-fixture", request_digest=digest,
        operation_id="operation-fixture", result_ref="result-fixture",
    )
    advanced = authorization.model_copy(update={"resource_revision": 8})
    assert check_command(command, advanced, existing) == "replay"
    _reject(lambda: check_command(command, advanced), "resource_revision_conflict")
    denied = authorization.model_copy(update={"allowed": False})
    _reject(lambda: check_command(command, denied, existing), "permission_denied")
    conflicting = command.model_copy(update={"request_digest": request_digest(intent, changed)})
    _reject(lambda: check_command(conflicting, authorization, existing), "idempotency_digest_conflict")
    different_scope = existing.model_copy(update={"scope": scope.model_copy(update={"resource_id": "other-task"})})
    _reject(lambda: check_command(command, authorization, different_scope), "idempotency_scope_mismatch")
    other_principal = Principal(kind="human", subject_id="other-developer")
    _reject(lambda: check_command(command, authorization.model_copy(update={"caller": other_principal})),
            "authorization_binding_mismatch")

    agent = Principal(kind="agent", subject_id="agent-fixture", delegator_id="owner-fixture")
    agent_command = command.model_copy(update={"caller": agent, "action": "deployment.approve"})
    agent_auth = authorization.model_copy(update={"caller": agent, "role": "agent",
                                                   "action": "deployment.approve", "delegation_current": True})
    _reject(lambda: check_command(agent_command, agent_auth), "role_action_denied")
    reviewer_auth = agent_auth.model_copy(update={"role": "deployment_approver"})
    _reject(lambda: check_command(agent_command, reviewer_auth), "principal_kind_mismatch")
    task_agent = command.model_copy(update={"caller": agent})
    revoked_delegation = authorization.model_copy(update={"caller": agent, "role": "agent"})
    _reject(lambda: check_command(task_agent, revoked_delegation), "delegation_not_current")
    _reject(lambda: CommandEnvelope.model_validate({**command.model_dump(), "protocol_revision": "p0-draft-r1"}))
    _reject(lambda: CommandEnvelope.model_validate({**command.model_dump(), "trace_id": "transient-fixture"}))
    _reject(lambda: CommandEnvelope.model_validate({**command.model_dump(), "expected_resource_revision": True}))
    emergency_command = command.model_copy(update={"action": "emergency.execute"})
    emergency_auth = authorization.model_copy(update={"action": "emergency.execute", "role": "emergency_admin"})
    _reject(lambda: check_command(emergency_command, emergency_auth), "emergency_not_enabled_before_p4")
    return {
        "jcs_defaults_and_meaningful_changes": True,
        "invalid_numbers_duplicates_and_secret_shape_rejected": True,
        "shared_engineering_reference_boundary": True,
        "current_permission_before_idempotency": True,
        "replay_before_object_version_check": True,
        "identity_digest_and_scope_conflicts": True,
        "agent_human_and_delegation_boundaries": True,
        "protocol_revision_and_emergency_boundary": True,
    }


if __name__ == "__main__":
    print(json.dumps(run_checks(), ensure_ascii=False, sort_keys=True))
