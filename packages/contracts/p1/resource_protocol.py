"""P1 resource protocol; P0 vectors/identities retain their original semantics."""

from datetime import timedelta
from typing import Literal, Self

import hashlib
import rfc8785
from pydantic import AwareDatetime, Field, model_validator

from packages.contracts.p0.decision_common import Contract, Digest, Identifier, Revision
from packages.contracts.p0.resource_contracts import (
    AllocationIdentity, HostResourcePool, ResourceAllocation, ResourceRequest, ResourceVector,
)

PROTOCOL = "p1-resources-r1"
BACKEND = "linux-systemd-docker-scratch-r1"


def canonical_digest(value: dict) -> str:
    return "sha256:" + hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def resource_request_digest(request: ResourceRequest) -> str:
    return canonical_digest(request.model_dump(mode="json", exclude={"request_digest"}))


class RunnerRegistration(Contract):
    protocol_revision: Literal[PROTOCOL] = PROTOCOL
    executor_instance_id: Identifier
    host_resource_pool_id: Identifier
    physical_host_id: Identifier
    hub_incarnation: Identifier
    resource_generation: Revision
    platform: Literal["linux/amd64"] = "linux/amd64"
    backend: Literal[BACKEND] = BACKEND
    maximum: ResourceVector
    cpu_period_us: int = Field(strict=True, ge=1000, le=1000000)
    capability_evidence_ref: Identifier
    image_id: Digest
    recipe_digest: Digest


class PoolRegistration(Contract):
    protocol_revision: Literal[PROTOCOL] = PROTOCOL
    pool: HostResourcePool
    hub_incarnation: Identifier
    resource_generation: Revision


class ReserveResourcesRequest(Contract):
    protocol_revision: Literal[PROTOCOL] = PROTOCOL
    expected_version: Revision
    expected_control_revision: Revision
    expected_input_validity_revision: Revision
    expires_at_utc: AwareDatetime
    resources: ResourceRequest
    backend: Literal[BACKEND] = BACKEND

    @model_validator(mode="after")
    def canonical_request(self) -> Self:
        if self.expires_at_utc.utcoffset() != timedelta(0):
            raise ValueError("resource_deadline_requires_utc")
        if self.resources.request_digest != resource_request_digest(self.resources):
            raise ValueError("resource_request_digest_mismatch")
        limits = self.resources.hard_limits
        if min(limits.memory_mib, limits.cpu_millicores, limits.pids) <= 0:
            raise ValueError("resource_group_requires_positive_process_limits")
        if limits.disk_bytes < 2 * 1024**2:
            raise ValueError("scratch_disk_limit_too_small")
        return self


class ReservationResult(Contract):
    command_id: Identifier
    task_id: Identifier
    allocation: ResourceAllocation


class ExecutorReceipt(Contract):
    protocol_revision: Literal[PROTOCOL] = PROTOCOL
    identity: AllocationIdentity
    request_digest: Digest
    sequence: Revision
    state: Literal["accepted", "launching", "running", "unknown", "closed_unstarted", "stopped"]
    process_binding: Identifier | None = None
    disk_reclaimed: bool = False
    evidence: dict[str, str | int | bool] = Field(default_factory=dict, max_length=24)

    @model_validator(mode="after")
    def terminal_facts(self) -> Self:
        if self.state == "closed_unstarted" and (self.process_binding is not None or not self.disk_reclaimed):
            raise ValueError("closed_unstarted_requires_durable_start_fence")
        if self.state in {"running", "stopped"} and self.process_binding is None:
            raise ValueError("physical_receipt_requires_process_binding")
        if self.disk_reclaimed and self.state not in {"closed_unstarted", "stopped"}:
            raise ValueError("disk_release_requires_closed_execution")
        return self


def match_runner(registration: RunnerRegistration, request: ResourceRequest, backend: str) -> None:
    identity = request.identity
    if (identity.executor_instance_id != registration.executor_instance_id
            or identity.host_resource_pool_id != registration.host_resource_pool_id
            or identity.hub_incarnation != registration.hub_incarnation
            or identity.resource_generation != registration.resource_generation
            or identity.cpu_period_us != registration.cpu_period_us or backend != registration.backend
            or identity.resource_group_digest != registration.recipe_digest):
        raise ValueError("resource_runner_identity_or_capability_mismatch")
    if any(getattr(request.hard_limits, name) > getattr(registration.maximum, name)
           for name in ResourceVector.model_fields):
        raise ValueError("resource_group_exceeds_runner_capability")
