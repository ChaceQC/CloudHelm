"""Disabled P0 emergency profile and explicit maintenance handback shapes."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from packages.contracts.p0.decision_common import Contract, Digest, Identifier, Revision
from packages.contracts.p0.engineering_contracts import EngineeringRef, UtcTimestamp, expect_kind


class EmergencyAccessProfile(Contract):
    profile_id: Identifier
    revision: Revision
    enabled: Literal[False] = False
    installation_id: Identifier
    executor_instance: Identifier
    owner_user_id: Identifier
    local_admin_identity: Identifier
    local_admin_uid: Annotated[int, Field(strict=True, ge=0, le=4294967294)]
    authentication: Literal["so-peercred-and-ed25519-challenge-r1"]
    authentication_material_ref: EngineeringRef
    resource_scope: tuple[Identifier, ...] = Field(min_length=1, max_length=32)
    allowed_actions: tuple[Literal["controlled_restart", "restore_compatible_artifact"], ...] = Field(
        min_length=1, max_length=2,
    )
    policy_ref: EngineeringRef
    valid_from: UtcTimestamp
    valid_until: UtcTimestamp
    max_execution_seconds: Annotated[int, Field(strict=True, ge=1, le=900)]

    @model_validator(mode="after")
    def check_profile(self):
        expect_kind(self.authentication_material_ref, "secret_version")
        expect_kind(self.policy_ref, "policy")
        ttl = (self.valid_until - self.valid_from).total_seconds()
        if not 0 < ttl <= 86400 or self.max_execution_seconds > ttl:
            raise ValueError("EMERGENCY_VALIDITY_OUT_OF_BOUNDS")
        if len(set(self.allowed_actions)) != len(self.allowed_actions):
            raise ValueError("DUPLICATE_EMERGENCY_ACTION")
        return self


class MaintenanceGate(Contract):
    maintenance_id: Identifier
    installation_id: Identifier
    executor_instance: Identifier
    profile_id: Identifier
    profile_revision: Revision
    local_admin_identity: Identifier
    resource_scope: tuple[Identifier, ...] = Field(min_length=1, max_length=32)
    original_operation_id: Identifier
    recovery_operation_id: Identifier | None = None
    normal_admission_closed: Literal[True] = True

    @model_validator(mode="after")
    def check_recovery_identity(self):
        if self.recovery_operation_id == self.original_operation_id:
            raise ValueError("RECOVERY_REQUIRES_NEW_OPERATION")
        return self


class MaintenanceHandback(Contract):
    maintenance_id: Identifier
    recovery_result_digest: Digest
    resource_scope: tuple[Identifier, ...] = Field(min_length=1, max_length=32)
    expected_generation: Revision
    current_hub_incarnation: Identifier
    local_admin_confirmation_ref: EngineeringRef
    hub_confirmation_ref: EngineeringRef
    reconciliation_ref: EngineeringRef
    unknown_conflicts: Annotated[int, Field(strict=True, ge=0, le=0)]

    @model_validator(mode="after")
    def check_confirmations(self):
        expect_kind(self.local_admin_confirmation_ref, "approval")
        expect_kind(self.hub_confirmation_ref, "approval")
        expect_kind(self.reconciliation_ref, "evidence")
        if self.local_admin_confirmation_ref == self.hub_confirmation_ref:
            raise ValueError("DISTINCT_HANDBACK_CONFIRMATIONS_REQUIRED")
        return self


class P0EmergencyContracts(Contract):
    profile: EmergencyAccessProfile
    maintenance_gate: MaintenanceGate
    handback: MaintenanceHandback
