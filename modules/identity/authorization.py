"""Fresh authorization before replay; business state and versions stay with domains."""

from collections.abc import Mapping
from uuid import uuid4

from sqlalchemy import func, select

from database.uow import UnitOfWork
from modules.identity.actors import (
    Actor, AuthoritativeResource, AuthorizationDecision, RecordedCommandActor,
    check_recorded_scope,
)
from modules.identity.audit import record_authorization
from modules.identity.errors import IdentityError
from modules.identity.locking import check_request_session, lock_current_subject, lock_project_policy
from modules.identity.policy import (
    AGENT_ACTIONS, OWNER_ACTIONS, SUPPORTED_ACTIONS,
    validate_delegation_actions, validate_role_actions,
)
from modules.identity.tables import delegations, role_bindings
from modules.projects.tables import projects
from packages.contracts.p0.identity_contracts import Action, AuthorizationEnvelope, Role


def _current_role(
    uow: UnitOfWork, user_id: str, project: Mapping[str, object], action: Action,
) -> tuple[Role, str | None]:
    if project["owner_user_id"] == user_id and action in OWNER_ACTIONS:
        return "project_owner", None
    bindings = uow.connection.execute(select(role_bindings).where(
        role_bindings.c.project_id == project["project_id"],
        role_bindings.c.user_id == user_id, role_bindings.c.revoked_at.is_(None),
    ).order_by(role_bindings.c.binding_id)).mappings().all()
    for binding in bindings:
        actions = validate_role_actions(binding["role"], binding["actions"])
        if action in actions:
            return binding["role"], binding["binding_id"]
    raise IdentityError("permission_denied")


def _current_delegation(
    uow: UnitOfWork, actor: RecordedCommandActor,
    resource: AuthoritativeResource, action: Action,
) -> str:
    if actor.delegation_id is None or action not in AGENT_ACTIONS:
        raise IdentityError("delegation_not_current")
    row = uow.connection.execute(select(delegations).where(
        delegations.c.delegation_id == actor.delegation_id,
    )).mappings().one_or_none()
    now = uow.connection.scalar(select(func.clock_timestamp()))
    if (row is None or row["agent_subject_id"] != actor.principal.subject_id
            or row["delegator_user_id"] != actor.principal.delegator_id
            or row["project_id"] != resource.project_id or row["task_id"] != resource.bound_task_id
            or row["revoked_at"] is not None
            or not row["issued_at"] <= now < row["expires_at"]):
        raise IdentityError("delegation_not_current")
    if action not in validate_delegation_actions(row["actions"]):
        raise IdentityError("delegation_not_current")
    return row["delegation_id"]


def authorize_current(
    uow: UnitOfWork, actor: Actor, resource: AuthoritativeResource, action: Action,
) -> AuthorizationDecision:
    """Locks and reads current facts, writes audit, never checks expected versions."""
    user_id = lock_current_subject(uow, actor)
    if not isinstance(resource, AuthoritativeResource):
        raise IdentityError("authorization_binding_mismatch")
    if action not in SUPPORTED_ACTIONS:
        raise IdentityError("role_action_denied")
    if isinstance(actor, RecordedCommandActor):
        check_recorded_scope(actor, resource)
    policy = lock_project_policy(uow, resource.project_id)
    project = uow.connection.execute(select(projects).where(
        projects.c.project_id == resource.project_id,
    )).mappings().one_or_none()
    if project is None:
        raise IdentityError("permission_denied")
    role, binding_id = _current_role(uow, user_id, project, action)
    delegation_id = None
    if actor.principal.kind == "agent":
        if not isinstance(actor, RecordedCommandActor):
            raise IdentityError("delegation_not_current")
        delegation_id = _current_delegation(uow, actor, resource, action)
        role = "agent"
    check_request_session(uow, actor)
    envelope = AuthorizationEnvelope(
        caller=actor.principal, role=role, scope=resource.scope, target=resource.target_scope,
        action=action, permission_revision=policy["authorization_revision"],
        policy_revision=policy["policy_revision"],
        resource_revision=project["revision"] if resource.resource_kind == "project" else resource.revision,
        audit_session_id=actor.audit_session_id, decision_id=str(uuid4()),
        allowed=True, delegation_current=delegation_id is not None,
    )
    decision = AuthorizationDecision(envelope, binding_id, delegation_id)
    record_authorization(uow, actor, decision)
    return decision
