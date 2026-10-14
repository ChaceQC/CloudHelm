"""Persist safe denial facts after the failed application transaction has ended."""

import logging

from database.uow import UnitOfWork
from modules.identity.audit import record_denial

_LOGGER = logging.getLogger("cloudhelm.hub_api")
_ACTIONS = {
    "identity.current": "auth.authenticate",
    "projects.list": "resource.read", "projects.get": "resource.read",
    "projects.roles": "project.manage", "projects.rename": "project.manage",
    "projects.grant_role": "project.manage", "projects.revoke_role": "project.manage",
    "tasks.create": "task.command", "tasks.start": "task.command",
    "tasks.complete": "task.command", "tasks.cancel": "task.cancel",
    "tasks.reconcile": "operation.reconcile", "tasks.query": "resource.read",
    "tasks.report": "resource.read",
}


def store_identity_denial(request, error) -> None:
    runtime = getattr(request.app.state, "runtime", None)
    if runtime is None:
        return
    actor = getattr(request.state, "actor", None)
    request_id = getattr(request.state, "request_id", "unassigned")
    route_name = getattr(request.scope.get("route"), "name", "")
    try:
        with UnitOfWork(runtime.pools.control) as uow:
            record_denial(
                uow, error=error, actor=actor,
                audit_session_id=actor.audit_session_id if actor else f"http-{request_id}",
                action=_ACTIONS.get(route_name, "auth.authenticate"),
            )
    except Exception:
        _LOGGER.error("identity_audit_unavailable request_id=%s", request_id)
