"""Bounded internal command, event, and workflow handoff contracts for P1.1."""

from __future__ import annotations

from typing import Annotated, Literal

import rfc8785
from pydantic import Field, JsonValue, field_validator

from packages.contracts.p0.decision_common import Contract, Digest, Identifier, Revision
from packages.contracts.p0.identity_contracts import CommandEnvelope

MAX_RESULT_BYTES = 65_536
WorkflowName = Literal[
    "collaboration.task_initial.v1", "collaboration.task_control.v1"
]
HttpResultStatus = Annotated[int, Field(strict=True, ge=200, le=499)]


def validate_public_payload(payload: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Bound UTF-8 JSON; callers still own the public field allowlist."""
    try:
        encoded = rfc8785.dumps(payload)
    except (ValueError, TypeError, UnicodeError):
        raise ValueError("public_payload_invalid") from None
    if len(encoded) > MAX_RESULT_BYTES:
        raise ValueError("public_payload_too_large")
    return payload


def contract_payload(value: Contract) -> dict[str, JsonValue]:
    """Only a route/domain's fixed, validated public Contract may be persisted."""
    if not isinstance(value, Contract):
        raise TypeError("public_contract_required")
    try:
        checked = type(value).model_validate(value.model_dump(mode="python"))
        payload = checked.model_dump(mode="json")
    except (ValueError, TypeError, UnicodeError):
        raise ValueError("public_contract_invalid") from None
    return validate_public_payload(payload)


class PersistedCommand(Contract):
    """Original result, not a new authorization or a new version decision."""

    envelope: CommandEnvelope
    status_code: HttpResultStatus
    result: dict[str, JsonValue]
    audit_session_id: Identifier
    authorization_decision_id: Identifier

    @field_validator("result")
    @classmethod
    def bounded_result(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        return validate_public_payload(value)


class WorkflowDispatch(Contract):
    """A Task binding; the actual workflow receives command_id only."""

    command_id: Identifier
    workflow_id: Identifier
    task_id: Identifier
    advance_revision: Revision
    workflow_name: WorkflowName
    request_digest: Digest


class EventEnvelope(Contract):
    event_id: Identifier
    command_id: Identifier
    project_id: Identifier
    aggregate_kind: Identifier
    aggregate_id: Identifier
    aggregate_version: Revision
    event_type: Identifier
    schema_version: Identifier
    payload: dict[str, JsonValue]

    @field_validator("payload")
    @classmethod
    def bounded_payload(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        return validate_public_payload(value)
