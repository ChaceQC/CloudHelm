"""Append safe authorization facts on the caller's transaction only."""

from typing import Literal
from uuid import uuid4

from sqlalchemy import insert

from database.uow import UnitOfWork
from modules.identity.actors import (
    Actor, AuthenticatedActor, AuthoritativeResource, AuthorizationDecision,
    RecordedCommandActor, validate_actor,
)
from modules.identity.errors import IdentityError
from modules.identity.tables import audit_records
from packages.contracts.p0.identity_contracts import Action


def _actor_fields(actor: Actor) -> dict[str, object]:
    validate_actor(actor)
    return {
        "caller_kind": actor.principal.kind,
        "subject_id": actor.principal.subject_id,
        "delegator_id": actor.principal.delegator_id,
        "authentication_source": actor.authentication_source,
        "device_session_id": actor.session_id if isinstance(actor, AuthenticatedActor) else None,
        "delegation_id": actor.delegation_id if isinstance(actor, RecordedCommandActor) else None,
        "source_command_id": actor.command_id if isinstance(actor, RecordedCommandActor) else None,
    }


def record_authorization(uow: UnitOfWork, actor: Actor, decision: AuthorizationDecision) -> None:
    envelope = decision.envelope
    uow.connection.execute(insert(audit_records).values(
        **_actor_fields(actor), decision_id=envelope.decision_id,
        audit_session_id=envelope.audit_session_id,
        project_id=envelope.scope.project_id,
        scope_json=envelope.scope.model_dump(mode="json"),
        target_json=envelope.target.model_dump(mode="json"), action=envelope.action,
        role=envelope.role, role_binding_id=decision.role_binding_id,
        permission_revision=envelope.permission_revision,
        policy_revision=envelope.policy_revision, resource_revision=envelope.resource_revision,
        outcome="allowed", reason_code="authorization_granted",
    ))


def record_denial(
    uow: UnitOfWork, *, error: IdentityError, audit_session_id: str,
    actor: Actor | None = None, resource: AuthoritativeResource | None = None,
    action: Action | Literal["auth.authenticate"] = "auth.authenticate",
) -> str:
    """Call in a fresh outer UoW after rollback; pass only server-resolved context."""
    decision_id = str(uuid4())
    fields = _actor_fields(actor) if actor is not None else {"authentication_source": "anonymous"}
    uow.connection.execute(insert(audit_records).values(
        **fields, decision_id=decision_id, audit_session_id=audit_session_id,
        project_id=resource.project_id if resource is not None else None,
        scope_json=resource.scope.model_dump(mode="json") if resource is not None else None,
        target_json=resource.target_scope.model_dump(mode="json") if resource is not None else None,
        action=action, outcome="denied", reason_code=error.code,
    ))
    return decision_id
