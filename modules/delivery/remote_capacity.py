"""Atomically retain every target binding, including unknown old/new configuration maxima."""

import hashlib

from sqlalchemy import select, text

from modules.collaboration.errors import TaskBoundaryError
from modules.delivery.deployment_store import read_object
from modules.delivery.deployment_tables import environment_bindings
from packages.contracts.p0.resource_contracts import ResourceVector, vector_max, vector_sum


def reserve_target_capacity(connection, plan, target):
    key = int.from_bytes(hashlib.sha256(("cloudhelm:delivery-capacity:" + target.installation_id)
        .encode("utf-8")).digest()[:8], "big", signed=True)
    connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
    rows = connection.execute(select(environment_bindings).where(
        environment_bindings.c.value_json["installation_id"].astext == target.installation_id,
    ).limit(65)).mappings().all()
    if len(rows) > 64:
        raise TaskBoundaryError("remote_target_capacity_scope_exceeded")
    occupied = []
    for row in rows:
        previous = ResourceVector()
        if row["config_revision_id"] is not None:
            previous = read_object(connection, row["project_id"], "configuration", row["config_revision_id"]).value.resources
        # The old running revision remains charged during an unresolved replacement.
        if row["active_operation_id"]:
            from modules.delivery.deployment_tables import environment_revisions

            active_plan_id = connection.scalar(select(environment_revisions.c.plan_id).where(
                environment_revisions.c.operation_id == row["active_operation_id"]))
            active_plan = read_object(connection, row["project_id"], "plan", active_plan_id).value
            if active_plan.expected_state.config_revision_id:
                old = read_object(connection, row["project_id"], "configuration", active_plan.expected_state.config_revision_id).value.resources
                previous = vector_max(previous, old)
        if row["binding_id"] == plan.binding.binding_id:
            previous = vector_max(previous, plan.configuration.resources)
        occupied.append(previous)
    total = vector_sum(tuple(occupied))
    if any(getattr(total, name) > getattr(target.capacity, name) for name in ResourceVector.model_fields):
        raise TaskBoundaryError("remote_target_capacity_unavailable")
