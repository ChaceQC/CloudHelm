"""Trusted WorkItem prerequisites and the bounded snapshot for one Agent Run."""

from typing import Literal

from pydantic import Field, StrictBool, model_validator

from packages.contracts.p0.decision_common import Contract, Digest, Identifier
from packages.contracts.p0.engineering_contracts import EngineeringRef, expect_kind
from packages.contracts.p1.workspace_git import GitObjectId, WorkspaceBinding


class WorkItemPrerequisite(Contract):
    kind: Literal["contract", "artifact", "integration", "environment"]
    subject_ref: EngineeringRef
    evidence_ref: EngineeringRef

    @model_validator(mode="after")
    def check_references(self):
        expect_kind(self.evidence_ref, "evidence")
        expect_kind(self.subject_ref, *{
            "contract": ("contract",),
            "artifact": ("candidate", "artifact"),
            "integration": ("input_set",),
            "environment": ("environment",),
        }[self.kind])
        return self


class WorkItemRequirements(Contract):
    """Internal declaration; references alone do not attest that dependencies are met."""

    schema_revision: Literal["p2-work-item-requirements-r1"] = "p2-work-item-requirements-r1"
    prerequisites: tuple[WorkItemPrerequisite, ...] = Field(default=(), max_length=32)
    formal_preview_required: StrictBool = False


class WorkItemRunHandoff(Contract):
    """Exact snapshots for diff reads after an acknowledged workspace return."""

    handoff_id: Identifier
    baseline_commit: GitObjectId
    returned_commit: GitObjectId
    baseline_manifest_digest: Digest
    returned_manifest_digest: Digest


class WorkItemRunSpec(Contract):
    """Frozen WorkItem facts for one Run; the workspace snapshot grants no authority."""

    schema_revision: Literal["p2-work-item-run-r1"] = "p2-work-item-run-r1"
    goal: str = Field(min_length=1, max_length=4096)
    acceptance_method_ref: EngineeringRef
    required_check_ids: tuple[Identifier, ...] = Field(min_length=1, max_length=64)
    prerequisites: tuple[WorkItemPrerequisite, ...] = Field(default=(), max_length=32)
    workspace: WorkspaceBinding | None = None
    writable_paths: tuple[Literal["."], ...] = Field(default=(), max_length=1)
    handoff: WorkItemRunHandoff | None = None

    @model_validator(mode="after")
    def check_references(self):
        expect_kind(self.acceptance_method_ref, "method", "acceptance_assets")
        if self.workspace is None and (self.writable_paths or self.handoff is not None):
            raise ValueError("work_item_run_workspace_required")
        return self
