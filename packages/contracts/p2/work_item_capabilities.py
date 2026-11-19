"""Internal support projection for an actor and work item at current revisions."""

from typing import Literal

from pydantic import Field, StrictBool

from packages.contracts.p0.decision_common import Contract, Identifier, Revision
from packages.contracts.p0.engineering_contracts import EngineeringRef
from .work_item_run import WorkItemPrerequisite


class WorkItemCapability(Contract):
    available: StrictBool
    reason: Identifier
    gate_phase: Literal["none", "start", "completion"] = "none"
    evidence_refs: tuple[EngineeringRef, ...] = Field(default=(), max_length=6)
    runner_evidence_ref: Identifier | None = None
    policy_ref: EngineeringRef | None = None


class WorkItemCapabilities(Contract):
    """Registered support and policy hints; available entries don't grant authority."""

    task_id: Identifier
    work_item_id: Identifier
    work_item_revision: Revision
    authorization_revision: Revision
    prerequisites: tuple[WorkItemPrerequisite, ...] = Field(max_length=32)
    managed_source: WorkItemCapability
    build: WorkItemCapability
    formal_preview: WorkItemCapability
    human_test: WorkItemCapability
    human_test_skip_allowed: StrictBool | None = None
