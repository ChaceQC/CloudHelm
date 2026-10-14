"""Explicit local maintenance operations with a distinct database authority."""

from datetime import timedelta
import secrets
from uuid import uuid4

from pydantic import SecretStr
from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Engine

from database.uow import UnitOfWork
from modules.identity.authentication import TOKEN_PREFIX, _token_digest
from modules.identity.bootstrap_support import MaintenanceError, require_active_user, require_maintenance
from modules.identity.credential_files import validate_destination, write_credential_file
from modules.identity.grants import MAX_REVISION
from modules.identity.maintenance_audit import record_maintenance
from modules.identity.tables import device_sessions, users
from modules.projects.bootstrap import create_project
from packages.contracts.p1.identity_requests import (
    CreateProjectRequest, CreateUserRequest, DisableUserRequest, IssueSessionRequest,
    MaintenanceResource, RevokeSessionRequest,
)
from packages.contracts.p1.identity_results import MaintenanceResult


def _validated(request, schema):
    if type(request) is not schema:
        raise MaintenanceError("maintenance_request_invalid")
    try:
        return schema.model_validate(request.model_dump(mode="python"))
    except ValueError:
        raise MaintenanceError("maintenance_request_invalid") from None


def _next_revision(revision: int) -> int:
    if revision >= MAX_REVISION:
        raise MaintenanceError("maintenance_revision_exhausted")
    return revision + 1


class IdentityMaintenance:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def create_user(self, request: CreateUserRequest) -> MaintenanceResult:
        request = _validated(request, CreateUserRequest)
        with UnitOfWork(self.engine) as uow:
            require_maintenance(uow)
            existing = uow.connection.execute(select(users).where(
                users.c.user_id == request.user_id,
            ).with_for_update()).mappings().one_or_none()
            if existing is not None and existing["display_name"] != request.display_name:
                raise MaintenanceError("identity_object_conflict")
            if existing is None:
                uow.connection.execute(insert(users).values(
                    user_id=request.user_id, display_name=request.display_name, status="active", revision=1,
                ))
            revision = existing["revision"] if existing else 1
            operation_id = record_maintenance(uow, "maintenance.user.create", MaintenanceResource(
                resource_kind="user", resource_id=request.user_id, user_id=request.user_id,
            ), revision=revision)
            return MaintenanceResult(
                operation_id=operation_id, outcome="unchanged" if existing else "created", user_id=request.user_id,
            )

    def create_project(self, request: CreateProjectRequest) -> MaintenanceResult:
        request = _validated(request, CreateProjectRequest)
        with UnitOfWork(self.engine) as uow:
            require_maintenance(uow)
            revision, changed = create_project(uow, request)
            operation_id = record_maintenance(uow, "maintenance.project.create", MaintenanceResource(
                resource_kind="project", resource_id=request.project_id,
                project_id=request.project_id, user_id=request.owner_user_id,
            ), revision=revision)
            return MaintenanceResult(
                operation_id=operation_id, outcome="created" if changed else "unchanged",
                user_id=request.owner_user_id, project_id=request.project_id,
            )

    def disable_user(self, request: DisableUserRequest) -> MaintenanceResult:
        request = _validated(request, DisableUserRequest)
        with UnitOfWork(self.engine) as uow:
            require_maintenance(uow)
            user = uow.connection.execute(select(users).where(
                users.c.user_id == request.user_id,
            ).with_for_update()).mappings().one_or_none()
            if user is None:
                raise MaintenanceError("maintenance_user_not_found")
            revision, changed = user["revision"], user["status"] != "disabled"
            if changed:
                revision = _next_revision(revision)
                uow.connection.execute(update(users).where(users.c.user_id == request.user_id)
                    .values(status="disabled", revision=revision))
            operation_id = record_maintenance(uow, "maintenance.user.disable", MaintenanceResource(
                resource_kind="user", resource_id=request.user_id, user_id=request.user_id,
            ), revision=revision)
            return MaintenanceResult(
                operation_id=operation_id, outcome="disabled" if changed else "unchanged", user_id=request.user_id,
            )

    def revoke_session(self, request: RevokeSessionRequest) -> MaintenanceResult:
        request = _validated(request, RevokeSessionRequest)
        with UnitOfWork(self.engine) as uow:
            require_maintenance(uow)
            user_id = uow.connection.scalar(select(device_sessions.c.user_id).where(
                device_sessions.c.session_id == request.session_id,
            ))
            if user_id is None:
                raise MaintenanceError("maintenance_session_not_found")
            uow.connection.execute(select(users.c.user_id).where(users.c.user_id == user_id).with_for_update()).one()
            row = uow.connection.execute(select(
                device_sessions.c.revision, device_sessions.c.revoked_at,
            ).where(device_sessions.c.session_id == request.session_id).with_for_update()).mappings().one()
            revision, changed = row["revision"], row["revoked_at"] is None
            if changed:
                revision = _next_revision(revision)
                uow.connection.execute(update(device_sessions).where(device_sessions.c.session_id == request.session_id)
                    .values(revoked_at=func.clock_timestamp(), revision=revision))
            operation_id = record_maintenance(uow, "maintenance.session.revoke", MaintenanceResource(
                resource_kind="device_session", resource_id=request.session_id, user_id=user_id,
            ), revision=revision)
            return MaintenanceResult(
                operation_id=operation_id, outcome="revoked" if changed else "unchanged",
                user_id=user_id, session_id=request.session_id,
            )

    def issue_session(self, request: IssueSessionRequest) -> MaintenanceResult:
        request = _validated(request, IssueSessionRequest)
        validate_destination(request.credential_file)
        with UnitOfWork(self.engine) as uow:
            require_maintenance(uow)
            require_active_user(uow, request.user_id)
        session_id = uuid4().hex
        bearer = SecretStr(TOKEN_PREFIX + secrets.token_urlsafe(32))
        path = write_credential_file(request.credential_file, bearer)
        digest = _token_digest(bearer)
        try:
            return self._persist_session(request, session_id, path, digest)
        except Exception:
            raise MaintenanceError("session_issue_unconfirmed", references={
                "user_id": request.user_id, "session_id": session_id, "credential_file": path,
            }) from None

    def _persist_session(self, request, session_id: str, path: str, digest: bytes) -> MaintenanceResult:
        with UnitOfWork(self.engine) as uow:
            require_maintenance(uow)
            require_active_user(uow, request.user_id, lock=True)
            now = uow.connection.scalar(select(func.clock_timestamp()))
            expires_at = now + timedelta(seconds=request.lifetime_seconds)
            uow.connection.execute(insert(device_sessions).values(
                session_id=session_id, user_id=request.user_id, token_digest=digest,
                issued_at=now, expires_at=expires_at, revision=1,
            ))
            operation_id = record_maintenance(uow, "maintenance.session.issue", MaintenanceResource(
                resource_kind="device_session", resource_id=session_id, user_id=request.user_id,
            ), revision=1)
            return MaintenanceResult(
                operation_id=operation_id, outcome="issued", user_id=request.user_id,
                session_id=session_id, credential_file=path, expires_at=expires_at,
            )
