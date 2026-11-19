"""Resolve fixed candidate facts inside an authorized, caller-owned transaction."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Connection

from database.uow import require_transaction
from modules.collaboration.errors import TaskBoundaryError
from modules.integration.merge_builds import (
    candidate_source_input_is_current, read_current_integration_snapshot, read_registered_candidate_source,
)
from modules.workspaces.operations import read_workspace_operation
from modules.workspaces.receipts import read_workspace_registration
from modules.workspaces.tables import workspace_candidates
from packages.contracts.p0.engineering_contracts import EngineeringRef
from packages.contracts.p1.build_records import BuildFixedInputs
from packages.contracts.p1.workspace_candidates import CandidateFreezeReceipt
from packages.contracts.p1.workspace_git import CandidateSnapshot, RegisteredGitSource
from packages.contracts.p1.workspace_records import workspace_metadata_digest


@dataclass(frozen=True, slots=True)
class IntegrationCandidateReadBinding:
    entry_id: str
    attempt_id: str


@dataclass(frozen=True, slots=True)
class CandidateReadSpec:
    snapshot: CandidateSnapshot
    git_source: RegisteredGitSource
    source_input_set_ref: EngineeringRef
    build_input_set_id: str
    build_input_set_digest: str
    integration: IntegrationCandidateReadBinding | None = None


def _read_workspace_source(connection, task, inputs: BuildFixedInputs) -> RegisteredGitSource:
    snapshot, reference = inputs.candidate, inputs.source_input_set_ref
    binding = snapshot.binding
    if (binding.project_id, binding.task_id) != (task["project_id"], task["task_id"]):
        raise TaskBoundaryError("candidate_read_binding_mismatch")
    row = connection.execute(select(workspace_candidates.c.snapshot_json, workspace_candidates.c.snapshot_digest).where(
        workspace_candidates.c.candidate_id == snapshot.candidate_id,
        workspace_candidates.c.project_id == binding.project_id,
        workspace_candidates.c.task_id == binding.task_id,
    )).mappings().one_or_none()
    if (row is None or row["snapshot_json"] != snapshot.model_dump(mode="json")
            or row["snapshot_digest"] != workspace_metadata_digest(snapshot)):
        raise TaskBoundaryError("candidate_read_binding_mismatch")

    intent, _ = read_workspace_operation(connection, snapshot.freeze_operation_id)
    if (intent.result.kind != "candidate" or intent.result.input_set_ref != reference
            or intent.result.control_revision != task["control_revision"]
            or intent.result.input_validity_revision != task["input_validity_revision"]
            or not candidate_source_input_is_current(connection, task, reference)):
        raise TaskBoundaryError("candidate_read_binding_mismatch")
    registration = read_workspace_registration(connection, intent)
    if (registration is None or not registration.applicable
            or not isinstance(registration.receipt, CandidateFreezeReceipt) or registration.receipt.snapshot != snapshot):
        raise TaskBoundaryError("candidate_read_binding_mismatch")
    return read_registered_candidate_source(connection, binding)


def read_current_candidate_spec(
    connection: Connection, task: Mapping[str, Any], inputs: BuildFixedInputs,
) -> CandidateReadSpec:
    """Resolve source identity only; the Gateway authorizes and supplies its Run's inputs."""
    require_transaction(connection)
    snapshot = inputs.candidate
    integration = None
    if snapshot.candidate_id.startswith("integration-candidate-"):
        attempt, entry = read_current_integration_snapshot(connection, task, snapshot)
        if entry.source_input_set_ref != inputs.source_input_set_ref:
            raise TaskBoundaryError("candidate_read_binding_mismatch")
        source = entry.source
        integration = IntegrationCandidateReadBinding(entry.entry_id, attempt.attempt_id)
    else:
        source = _read_workspace_source(connection, task, inputs)
    return CandidateReadSpec(
        snapshot=snapshot, git_source=source, source_input_set_ref=inputs.source_input_set_ref,
        build_input_set_id=inputs.input_set.input_set_id, build_input_set_digest=inputs.input_set.set_digest,
        integration=integration,
    )
