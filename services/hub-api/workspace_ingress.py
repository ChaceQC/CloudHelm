"""Authorize and preflight, then stage bounded bytes outside the command transaction."""

import importlib

from database.uow import UnitOfWork
from modules.workspaces.commands import _guard, _prepare
from modules.workspaces.operations import read_workspace_row
from packages.contracts.p1.workspace_requests import WorkspaceCommandResult, WorkspaceHttpResult
from .errors import ApiRequestError


def accept_uploaded_mutation(application, actor, workspace_id, upload, *, idempotency_key):
    request = upload.request
    with UnitOfWork(application.engine) as uow:
        row = read_workspace_row(uow.connection, workspace_id)
        context, workspace, existing = _prepare(
            uow, actor, row["task_id"], workspace_id, request, idempotency_key,
        )
        if existing is not None:
            return WorkspaceHttpResult(status_code=existing.status_code,
                                       body=WorkspaceCommandResult.model_validate(existing.result))
        _guard(context, request, workspace)
    if request.action == "write":
        try:
            registry_module = importlib.import_module("services.dev-runner.engineering_registry")
            payloads = importlib.import_module("services.dev-runner.engineering_payloads")
            registry = registry_module.EngineeringRegistry(registry_module.load_registration())
            digest = payloads.stage_mutation_content(registry, upload.content_utf8.encode("utf-8"))
            if digest != request.replacement.content_digest:
                raise ValueError("workspace_staged_content_digest_mismatch")
        except (ValueError, OSError, RuntimeError):
            raise ApiRequestError("workspace_content_staging_unavailable", 503) from None
    # A concurrent permission/version change is checked again by the actual command.
    # An orphaned staged object is inert retained storage, never a workspace write.
    return application.mutate(actor, workspace_id, request, idempotency_key=idempotency_key)
