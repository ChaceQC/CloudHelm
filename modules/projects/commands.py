"""Existing-project commands: current access, original result, version, one commit."""

from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.engine import Engine

from database.commands import lock_and_get, save_result
from database.uow import UnitOfWork
from modules.identity.actors import Actor, AuthoritativeResource, validate_actor
from modules.identity.authorization import authorize_current
from modules.identity.errors import ManagementRejection
from modules.identity.grants import (
    MAX_REVISION, binding_target_user, grant_project_role, revoke_project_role,
)
from modules.identity.locking import lock_current_subject
from modules.identity.tables import project_policies
from modules.projects.tables import projects
from modules.sync.events import append_event
from packages.contracts.p0.identity_contracts import CommandEnvelope, CommandIntent, ResourceScope, request_digest
from packages.contracts.p1.identity_contracts import ProjectView
from packages.contracts.p1.identity_requests import (
    GrantProjectRoleRequest, RenameProjectRequest, RevokeProjectRoleRequest,
)
from packages.contracts.p1.identity_results import ProjectChangedEvent, ProjectCommandResult, ProjectHttpResult

ProjectRequest = RenameProjectRequest | GrantProjectRoleRequest | RevokeProjectRoleRequest
_SCHEMAS = {
    RenameProjectRequest: "p1-project-rename-r1",
    GrantProjectRoleRequest: "p1-project-role-grant-r1",
    RevokeProjectRoleRequest: "p1-project-role-revoke-r1",
}


def _projection(uow: UnitOfWork, project_id: str) -> ProjectView:
    row = uow.connection.execute(select(
        projects.c.project_id, projects.c.name, projects.c.owner_user_id, projects.c.revision,
        project_policies.c.authorization_revision.label("permission_revision"),
        project_policies.c.policy_revision,
    ).join(project_policies, project_policies.c.project_id == projects.c.project_id).where(
        projects.c.project_id == project_id,
    )).mappings().one()
    return ProjectView(**row)


def _target_and_locks(uow: UnitOfWork, actor: Actor, project_id: str, request: ProjectRequest):
    target_user = None
    target = ResourceScope(project_id=project_id, resource_kind="project", resource_id=project_id)
    if isinstance(request, GrantProjectRoleRequest):
        target_user = request.user_id
        target = ResourceScope(project_id=project_id, resource_kind="user", resource_id=request.user_id)
    elif isinstance(request, RevokeProjectRoleRequest):
        target_user = binding_target_user(uow, project_id, request.binding_id)
        target = ResourceScope(project_id=project_id, resource_kind="role_binding", resource_id=request.binding_id)
    lock_current_subject(uow, actor, additional_user_ids=(target_user,) if target_user else ())
    return AuthoritativeResource(project_id, "project", project_id, target=target)


def _envelope(actor: Actor, resource: AuthoritativeResource, request: ProjectRequest, key: str):
    try:
        intent = CommandIntent(
            request_schema_revision=_SCHEMAS[type(request)], caller=actor.principal,
            scope=resource.scope, target=resource.target_scope, action="project.manage",
            expected_resource_revision=request.expected_project_revision,
        )
        return CommandEnvelope(
            **intent.model_dump(), command_id=uuid4().hex, idempotency_key=key,
            request_digest=request_digest(intent, request),
        )
    except (ValueError, TypeError):
        raise ValueError("project_command_identity_invalid") from None


def _apply(uow: UnitOfWork, project, request: ProjectRequest):
    if project["revision"] != request.expected_project_revision:
        raise ManagementRejection("resource_revision_conflict")
    if project["revision"] >= MAX_REVISION:
        raise ManagementRejection("revision_limit_reached")
    binding = None
    if isinstance(request, RenameProjectRequest):
        changed, outcome = project["name"] != request.name, "renamed"
    elif isinstance(request, GrantProjectRoleRequest):
        binding, changed = grant_project_role(uow, project["project_id"], request)
        outcome = "role_granted"
    else:
        binding, changed = revoke_project_role(uow, project["project_id"], request)
        outcome = "role_revoked"
    if changed:
        values = {"revision": project["revision"] + 1}
        if isinstance(request, RenameProjectRequest):
            values["name"] = request.name
        uow.connection.execute(update(projects).where(
            projects.c.project_id == project["project_id"],
        ).values(**values))
    return outcome if changed else "unchanged", binding


class ProjectApplication:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def rename(self, actor: Actor, project_id: str, request: RenameProjectRequest, *, idempotency_key: str) -> ProjectHttpResult:
        return self._execute(actor, project_id, request, RenameProjectRequest, idempotency_key)

    def grant_role(self, actor: Actor, project_id: str, request: GrantProjectRoleRequest, *, idempotency_key: str) -> ProjectHttpResult:
        return self._execute(actor, project_id, request, GrantProjectRoleRequest, idempotency_key)

    def revoke_role(self, actor: Actor, project_id: str, request: RevokeProjectRoleRequest, *, idempotency_key: str) -> ProjectHttpResult:
        return self._execute(actor, project_id, request, RevokeProjectRoleRequest, idempotency_key)

    def _execute(self, actor, project_id, request, schema, key) -> ProjectHttpResult:
        if type(request) is not schema:
            raise ValueError("project_request_schema_invalid")
        try:
            request = schema.model_validate(request.model_dump(mode="python"))
        except ValueError:
            raise ValueError("project_request_schema_invalid") from None
        validate_actor(actor)
        with UnitOfWork(self.engine) as uow:
            resource = _target_and_locks(uow, actor, project_id, request)
            authorization = authorize_current(uow, actor, resource, "project.manage")
            # Keep the separate read decision/audit for the returned projection.
            # T-SIM-07b retains both actions; policy does not imply one from the other.
            authorize_current(uow, actor, resource, "resource.read")
            project = uow.connection.execute(select(projects).where(
                projects.c.project_id == project_id,
            ).with_for_update()).mappings().one()
            envelope = _envelope(actor, resource, request, key)
            existing = lock_and_get(uow.connection, envelope)
            if existing is not None:
                return ProjectHttpResult(status_code=existing.status_code, body=ProjectCommandResult.model_validate(existing.result))
            result, status = self._apply_and_record(uow, envelope, project, request)
            save_result(uow.connection, envelope, result, status_code=status, authorization=authorization.envelope)
            return ProjectHttpResult(status_code=status, body=result)

    def _apply_and_record(self, uow, envelope, project, request):
        binding, status = None, 200
        try:
            outcome, binding = _apply(uow, project, request)
            code = f"project_{outcome}"
        except ManagementRejection as error:
            outcome, code, status = "rejected", error.code, 409
        view = _projection(uow, project["project_id"])
        result = ProjectCommandResult(
            command_id=envelope.command_id, project_id=project["project_id"],
            outcome=outcome, code=code, project=view, role_binding=binding,
        )
        if outcome not in {"unchanged", "rejected"}:
            append_event(
                uow.connection, command_id=envelope.command_id, project_id=project["project_id"],
                aggregate_kind="project", aggregate_id=project["project_id"],
                aggregate_version=view.revision, event_type=f"project.{outcome}",
                schema_version="p1-project-event-r1",
                payload=ProjectChangedEvent(project=view, change=outcome, role_binding=binding),
            )
        return result, status
