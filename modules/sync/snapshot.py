"""A bounded consistent read, using domain projections rather than event payloads."""

from sqlalchemy import func, select

from modules.collaboration.command_support import TaskAccessContext
from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.guards import task_resource
from modules.collaboration.queries import task_view
from modules.collaboration.tables import tasks
from modules.delivery.deployment_store import read_object
from modules.delivery.deployment_tables import (
    deployment_approvals, deployment_plans, environment_bindings, environment_configs, releases,
)
from modules.identity.authorization import authorize_current
from modules.identity.policy import OWNER_ACTIONS, validate_role_actions
from modules.identity.tables import role_bindings
from packages.contracts.p1.sync import SyncObject, SyncSnapshot


def bounded(connection, statement):
    rows = connection.execute(statement.limit(101)).mappings().all()
    if len(rows) > 100:
        raise TaskBoundaryError("snapshot_scope_too_large", status_code=409)
    return rows


def task_views(uow, actor, project_id):
    views = []
    for task in bounded(uow.connection, select(tasks).where(tasks.c.project_id == project_id)
                        .order_by(tasks.c.task_id)):
        decision = authorize_current(uow, actor, task_resource(task), "resource.read")
        views.append(task_view(TaskAccessContext(uow, actor, task, decision)))
    return tuple(views)


def delivery_objects(connection, project_id):
    objects = []
    for kind, table, key in (
        ("release", releases, "release_id"), ("configuration", environment_configs, "config_revision_id"),
        ("environment", environment_bindings, "binding_id"), ("plan", deployment_plans, "plan_id"),
    ):
        for row in bounded(connection, select(table).where(table.c.project_id == project_id).order_by(table.c[key])):
            value = row["value_json"]
            extra = {}
            if kind == "plan":
                # Decode through the immutable domain reader before projecting approval identity.
                plan = read_object(connection, project_id, "plan", row[key]).value
                approval_row = connection.scalar(select(deployment_approvals.c.plan_id).where(
                    deployment_approvals.c.plan_id == row[key], deployment_approvals.c.project_id == project_id))
                approval = read_object(connection, project_id, "approval", approval_row).value if approval_row else None
                extra = dict(release_id=plan.release_id, target_id=plan.binding.target_id,
                             config_revision_id=plan.configuration.configuration.config_revision_id,
                             approved=approval is not None, operation_id=approval.operation_id if approval else None)
            elif kind == "environment":
                extra = dict(revision=row["environment_revision"], release_id=row["release_id"],
                             config_revision_id=row["config_revision_id"], target_id=value["target_id"],
                             operation_id=row["active_operation_id"])
            elif kind == "configuration":
                extra = dict(revision=value["revision"])
            objects.append(SyncObject(kind=kind, object_id=row[key], digest=row["digest"], **extra))
    return tuple(objects)


def build_snapshot(uow, actor, project, head, stream_id):
    actions = set(OWNER_ACTIONS) if actor.principal.subject_id == project.owner_user_id else set()
    bindings = uow.connection.execute(select(role_bindings).where(
        role_bindings.c.project_id == project.project_id,
        role_bindings.c.user_id == actor.principal.subject_id, role_bindings.c.revoked_at.is_(None),
    )).mappings().all()
    for binding in bindings:
        actions.update(validate_role_actions(binding["role"], binding["actions"]))
    snapshot = SyncSnapshot(
        stream_id=stream_id, cursor=head["last_cursor"], project=project,
        available_actions=tuple(sorted(actions)),
        captured_at=uow.connection.scalar(select(func.clock_timestamp())),
        tasks=task_views(uow, actor, project.project_id),
        objects=delivery_objects(uow.connection, project.project_id),
    )
    if len(snapshot.model_dump_json().encode("utf-8")) > 2 * 1024 * 1024:
        raise TaskBoundaryError("snapshot_scope_too_large", status_code=409)
    return snapshot
