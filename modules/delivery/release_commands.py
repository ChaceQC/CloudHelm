"""Publish only successful, source-bound builds with current independent evidence."""

from sqlalchemy import select

from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.guards import read_task
from modules.collaboration.records import read_fact_source, read_registered_reference, reference_key
from modules.collaboration.tables import task_evidence_links, task_inputs
from modules.delivery.deployment_store import write_object
from modules.delivery.queries import build_view, read_build_intent
from modules.delivery.compose import bind_environment_config
from modules.delivery.release_recipe import archive_runtime, delivery_digest, runtime_verification_digest, variant_digest
from packages.contracts.p1.delivery_records import ReleaseManifest
from packages.contracts.p1.task_facts import AcceptanceMetadata, EvidenceMetadata


def _verification(connection, row, record, references, runtime_digest):
    task = read_task(connection, record.task_id, for_update=True)
    current = connection.execute(select(task_inputs).where(
        task_inputs.c.task_id == task["task_id"],
        task_inputs.c.input_validity_revision == task["input_validity_revision"],
    )).mappings().one_or_none()
    if (task["input_status"] != "valid" or task["cancel_requested_at"] is not None
            or current is None or current["input_set_key"] != row["input_set_key"]
            or task["input_validity_revision"] != record.input_validity_revision
            or task["control_revision"] != record.control_revision):
        raise TaskBoundaryError("release_build_input_not_current")
    acceptance_ref = record.fixed_inputs.definition.acceptance_assets_ref
    acceptance = read_registered_reference(connection, record.project_id, acceptance_ref)
    if (not isinstance(acceptance.metadata, AcceptanceMetadata)
            or read_fact_source(connection, record.project_id, acceptance.source_id).purpose != "product"):
        raise TaskBoundaryError("release_acceptance_assets_invalid")
    candidate = read_registered_reference(connection, record.project_id, current["candidate_key"])
    if (candidate.metadata.record_kind != "candidate"
            or candidate.metadata.source_ref.revision != record.fixed_inputs.candidate.candidate_commit):
        raise TaskBoundaryError("release_candidate_source_mismatch")
    covered, runtime_verified = set(), False
    if len({ref.model_dump_json() for ref in references}) != len(references):
        raise TaskBoundaryError("release_duplicate_evidence", status_code=422)
    for ref in references:
        registered = read_registered_reference(connection, record.project_id, ref)
        if read_fact_source(connection, record.project_id, registered.source_id).purpose != "product":
            raise TaskBoundaryError("release_product_evidence_required")
        data = registered.metadata
        link = connection.execute(select(task_evidence_links).where(
            task_evidence_links.c.task_id == record.task_id,
            task_evidence_links.c.evidence_key == reference_key(record.project_id, ref),
            task_evidence_links.c.input_validity_revision == record.input_validity_revision,
        )).mappings().one_or_none()
        if (not isinstance(data, EvidenceMetadata) or data.role != "verification"
                or data.acceptance_assets_ref != acceptance_ref or data.evidence.result != "passed"
                or data.evidence.input_set_ref != record.fixed_inputs.source_input_set_ref
                or link is None or link["applicability"] != "valid" or link["input_set_key"] != row["input_set_key"]):
            raise TaskBoundaryError("release_evidence_not_applicable")
        if data.evidence.subject_ref != candidate.reference:
            raise TaskBoundaryError("release_evidence_subject_mismatch")
        covered.update(data.check_ids)
        runtime_verified |= data.fact_digest == runtime_digest and "artifact_runtime" in data.check_ids
    if not set(acceptance.metadata.required_check_ids) <= covered or not runtime_verified:
        raise TaskBoundaryError("release_verification_incomplete")
    # Optional human testing remains owned by the Task policy and its registered facts.
    from modules.collaboration.fact_reads import FactReader
    from modules.collaboration.facts import read_declaration
    from modules.collaboration.completion_facts import read_completion_inputs
    from modules.collaboration.human_facts import read_human_fact

    reader = FactReader(connection, task["project_id"], task["task_id"])
    declaration = read_declaration(connection, task)
    inputs = read_completion_inputs(reader, task, declaration)
    human = read_human_fact(reader, inputs, declaration)
    satisfied = (human.policy_current and (not human.is_completion_gate or (
        human.applicable_to_final_input and (human.conclusion == "passed"
            or human.conclusion == "skipped" and human.skip_allowed))))
    if not inputs.current or not satisfied:
        raise TaskBoundaryError("release_human_test_pending")


def create_release(context, request):
    row, record = read_build_intent(context.uow.connection, request.build_operation_id)
    if record.project_id != context.project_id:
        raise TaskBoundaryError("build_not_found", status_code=404)
    if request.variant_digest != variant_digest(record):
        raise TaskBoundaryError("release_variant_mismatch", status_code=422)
    view = build_view(context.uow.connection, record)
    if (view.state != "succeeded" or not view.content.applicable or not view.execution.applicable):
        raise TaskBoundaryError("release_build_not_verified")
    artifacts = tuple(sorted(view.content.artifacts, key=lambda item: item.role))
    runtime = archive_runtime(artifacts)
    bind_environment_config(runtime, request.verification_configuration)
    _verification(context.uow.connection, row, record, request.verification_refs,
        runtime_verification_digest(record, artifacts, request.verification_configuration))
    # The sole supported physical builder verifies the fixed definition before success.
    definition = record.fixed_inputs.definition
    if (definition.platform != "linux/amd64" or definition.descriptor.origin != "controlled_recipe"
            or definition.descriptor.path != "infra/p1/reference-build/project-descriptor.json"):
        raise TaskBoundaryError("release_build_variant_unsupported")
    identity = delivery_digest({"project_id": context.project_id, "build": record.build_input_digest,
        "operation": record.operation_id, "runtime": runtime.release_digest,
        "test_configuration": request.verification_configuration.model_dump(mode="json"),
        "verification": [ref.model_dump(mode="json") for ref in sorted(request.verification_refs, key=lambda ref: ref.model_dump_json())]})
    manifest = ReleaseManifest(release_id="release-" + identity[7:], project_id=context.project_id,
        task_id=record.task_id, build_run_id=record.build_run_id, build_operation_id=record.operation_id,
        build_input_digest=record.build_input_digest, source_commit=record.fixed_inputs.candidate.candidate_commit,
        input_set=record.fixed_inputs.input_set, definition=definition, variant_digest=request.variant_digest,
        artifacts=artifacts, runtime=runtime, build_observation_id=view.execution.observation.observation_id,
        build_method_ref=view.execution.observation.method_ref, verification_configuration=request.verification_configuration,
        verification_refs=tuple(sorted(request.verification_refs, key=lambda ref: ref.model_dump_json())))
    return write_object(context, "release", manifest.release_id, manifest)
