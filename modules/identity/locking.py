"""Shared order: sorted users, request session, project policy, domain, command."""

from collections.abc import Mapping

from sqlalchemy import func, select

from database.uow import UnitOfWork
from modules.identity.actors import Actor, AuthenticatedActor, validate_actor
from modules.identity.errors import IdentityError
from modules.identity.policy import POLICY_REVISION
from modules.identity.tables import device_sessions, project_policies, users


def lock_current_subject(
    uow: UnitOfWork, actor: Actor, *, additional_user_ids: tuple[str, ...] = (),
) -> str:
    validate_actor(actor)
    principal = actor.principal
    user_id = principal.delegator_id if principal.kind == "agent" else principal.subject_id
    if principal.kind not in {"human", "agent"} or user_id is None:
        raise IdentityError("permission_denied")
    identifiers = sorted({user_id, *additional_user_ids})
    rows = uow.connection.execute(select(users.c.user_id, users.c.status).where(
        users.c.user_id.in_(identifiers),
    ).order_by(users.c.user_id).with_for_update()).mappings().all()
    states = {row["user_id"]: row["status"] for row in rows}
    if states.get(user_id) != "active":
        code = "authentication_failed" if isinstance(actor, AuthenticatedActor) else "identity_not_current"
        raise IdentityError(code)
    if set(states) != set(identifiers):
        raise IdentityError("permission_denied")
    check_request_session(uow, actor, lock=True)
    return user_id


def check_request_session(uow: UnitOfWork, actor: Actor, *, lock: bool = False) -> None:
    if not isinstance(actor, AuthenticatedActor):
        return
    query = select(
        device_sessions.c.user_id, device_sessions.c.revision,
        device_sessions.c.issued_at, device_sessions.c.expires_at,
        device_sessions.c.revoked_at,
    ).where(device_sessions.c.session_id == actor.session_id)
    if lock:
        query = query.with_for_update()
    row = uow.connection.execute(query).mappings().one_or_none()
    now = uow.connection.scalar(select(func.clock_timestamp()))
    if (row is None or row["user_id"] != actor.principal.subject_id
            or row["revision"] != actor.session_revision or row["revoked_at"] is not None
            or not row["issued_at"] <= now < row["expires_at"]):
        raise IdentityError("authentication_failed")


def lock_project_policy(uow: UnitOfWork, project_id: str) -> Mapping[str, object]:
    row = uow.connection.execute(select(project_policies).where(
        project_policies.c.project_id == project_id,
    ).with_for_update()).mappings().one_or_none()
    if row is None:
        raise IdentityError("permission_denied")
    if row["policy_revision"] != POLICY_REVISION:
        raise IdentityError("policy_not_current")
    return row
