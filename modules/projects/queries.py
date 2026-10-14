"""Bounded project projections with current, transaction-scoped authorization."""

from sqlalchemy import exists, or_, select

from database.uow import UnitOfWork
from modules.identity.actors import Actor, AuthenticatedActor, AuthoritativeResource
from modules.identity.authorization import authorize_current
from modules.identity.errors import IdentityError
from modules.identity.locking import lock_current_subject
from modules.identity.tables import role_bindings
from modules.projects.tables import projects
from packages.contracts.p1.identity_contracts import ProjectPage, ProjectView


def get_project(uow: UnitOfWork, actor: Actor, project_id: str) -> ProjectView:
    decision = authorize_current(
        uow, actor, AuthoritativeResource(project_id, "project", project_id), "resource.read",
    )
    row = uow.connection.execute(select(projects).where(
        projects.c.project_id == project_id,
    )).mappings().one()
    return ProjectView(
        project_id=row["project_id"], name=row["name"], owner_user_id=row["owner_user_id"],
        revision=row["revision"], permission_revision=decision.envelope.permission_revision,
        policy_revision=decision.envelope.policy_revision,
    )


def list_projects(
    uow: UnitOfWork, actor: AuthenticatedActor, *, after: str | None = None, limit: int = 50,
) -> ProjectPage:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("project_page_limit_invalid")
    if after is not None and (not isinstance(after, str) or not 1 <= len(after) <= 160):
        raise ValueError("project_page_cursor_invalid")
    if not isinstance(actor, AuthenticatedActor):
        raise IdentityError("permission_denied")
    user_id = lock_current_subject(uow, actor)
    readable_binding = exists(select(role_bindings.c.binding_id).where(
        role_bindings.c.project_id == projects.c.project_id,
        role_bindings.c.user_id == user_id, role_bindings.c.revoked_at.is_(None),
        role_bindings.c.actions.any("resource.read"),
    ))
    query = select(projects.c.project_id).where(or_(
        projects.c.owner_user_id == user_id, readable_binding,
    )).order_by(projects.c.project_id).limit(limit + 1)
    if after is not None:
        query = query.where(projects.c.project_id > after)
    identifiers = uow.connection.execute(query).scalars().all()
    items = tuple(get_project(uow, actor, identifier) for identifier in identifiers[:limit])
    return ProjectPage(
        items=items, next_cursor=items[-1].project_id if len(identifiers) > limit else None,
    )
