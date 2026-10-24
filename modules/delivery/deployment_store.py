"""Exact typed reads and immutable writes inside the caller's transaction."""

from sqlalchemy import insert, select

from modules.collaboration.errors import TaskBoundaryError
from modules.delivery.deployment_tables import (
    deployment_approvals, deployment_plans, environment_bindings, environment_configs, releases,
)
from modules.delivery.release_recipe import delivery_digest
from packages.contracts.p1.delivery_records import (
    DeliveryObject, DeploymentApproval, DeploymentPlan, EnvironmentBinding, EnvironmentConfigRevision, ReleaseManifest,
)

OBJECTS = {
    "release": (releases, "release_id", ReleaseManifest),
    "configuration": (environment_configs, "config_revision_id", EnvironmentConfigRevision),
    "plan": (deployment_plans, "plan_id", DeploymentPlan),
    "approval": (deployment_approvals, "plan_id", DeploymentApproval),
}


def read_object(connection, project_id, kind, object_id):
    table, key, schema = OBJECTS[kind]
    row = connection.execute(select(table).where(
        table.c[key] == object_id, table.c.project_id == project_id,
    )).mappings().one_or_none()
    if row is None:
        raise TaskBoundaryError("delivery_object_not_found", status_code=404)
    try:
        value = schema.model_validate(row["value_json"])
        expected_id = value.configuration.config_revision_id if kind == "configuration" else getattr(value, key)
        if expected_id != object_id or delivery_digest(value) != row["digest"]:
            raise ValueError
    except ValueError:
        raise TaskBoundaryError("delivery_object_invalid") from None
    return DeliveryObject(object_id=object_id, digest=row["digest"], value=value)


def write_object(context, kind, object_id, value):
    table, key, schema = OBJECTS[kind]
    value = schema.model_validate(value.model_dump(mode="python"))
    digest = delivery_digest(value)
    existing = context.uow.connection.execute(select(table.c.digest).where(table.c[key] == object_id)).scalar_one_or_none()
    if existing is not None:
        if existing != digest:
            raise TaskBoundaryError("delivery_identity_conflict")
        return read_object(context.uow.connection, context.project_id, kind, object_id)
    context.uow.connection.execute(insert(table).values(**{key: object_id}, project_id=context.project_id,
        digest=digest, value_json=value.model_dump(mode="json"), command_id=context.envelope.command_id,
        authorization_decision_id=context.authorization.envelope.decision_id))
    return DeliveryObject(object_id=object_id, digest=digest, value=value)


def lock_binding(connection, project_id, binding_id):
    row = connection.execute(select(environment_bindings).where(
        environment_bindings.c.binding_id == binding_id, environment_bindings.c.project_id == project_id,
    ).with_for_update()).mappings().one_or_none()
    if row is None:
        raise TaskBoundaryError("environment_binding_not_found", status_code=404)
    binding = EnvironmentBinding.model_validate(row["value_json"])
    if binding.binding_id != binding_id or binding.project_id != project_id or delivery_digest(binding) != row["digest"]:
        raise TaskBoundaryError("environment_binding_invalid")
    return row, binding
