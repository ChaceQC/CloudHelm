"""Role mutations under the caller's user locks and project authorization guard."""

from uuid import uuid4

from sqlalchemy import func, insert, select, update

from database.uow import UnitOfWork
from modules.identity.actors import Actor, AuthoritativeResource
from modules.identity.authorization import authorize_current
from modules.identity.errors import IdentityError, ManagementRejection
from modules.identity.locking import lock_project_policy
from modules.identity.policy import validate_role_actions
from modules.identity.tables import project_policies, role_bindings, users
from packages.contracts.p1.identity_contracts import RoleBindingPage, RoleBindingView
from packages.contracts.p1.identity_requests import GrantProjectRoleRequest, RevokeProjectRoleRequest

MAX_REVISION = 9007199254740991


def binding_target_user(uow: UnitOfWork, project_id: str, binding_id: str) -> str | None:
    return uow.connection.scalar(select(role_bindings.c.user_id).where(
        role_bindings.c.project_id == project_id, role_bindings.c.binding_id == binding_id,
    ))


def _view(row) -> RoleBindingView:
    return RoleBindingView(
        binding_id=row["binding_id"], project_id=row["project_id"], user_id=row["user_id"],
        role=row["role"], actions=tuple(row["actions"]), revision=row["revision"],
        revoked=row["revoked_at"] is not None,
    )


def list_project_roles(
    uow: UnitOfWork, actor: Actor, project_id: str, *, after: str | None = None, limit: int = 50,
) -> RoleBindingPage:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("role_page_limit_invalid")
    if after is not None and (not isinstance(after, str) or not 1 <= len(after) <= 160):
        raise ValueError("role_page_cursor_invalid")
    resource = AuthoritativeResource(project_id, "project", project_id)
    authorize_current(uow, actor, resource, "project.manage")
    authorize_current(uow, actor, resource, "resource.read")
    query = select(role_bindings).where(role_bindings.c.project_id == project_id)
    if after is not None:
        query = query.where(role_bindings.c.binding_id > after)
    rows = uow.connection.execute(query.order_by(role_bindings.c.binding_id).limit(limit + 1)).mappings().all()
    items = tuple(_view(row) for row in rows[:limit])
    return RoleBindingPage(items=items, next_cursor=items[-1].binding_id if len(rows) > limit else None)


def _check_revision(uow: UnitOfWork, project_id: str, expected: int) -> None:
    policy = lock_project_policy(uow, project_id)
    if policy["authorization_revision"] != expected:
        raise ManagementRejection("permission_revision_conflict")
    if expected >= MAX_REVISION:
        raise ManagementRejection("revision_limit_reached")


def _advance_permission(uow: UnitOfWork, project_id: str) -> None:
    uow.connection.execute(update(project_policies).where(
        project_policies.c.project_id == project_id,
    ).values(authorization_revision=project_policies.c.authorization_revision + 1))


def grant_project_role(
    uow: UnitOfWork, project_id: str, request: GrantProjectRoleRequest,
) -> tuple[RoleBindingView, bool]:
    """Caller locks the target User before entering the project guard."""
    _check_revision(uow, project_id, request.expected_permission_revision)
    try:
        actions = validate_role_actions(request.role, request.actions)
    except IdentityError:
        raise ManagementRejection("role_action_denied") from None
    status = uow.connection.scalar(select(users.c.status).where(users.c.user_id == request.user_id))
    if status != "active":
        raise ManagementRejection("target_user_not_current")
    row = uow.connection.execute(select(role_bindings).where(
        role_bindings.c.project_id == project_id, role_bindings.c.user_id == request.user_id,
        role_bindings.c.role == request.role,
    )).mappings().one_or_none()
    if row is not None and row["revoked_at"] is None and tuple(row["actions"]) == actions:
        return _view(row), False
    if row is not None and row["revision"] >= MAX_REVISION:
        raise ManagementRejection("revision_limit_reached")
    if row is None:
        statement = insert(role_bindings).values(
            binding_id=uuid4().hex, project_id=project_id, user_id=request.user_id,
            role=request.role, actions=list(actions), revision=1,
        )
    else:
        statement = update(role_bindings).where(role_bindings.c.binding_id == row["binding_id"]).values(
            actions=list(actions), revision=row["revision"] + 1, revoked_at=None,
        )
    changed = uow.connection.execute(statement.returning(role_bindings)).mappings().one()
    _advance_permission(uow, project_id)
    return _view(changed), True


def revoke_project_role(
    uow: UnitOfWork, project_id: str, request: RevokeProjectRoleRequest,
) -> tuple[RoleBindingView, bool]:
    _check_revision(uow, project_id, request.expected_permission_revision)
    row = uow.connection.execute(select(role_bindings).where(
        role_bindings.c.project_id == project_id, role_bindings.c.binding_id == request.binding_id,
    )).mappings().one_or_none()
    if row is None:
        raise ManagementRejection("role_binding_not_found")
    if row["revoked_at"] is not None:
        return _view(row), False
    if row["revision"] >= MAX_REVISION:
        raise ManagementRejection("revision_limit_reached")
    changed = uow.connection.execute(update(role_bindings).where(
        role_bindings.c.binding_id == request.binding_id,
    ).values(revoked_at=func.clock_timestamp(), revision=row["revision"] + 1)
        .returning(role_bindings)).mappings().one()
    _advance_permission(uow, project_id)
    return _view(changed), True
