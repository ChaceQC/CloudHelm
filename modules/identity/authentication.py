"""Opaque, database-backed DeviceSession authentication with no public issuance."""

import hashlib
import re

from pydantic import SecretStr
from sqlalchemy import func, select

from database.uow import UnitOfWork
from modules.identity.actors import AuthenticatedActor, _authenticated_actor
from modules.identity.errors import IdentityError
from modules.identity.tables import device_sessions, users
from packages.contracts.p1.identity_contracts import CurrentIdentity


TOKEN_PREFIX = "ch1_"
_TOKEN_PATTERN = re.compile(re.escape(TOKEN_PREFIX) + r"[A-Za-z0-9_-]{43}\Z")


def _token_digest(bearer: SecretStr) -> bytes:
    if not isinstance(bearer, SecretStr):
        raise IdentityError("authentication_required")
    value = bearer.get_secret_value()
    if not _TOKEN_PATTERN.fullmatch(value):
        raise IdentityError("authentication_failed")
    return hashlib.sha256(value.encode("ascii")).digest()


def authenticate_current(uow: UnitOfWork, bearer: SecretStr) -> AuthenticatedActor:
    digest = _token_digest(bearer)
    session = uow.connection.execute(select(
        device_sessions.c.session_id, device_sessions.c.user_id,
        device_sessions.c.revision, device_sessions.c.issued_at,
        device_sessions.c.expires_at, device_sessions.c.revoked_at,
        users.c.status, func.clock_timestamp().label("checked_at"),
    ).join(users, users.c.user_id == device_sessions.c.user_id).where(
        device_sessions.c.token_digest == digest,
    )).mappings().one_or_none()
    if session is None or session["status"] != "active":
        raise IdentityError("authentication_failed")
    if (session["revoked_at"] is not None
            or not session["issued_at"] <= session["checked_at"] < session["expires_at"]):
        raise IdentityError("authentication_failed")
    return _authenticated_actor(session["user_id"], session["session_id"], session["revision"])


def current_identity(uow: UnitOfWork, actor: AuthenticatedActor) -> CurrentIdentity:
    from modules.identity.locking import lock_current_subject

    lock_current_subject(uow, actor)
    row = uow.connection.execute(select(
        users.c.user_id, users.c.display_name,
        device_sessions.c.session_id, device_sessions.c.expires_at,
    ).join(device_sessions, users.c.user_id == device_sessions.c.user_id).where(
        device_sessions.c.session_id == actor.session_id,
    )).mappings().one()
    return CurrentIdentity(**row)
