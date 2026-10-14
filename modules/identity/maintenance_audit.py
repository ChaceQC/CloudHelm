"""Audit the real local OS account and separately verified maintenance DB role."""

import os
import sys
from uuid import uuid4

from sqlalchemy import insert

from database.readiness import require_maintenance_role
from database.uow import UnitOfWork
from modules.identity.tables import audit_records
from packages.contracts.p1.identity_requests import MaintenanceAction, MaintenanceResource


def record_maintenance(
    uow: UnitOfWork, action: MaintenanceAction, resource: MaintenanceResource, *, revision: int,
) -> str:
    require_maintenance_role(uow.connection)
    if sys.platform != "linux":
        raise ValueError("maintenance_linux_required")
    decision_id = uuid4().hex
    scope = resource.model_dump(mode="json")
    uow.connection.execute(insert(audit_records).values(
        decision_id=decision_id, audit_session_id=f"maintenance-{uuid4().hex}",
        authentication_source="maintenance", caller_kind="human",
        subject_id=f"linux-uid:{os.geteuid()}", project_id=resource.project_id,
        scope_json=scope, target_json=scope, action=action,
        resource_revision=revision, outcome="allowed", reason_code="maintenance_applied",
    ))
    return decision_id
