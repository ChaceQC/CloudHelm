"""Small trusted-maintenance helpers, never an ordinary caller capability."""

import sys

from sqlalchemy import insert, select

from database.readiness import assert_schema_ready, require_maintenance_role
from database.uow import UnitOfWork
from modules.identity.tables import project_policies, users


class MaintenanceError(ValueError):
    """A fixed public category with optional non-secret recovery references."""

    def __init__(self, code: str, *, references: dict[str, str] | None = None) -> None:
        self.code = code
        self.references = references or {}
        super().__init__(code)


def require_maintenance(uow: UnitOfWork) -> None:
    if sys.platform != "linux":
        raise MaintenanceError("maintenance_linux_required")
    require_maintenance_role(uow.connection)
    assert_schema_ready(uow.connection)


def require_active_user(uow: UnitOfWork, user_id: str, *, lock: bool = False):
    query = select(users.c.user_id, users.c.status, users.c.revision, users.c.display_name).where(
        users.c.user_id == user_id,
    )
    if lock:
        query = query.with_for_update()
    user = uow.connection.execute(query).mappings().one_or_none()
    if user is None or user["status"] != "active":
        raise MaintenanceError("maintenance_user_not_current")
    return user


def initialize_project_policy(uow: UnitOfWork, project_id: str) -> None:
    require_maintenance_role(uow.connection)
    uow.connection.execute(insert(project_policies).values(
        project_id=project_id, policy_revision=1, authorization_revision=1,
    ))
