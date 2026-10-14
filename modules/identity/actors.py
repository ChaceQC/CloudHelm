"""Internal authenticated identities; none of these are public request schemas."""

from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import select

from database.uow import UnitOfWork
from modules.identity.errors import IdentityError
from modules.identity.tables import audit_records
from packages.contracts.p0.identity_contracts import AuthorizationEnvelope, Principal, ResourceScope


_HTTP_PROOF = object()
_COMMAND_PROOF = object()


@dataclass(frozen=True, slots=True)
class AuthenticatedActor:
    principal: Principal
    session_id: str
    session_revision: int
    _proof: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._proof is not _HTTP_PROOF or self.principal.kind != "human":
            raise IdentityError("authentication_failed")

    @property
    def audit_session_id(self) -> str:
        return self.session_id

    @property
    def authentication_source(self) -> Literal["device_session"]:
        return "device_session"


@dataclass(frozen=True, slots=True)
class RecordedCommandActor:
    principal: Principal
    command_id: str
    audit_session_id: str
    authorization_decision_id: str
    source_scope: ResourceScope
    source_target: ResourceScope
    delegation_id: str | None
    _proof: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._proof is not _COMMAND_PROOF:
            raise IdentityError("recorded_actor_not_found")

    @property
    def authentication_source(self) -> Literal["recorded_command"]:
        return "recorded_command"


Actor = AuthenticatedActor | RecordedCommandActor


@dataclass(frozen=True, slots=True)
class AuthoritativeResource:
    """Resource identity resolved by its owning domain, never from client claims."""

    project_id: str
    resource_kind: str
    resource_id: str
    revision: int = 0
    task_id: str | None = None
    target: ResourceScope | None = None

    def __post_init__(self) -> None:
        if type(self.revision) is not int or not 0 <= self.revision <= 9007199254740991:
            raise IdentityError("authorization_binding_mismatch")
        if self.target is not None and self.target.project_id != self.project_id:
            raise IdentityError("authorization_binding_mismatch")
        if self.resource_kind == "project" and self.resource_id != self.project_id:
            raise IdentityError("authorization_binding_mismatch")
        if self.target is not None and self.target.resource_kind == "project":
            if self.target.resource_id != self.project_id:
                raise IdentityError("authorization_binding_mismatch")
        if self.resource_kind == "task" and self.task_id not in {None, self.resource_id}:
            raise IdentityError("authorization_binding_mismatch")
        if (self.resource_kind == "task" and self.target is not None
                and self.target.resource_kind == "task" and self.target.resource_id != self.resource_id):
            raise IdentityError("authorization_binding_mismatch")
        _ = self.scope

    @property
    def scope(self) -> ResourceScope:
        return ResourceScope(
            project_id=self.project_id, resource_kind=self.resource_kind,
            resource_id=self.resource_id,
        )

    @property
    def target_scope(self) -> ResourceScope:
        return self.target or self.scope

    @property
    def bound_task_id(self) -> str | None:
        return self.resource_id if self.resource_kind == "task" else self.task_id


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    envelope: AuthorizationEnvelope
    role_binding_id: str | None
    delegation_id: str | None


def _authenticated_actor(user_id: str, session_id: str, revision: int) -> AuthenticatedActor:
    return AuthenticatedActor(
        principal=Principal(kind="human", subject_id=user_id),
        session_id=session_id, session_revision=revision, _proof=_HTTP_PROOF,
    )


def validate_actor(actor: Actor) -> None:
    if isinstance(actor, AuthenticatedActor) and actor._proof is _HTTP_PROOF:
        return
    if isinstance(actor, RecordedCommandActor) and actor._proof is _COMMAND_PROOF:
        return
    raise IdentityError("authentication_failed")


def actor_for_command(uow: UnitOfWork, command_id: str) -> RecordedCommandActor:
    """Resolve an accepted command and its matching immutable authorization audit."""
    from database.commands import get_by_id

    command = get_by_id(uow.connection, command_id)
    if command is None or not 200 <= command.status_code < 300:
        raise IdentityError("recorded_actor_not_found")
    record = uow.connection.execute(select(audit_records).where(
        audit_records.c.decision_id == command.authorization_decision_id,
    )).mappings().one_or_none()
    envelope = command.envelope
    if record is None or record["outcome"] != "allowed":
        raise IdentityError("recorded_actor_not_found")
    matches = (
        record["audit_session_id"] == command.audit_session_id,
        record["caller_kind"] == envelope.caller.kind,
        record["subject_id"] == envelope.caller.subject_id,
        record["delegator_id"] == envelope.caller.delegator_id,
        record["project_id"] == envelope.scope.project_id,
        record["scope_json"] == envelope.scope.model_dump(mode="json"),
        record["target_json"] == envelope.target.model_dump(mode="json"),
        record["action"] == envelope.action,
        record["authentication_source"] != "anonymous",
    )
    if not all(matches) or envelope.caller.kind == "executor":
        raise IdentityError("authorization_binding_mismatch")
    if (envelope.caller.kind == "agent") != (record["delegation_id"] is not None):
        raise IdentityError("authorization_binding_mismatch")
    return RecordedCommandActor(
        principal=envelope.caller, command_id=command_id,
        audit_session_id=command.audit_session_id,
        authorization_decision_id=command.authorization_decision_id,
        source_scope=envelope.scope, source_target=envelope.target,
        delegation_id=record["delegation_id"], _proof=_COMMAND_PROOF,
    )


def check_recorded_scope(actor: RecordedCommandActor, resource: AuthoritativeResource) -> None:
    """An accepted command cannot become a worker capability for other resources."""
    if actor.source_scope.project_id != resource.project_id:
        raise IdentityError("authorization_binding_mismatch")
    if actor.source_scope.resource_kind == "task":
        if actor.source_scope.resource_id != resource.bound_task_id:
            raise IdentityError("authorization_binding_mismatch")
    elif actor.source_scope != resource.scope or actor.source_target != resource.target_scope:
        raise IdentityError("authorization_binding_mismatch")
