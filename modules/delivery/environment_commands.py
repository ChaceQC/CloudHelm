"""Logical environment/config changes never advance the desired deployment revision."""

from sqlalchemy import insert, select, update

from modules.collaboration.errors import TaskBoundaryError
from modules.delivery.compose import bind_environment_config
from modules.delivery.deployment_store import lock_binding, read_object, write_object
from modules.delivery.deployment_tables import environment_bindings
from modules.delivery.release_recipe import delivery_digest, parameter_contract_digest
from modules.delivery.target_facts import read_target
from packages.contracts.p1.delivery_records import DeliveryObject, EnvironmentBinding, EnvironmentConfigRevision


def create_environment(context, request):
    read_target(context.uow.connection, context.project_id, request.target_id, request.installation_id)
    digest = delivery_digest({"project": context.project_id, **request.model_dump(mode="json")})
    binding = EnvironmentBinding(binding_id="binding-" + digest[7:], project_id=context.project_id,
        environment_id=request.environment_id, target_id=request.target_id, installation_id=request.installation_id,
        namespace="ch-" + digest[7:39])
    existing = context.uow.connection.execute(select(environment_bindings.c.binding_id).where(
        environment_bindings.c.project_id == context.project_id,
        environment_bindings.c.environment_id == request.environment_id,
    )).scalar_one_or_none()
    if existing is not None:
        if existing != binding.binding_id:
            raise TaskBoundaryError("environment_rebinding_requires_review")
    else:
        context.uow.connection.execute(insert(environment_bindings).values(binding_id=binding.binding_id,
            project_id=context.project_id, environment_id=binding.environment_id,
            value_json=binding.model_dump(mode="json"), digest=delivery_digest(binding)))
    return DeliveryObject(object_id=binding.binding_id, digest=delivery_digest(binding), value=binding)


def check_resources(resources, target):
    if (any(getattr(resources, key) <= 0 for key in ("memory_mib", "cpu_millicores", "disk_bytes", "pids"))
            or any(getattr(resources, key) > getattr(target.capacity, key) for key in type(resources).model_fields)):
        raise TaskBoundaryError("deployment_resources_out_of_bounds", status_code=422)


def create_config(context, binding_id, request):
    release = read_object(context.uow.connection, context.project_id, "release", request.release_id).value
    row, binding = lock_binding(context.uow.connection, context.project_id, binding_id)
    if request.expected_config_revision != row["config_revision"]:
        raise TaskBoundaryError("configuration_revision_conflict")
    if row["config_revision"] == 9007199254740991:
        raise TaskBoundaryError("configuration_revision_exhausted")
    target = read_target(context.uow.connection, context.project_id, binding.target_id, binding.installation_id)
    check_resources(request.resources, target)
    bind_environment_config(release.runtime, request.configuration)
    # A caller chooses an immutable configuration identity, never an overwrite.
    value = EnvironmentConfigRevision(binding_id=binding_id, revision=row["config_revision"] + 1,
        configuration=request.configuration, parameter_contract_digest=parameter_contract_digest(release.runtime),
        resources=request.resources)
    result = write_object(context, "configuration", request.configuration.config_revision_id, value)
    context.uow.connection.execute(update(environment_bindings).where(
        environment_bindings.c.binding_id == binding_id,
    ).values(config_revision=value.revision))
    return result
