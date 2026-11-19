"""Resolve registered WorkItem inputs and freeze their bounded Run read specification."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.engine import Connection

from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.facts import read_declaration
from modules.collaboration.records import read_registered_reference, reference_key
from modules.collaboration.tables import task_inputs
from modules.workspaces.handoff_gates import read_returned_handoff_spec
from modules.workspaces.preview_environments import work_item_environment_ready
from packages.contracts.p0.engineering_contracts import EngineeringRef
from packages.contracts.p1.task_facts import AcceptanceMetadata, EvidenceMetadata, InputSetMetadata
from packages.contracts.p1.task_requests import TaskDeclaration
from packages.contracts.p1.workspace_git import WorkspaceBinding
from packages.contracts.p2.work_item_run import WorkItemRequirements, WorkItemRunSpec


@dataclass(frozen=True, slots=True)
class WorkItemRunInputs:
    declaration: TaskDeclaration
    input_set_ref: EngineeringRef
    acceptance: AcceptanceMetadata
    requirements: WorkItemRequirements


def read_work_item_run_inputs(
    connection: Connection, task: Mapping[str, Any], item: Mapping[str, Any],
) -> WorkItemRunInputs:
    """Resolve the current Task input and check its WorkItem's declared prerequisites."""
    current = connection.execute(select(task_inputs.c.input_set_key, task_inputs.c.source_key).where(
        task_inputs.c.task_id == task["task_id"],
        task_inputs.c.input_validity_revision == task["input_validity_revision"],
    )).one_or_none()
    if current is None:
        raise TaskBoundaryError("agent_input_not_current")
    project_id = task["project_id"]
    declaration = read_declaration(connection, task)
    inputs = read_registered_reference(connection, project_id, current.input_set_key)
    if not isinstance(inputs.metadata, InputSetMetadata):
        raise TaskBoundaryError("registered_input_set_required")
    refs = inputs.metadata.input_set.references
    if (current.source_key != reference_key(project_id, declaration.source_ref)
            or any(ref not in refs for ref in (
                declaration.requirement_ref, declaration.acceptance_assets_ref, declaration.source_ref))):
        raise TaskBoundaryError("agent_context_input_mismatch")

    read_registered_reference(connection, project_id, declaration.requirement_ref)
    read_registered_reference(connection, project_id, declaration.source_ref)
    acceptance = read_registered_reference(connection, project_id, declaration.acceptance_assets_ref).metadata
    if not isinstance(acceptance, AcceptanceMetadata) or acceptance.method_ref not in refs:
        raise TaskBoundaryError("agent_context_input_mismatch")
    read_registered_reference(connection, project_id, acceptance.method_ref)

    try:
        requirements = WorkItemRequirements.model_validate(item["run_requirements_json"])
    except ValidationError:
        raise TaskBoundaryError("agent_work_item_requirements_invalid") from None
    for prerequisite in requirements.prerequisites:
        try:
            metadata = read_registered_reference(connection, project_id, prerequisite.evidence_ref).metadata
        except TaskBoundaryError:
            metadata = None
        if (not isinstance(metadata, EvidenceMetadata) or metadata.role != "work_item_dependency"
                or metadata.evidence.result != "passed" or metadata.evidence.subject_ref != prerequisite.subject_ref
                or metadata.evidence.input_set_ref != inputs.reference
                or prerequisite.kind == "environment" and not work_item_environment_ready(
                    connection, task, prerequisite.subject_ref)):
            raise TaskBoundaryError("agent_work_item_dependency_unsatisfied",
                                    object_ids=(prerequisite.subject_ref.object_id,))
    return WorkItemRunInputs(declaration, inputs.reference, acceptance, requirements)


def build_work_item_run_spec(
    connection: Connection, item: Mapping[str, Any], inputs: WorkItemRunInputs, workspace: WorkspaceBinding | None,
) -> WorkItemRunSpec:
    """Use only registered facts; the caller holds the Task and gates workspace ownership."""
    return WorkItemRunSpec(
        goal=item["goal"], acceptance_method_ref=inputs.acceptance.method_ref,
        required_check_ids=inputs.acceptance.required_check_ids, prerequisites=inputs.requirements.prerequisites,
        workspace=workspace, writable_paths=(".",) if workspace is not None else (),
        handoff=read_returned_handoff_spec(connection, workspace) if workspace is not None else None,
    )
