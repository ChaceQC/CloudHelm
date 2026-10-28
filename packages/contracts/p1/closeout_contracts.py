"""Finite pre-runtime closeout facts; these records never claim deployment success."""

from typing import Literal

from pydantic import Field, model_validator

from packages.contracts.p0.decision_common import Contract, Digest, Identifier, Revision
from packages.contracts.p0.engineering_contracts import UtcTimestamp
from packages.contracts.p0.resource_contracts import ResourceVector


class RemoteCloseoutReceipt(Contract):
    schema_revision: Literal["p1-archive-closeout-r1"] = "p1-archive-closeout-r1"
    scope: Literal["first_install_before_runtime"] = "first_install_before_runtime"
    operation_id: Identifier
    plan_digest: Digest
    binding_id: Identifier
    target_id: Identifier
    installation_id: Identifier
    executor_instance: Identifier
    generation: Revision
    environment_revision: Revision
    fence_digest: Digest
    ledger_facts_digest: Digest
    physical_evidence_digest: Digest
    closed_grant_ids: tuple[Identifier, ...] = Field(default=(), max_length=64)
    started_step_ids: tuple[Identifier, ...] = Field(default=(), max_length=16)
    retained_resources: ResourceVector
    old_start_paths_closed: Literal[True] = True
    processes_stopped: Literal[True] = True
    runtime_objects_absent: Literal[True] = True
    observed_at: UtcTimestamp

    @model_validator(mode="after")
    def supported_scope(self):
        retained = self.retained_resources
        if (retained.cpu_millicores or retained.memory_mib or retained.pids or retained.disk_bytes <= 0
                or set(self.started_step_ids) - {"artifact_prepare"}
                or len(set(self.started_step_ids)) != len(self.started_step_ids)
                or len(set(self.closed_grant_ids)) != len(self.closed_grant_ids)):
            raise ValueError("remote_closeout_scope_invalid")
        return self


class DeploymentCloseout(Contract):
    operation_id: Identifier
    plan_id: Identifier
    plan_digest: Digest
    binding_id: Identifier
    target_id: Identifier
    installation_id: Identifier
    receipt_digest: Digest
    retained_resources: ResourceVector
    environment_revision: Revision
    closed_by_user_id: Identifier
    closed_at: UtcTimestamp
    status: Literal["closed_retained"] = "closed_retained"
