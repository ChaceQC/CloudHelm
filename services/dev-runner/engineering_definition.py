"""The single supported notes build definition, fixed from actual input bytes."""

from collections.abc import Mapping

from modules.workspaces.safe_paths import WorkspaceFileError
from packages.contracts.p0.engineering_contracts import EngineeringRef
from packages.contracts.p1.build_requests import BuildDefinition, BuildFileInput
from packages.contracts.p1.development_environment import POSTGRES_REFERENCE
from packages.contracts.p1.workspace_git import content_digest

from .backend_build_inputs import _read_fixed, verify_source as verify_backend
from .frontend_build_inputs import SOURCE_DIGESTS, VerifiedFrontendSource
from .frontend_images import BASES
from .offline_images import SOURCE_REFERENCE
from .toolchain import TOOLCHAIN_DIGEST

CONTROLLED_ROOT = "infra/p1/reference-build/"
FRONTEND_SOURCE_METADATA = {
    ".dockerignore": "80d80bd24d6f35ad894790ce2a9a23784ccfd69e84eb41d383c3c990dfc5c9b4",
    "Dockerfile": "33fab9b0b86547f6b5c049e66c767ce1d583215c2aea2fcad52245fffeb5087a",
}


def split_sources(files: Mapping[str, bytes], prefix: str):
    selected = {name.removeprefix(prefix + "/"): raw for name, raw in files.items()
                if name.startswith(prefix + "/")}
    if prefix == "frontend":
        # The registered source includes the original online build metadata.
        # This explicit offline variant fixes it separately from its ten inputs.
        if (set(selected) != set(SOURCE_DIGESTS) | set(FRONTEND_SOURCE_METADATA)
                or any(type(selected[name]) is not bytes or content_digest(selected[name])[7:] != digest
                       for name, digest in FRONTEND_SOURCE_METADATA.items())):
            raise WorkspaceFileError("build_frontend_source_metadata_mismatch")
        return {name: selected[name] for name in SOURCE_DIGESTS}
    return selected


def _controlled(name):
    from .engineering_registry import REPOSITORY

    return _read_fixed(REPOSITORY / CONTROLLED_ROOT / name)


def _reference(name, reference):
    digest = reference.rsplit("@", 1)[1]
    return EngineeringRef(kind="artifact", object_id=name, revision=digest[7:], authority="runner",
                          digest=digest, digest_algorithm="sha256")


def definition_and_frontend_for_candidate(
        files: Mapping[str, bytes], acceptance_ref: EngineeringRef) -> tuple[BuildDefinition, VerifiedFrontendSource]:
    """Fix the definition and retain its verified frontend candidate for the builder."""
    verify_backend(split_sources(files, "backend"), allow_app_changes=True)
    frontend = VerifiedFrontendSource.from_inputs(split_sources(files, "frontend"))
    if "compose.yaml" not in files:
        raise WorkspaceFileError("build_candidate_compose_missing")

    def candidate(path):
        if path not in files or type(files[path]) is not bytes:
            raise WorkspaceFileError("build_candidate_file_missing")
        return BuildFileInput(path=path, digest=content_digest(files[path]))

    def controlled(name):
        return BuildFileInput(origin="controlled_recipe", path=CONTROLLED_ROOT + name,
                              digest=content_digest(_controlled(name)))

    runtime = EngineeringRef(kind="runtime", object_id="reference-local-artifact-verification",
        revision="p1-reference-runtime-r1", authority="runner",
        digest=content_digest(_controlled("runtime.compose.yaml")), digest_algorithm="sha256")
    toolchain = EngineeringRef(kind="artifact", object_id="moby-buildkit-rootless", revision="0.34.0",
        authority="runner", digest=TOOLCHAIN_DIGEST, digest_algorithm="sha256")
    definition = BuildDefinition(
        recipes=tuple(controlled(name) for name in ("backend.offline.Dockerfile", "frontend.offline.Dockerfile")),
        locks=tuple(candidate(path) for path in ("backend/uv.lock", "frontend/package-lock.json")),
        toolchain_refs=(toolchain,), base_image_refs=tuple(_reference(name, reference) for name, reference in (
            ("python-base", SOURCE_REFERENCE), ("node-base", BASES["node"]), ("nginx-base", BASES["nginx"]),
            ("postgres-dependency", POSTGRES_REFERENCE))),
        descriptor=controlled("project-descriptor.json"), compose=candidate("compose.yaml"),
        runtime_contract_ref=runtime, config_schema=controlled("config.schema.json"),
        migrations=tuple(candidate(path) for path in sorted(files) if path.startswith("backend/migrations/")),
        acceptance_assets_ref=acceptance_ref,
    )
    return definition, frontend


def definition_for_candidate(files: Mapping[str, bytes], acceptance_ref: EngineeringRef) -> BuildDefinition:
    """Return only the definition for local methods that do not start a build."""
    return definition_and_frontend_for_candidate(files, acceptance_ref)[0]
