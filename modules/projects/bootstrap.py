"""Project creation is available only to the explicitly verified maintenance role."""

from sqlalchemy import insert, select

from database.readiness import require_maintenance_role
from database.uow import UnitOfWork
from modules.identity.bootstrap_support import MaintenanceError, initialize_project_policy, require_active_user
from modules.projects.tables import projects
from packages.contracts.p1.identity_requests import CreateProjectRequest


def create_project(uow: UnitOfWork, request: CreateProjectRequest) -> tuple[int, bool]:
    require_maintenance_role(uow.connection)
    require_active_user(uow, request.owner_user_id, lock=True)
    existing = uow.connection.execute(select(projects).where(
        projects.c.project_id == request.project_id,
    )).mappings().one_or_none()
    if existing is not None:
        if existing["owner_user_id"] != request.owner_user_id or existing["name"] != request.name:
            raise MaintenanceError("identity_object_conflict")
        return existing["revision"], False
    uow.connection.execute(insert(projects).values(
        project_id=request.project_id, owner_user_id=request.owner_user_id, name=request.name, revision=1,
    ))
    initialize_project_policy(uow, request.project_id)
    return 1, True
