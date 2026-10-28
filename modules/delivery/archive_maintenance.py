"""Restricted local actions on the one persisted archive-maintenance scope."""

from datetime import timedelta
import secrets
from uuid import uuid4

from pydantic import SecretStr
from sqlalchemy import func, insert, select

from database.archive_maintenance import assert_archive_maintenance
from database.uow import UnitOfWork
from modules.collaboration.errors import TaskBoundaryError
from modules.delivery.closeout_application import accept_remote_closeout
from modules.delivery.deployment_application import _execute_archive_closeout
from modules.delivery.remote_auth import _authenticate_remote_credential
from modules.identity.authentication import TOKEN_PREFIX, _token_digest, authenticate_current
from modules.identity.authorization import _current_role
from modules.identity.bootstrap_support import MaintenanceError, require_active_user
from modules.identity.credential_files import validate_destination, write_credential_file
from modules.identity.errors import IdentityError
from modules.identity.locking import lock_project_policy
from modules.identity.maintenance_audit import record_maintenance
from modules.identity.tables import device_sessions
from modules.projects.tables import projects
from packages.contracts.p1.closeout_contracts import RemoteCloseoutReceipt
from packages.contracts.p1.delivery_requests import CloseDeploymentRequest
from packages.contracts.p1.identity_requests import IssueSessionRequest, MaintenanceResource
from packages.contracts.p1.identity_results import MaintenanceResult


def receive_archive_closeout(uow, operation_id, token, receipt):
    if type(receipt) is not RemoteCloseoutReceipt:
        raise TaskBoundaryError("archive_maintenance_request_invalid", status_code=422)
    scope = assert_archive_maintenance(uow.connection, operation_id)
    if receipt.operation_id != scope.operation_id or receipt.binding_id != scope.binding_id:
        raise TaskBoundaryError("archive_maintenance_scope_invalid", status_code=403)
    credential = _authenticate_remote_credential(uow, token)
    if credential["project_id"] != scope.project_id:
        raise TaskBoundaryError("archive_maintenance_scope_invalid", status_code=403)
    return accept_remote_closeout(uow, credential, receipt)


def close_archive_deployment(uow, operation_id, bearer, request, *, idempotency_key):
    if type(request) is not CloseDeploymentRequest:
        raise TaskBoundaryError("archive_maintenance_request_invalid", status_code=422)
    actor = authenticate_current(uow, bearer)
    return _execute_archive_closeout(uow, actor, operation_id, request, idempotency_key=idempotency_key)


def _require_archive_approver(uow, operation_id, user_id):
    scope = assert_archive_maintenance(uow.connection, operation_id)
    require_active_user(uow, user_id, lock=True)
    lock_project_policy(uow, scope.project_id)
    project = uow.connection.execute(select(projects).where(
        projects.c.project_id == scope.project_id)).mappings().one_or_none()
    if project is None:
        raise IdentityError("permission_denied")
    _current_role(uow, user_id, project, "deployment.approve")
    return scope


def issue_archive_session(engine, operation_id, request):
    if type(request) is not IssueSessionRequest:
        raise MaintenanceError("maintenance_request_invalid")
    validate_destination(request.credential_file)
    with UnitOfWork(engine) as uow:
        _require_archive_approver(uow, operation_id, request.user_id)
    session_id = uuid4().hex
    bearer = SecretStr(TOKEN_PREFIX + secrets.token_urlsafe(32))
    path = write_credential_file(request.credential_file, bearer)
    digest = _token_digest(bearer)
    try:
        with UnitOfWork(engine) as uow:
            scope = _require_archive_approver(uow, operation_id, request.user_id)
            now = uow.connection.scalar(select(func.clock_timestamp()))
            expires_at = now + timedelta(seconds=request.lifetime_seconds)
            uow.connection.execute(insert(device_sessions).values(
                session_id=session_id, user_id=request.user_id, token_digest=digest,
                issued_at=now, expires_at=expires_at, revision=1))
            audit_id = record_maintenance(uow, "maintenance.session.issue", MaintenanceResource(
                resource_kind="device_session", resource_id=session_id,
                user_id=request.user_id, project_id=scope.project_id), revision=1)
        return MaintenanceResult(operation_id=audit_id, outcome="issued", user_id=request.user_id,
            project_id=scope.project_id, session_id=session_id, credential_file=path, expires_at=expires_at)
    except Exception:
        raise MaintenanceError("session_issue_unconfirmed", references={
            "user_id": request.user_id, "session_id": session_id, "credential_file": path,
        }) from None
