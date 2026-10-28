"""Installation-bound executor authentication, separate from human DeviceSessions."""

import hashlib
import re

from pydantic import SecretStr
from sqlalchemy import func, insert, select

from database.readiness import assert_schema_ready, require_maintenance_role
from modules.collaboration.errors import TaskBoundaryError
from modules.delivery.remote_tables import remote_credentials


def enroll_remote(uow, *, credential_id, project_id, target_id, installation_id, token: SecretStr, expires_at):
    require_maintenance_role(uow.connection)
    digest = _digest(token)
    uow.connection.execute(insert(remote_credentials).values(credential_id=credential_id, project_id=project_id,
        target_id=target_id, installation_id=installation_id, token_digest=digest, expires_at=expires_at))


def _digest(token):
    if not isinstance(token, SecretStr) or not re.fullmatch(r"chra1_[A-Za-z0-9_-]{43}", token.get_secret_value()):
        raise TaskBoundaryError("remote_authentication_failed", status_code=401)
    return hashlib.sha256(token.get_secret_value().encode("ascii")).digest()


def _authenticate_remote_credential(uow, token):
    row = uow.connection.execute(select(remote_credentials).where(
        remote_credentials.c.token_digest == _digest(token)).with_for_update(read=True)).mappings().one_or_none()
    now = uow.connection.scalar(select(func.clock_timestamp()))
    if row is None or row["revoked"] or now >= row["expires_at"]:
        raise TaskBoundaryError("remote_authentication_failed", status_code=401)
    return row


def authenticate_remote(uow, token):
    row = _authenticate_remote_credential(uow, token)
    assert_schema_ready(uow.connection)
    return row
