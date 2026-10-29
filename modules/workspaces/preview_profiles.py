"""The first controlled preview uses fixed notes configuration and synthetic data."""

from modules.collaboration.errors import TaskBoundaryError
from modules.delivery.queries import read_build_intent
from packages.contracts.p0.engineering_contracts import EngineeringRef
from packages.contracts.p1.resource_protocol import canonical_digest
from packages.contracts.p1.development_environment import DATA_REVISION, MIGRATION_REVISION, POSTGRES_MANIFEST

PROFILE = "notes-fixed-candidate-preview-r1"
CONFIG = {"profile": PROFILE, "services": ("frontend", "backend", "postgres"),
          "postgres_manifest": POSTGRES_MANIFEST,
          "ports": {"frontend": 80, "backend": 8000, "postgres": 5432},
          "host_ports": (), "credentials": "instance_ephemeral", "migration": MIGRATION_REVISION}
DATASET = {"profile": PROFILE, "revision": DATA_REVISION,
           "initializer": "workspace_development_recipe.data_statements", "seed_note_count": 1,
           "production_data": False}


def fixed_preview_inputs(connection, candidate):
    _, build = read_build_intent(connection, candidate.build_operation_id)
    definition = build.fixed_inputs.definition
    if (definition.descriptor.origin != "controlled_recipe"
            or definition.runtime_contract_ref.object_id != "reference-local-artifact-verification"):
        raise TaskBoundaryError("preview_profile_not_supported")
    return tuple(EngineeringRef(kind=kind, object_id=name, revision="1", authority="workspaces",
                                digest=canonical_digest(value), digest_algorithm="sha256")
                 for kind, name, value in (("environment_config", "notes-preview-config-r1", CONFIG),
                                           ("artifact", "notes-synthetic-data-r1", DATASET)))
