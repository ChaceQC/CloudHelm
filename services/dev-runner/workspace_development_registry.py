"""Read-only trusted metadata resolution before a development intent is accepted."""

from packages.contracts.p0.engineering_contracts import EngineeringRef
from packages.contracts.p1.development_environment import (
    DATA_REVISION, MIGRATION_REVISION, WorkspaceDevelopmentEnvironmentSpec, WorkspaceDevelopmentToolchain,
)

from .engineering_registry import EngineeringRegistry, EngineeringRegistryError, load_registration
from .python_dependencies import CACHE_ROOT, PythonDependencyInput, reference_inputs, verify_seed
from .toolchain import ProbeFailure
from .workspace_development_inputs import (
    read_workspace_backend_inputs, validate_workspace_dependency_inputs,
)


def registered_development_spec(*, binding, request, command_id, environment_id, current_environment):
    """Do no installation, container creation, network acquisition or business write."""
    from .workspace_development_runtime import observe_workspace_source

    registration = load_registration()
    if registration is None:
        raise EngineeringRegistryError("engineering_execution_not_configured")
    registry = EngineeringRegistry(registration)
    with registry.admit(16 * 1024**2) as storage:
        source = observe_workspace_source(storage, binding)
        controls = read_workspace_backend_inputs(storage, binding)
        dependency_input = PythonDependencyInput()
        seed = verify_seed(CACHE_ROOT / dependency_input.cache_key, dependency_input,
                           source_files=reference_inputs())
        inputs = validate_workspace_dependency_inputs(
            binding, controls, dependency_input=dependency_input, seed_receipt=seed,
        )
        after = observe_workspace_source(storage, binding)
        if source.manifest_digest != after.manifest_digest:
            raise ProbeFailure("workspace_development_source_changed_during_resolution")
        toolchain = WorkspaceDevelopmentToolchain(
            artifact_ref=EngineeringRef(
                kind="artifact", object_id="notes-backend-python-toolchain",
                revision="python-3.12.13-uv-0.11.29-linux-amd64", digest=inputs.toolchain.digest,
                digest_algorithm="sha256",
            ), artifact_digest=inputs.toolchain.digest,
        )
        data_revision = DATA_REVISION if current_environment is None else current_environment["data_revision"]
        if request.action == "reset_data":
            data_revision = request.target_data_revision
        if data_revision not in {DATA_REVISION, "reference-synthetic-r2"}:
            raise ProbeFailure("workspace_development_data_revision_unsupported")
        return WorkspaceDevelopmentEnvironmentSpec(
            environment_id=environment_id, binding=binding, storage_ref=registration.storage,
            toolchain=toolchain, source_manifest_digest=source.manifest_digest,
            original_lock_digest=inputs.lock_digest, dependency_cache_key="sha256:" + inputs.environment_key,
            migration_revision=MIGRATION_REVISION, data_revision=data_revision,
            data_generation=0 if current_environment is None else current_environment["data_generation"],
        )
