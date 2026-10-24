"""Bounded Compose release and deployment shapes for the P1 delivery seam."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from packages.contracts.p0.decision_common import Contract, Digest, Identifier


PARSER_REVISION = "p1-compose-parser-r1"
COMPOSE_CONTRACT = "cloudhelm.p1.compose-r1"


class ComposeParameterSlot(Contract):
    service: Identifier
    target: str = Field(pattern=r"^environment\.[A-Z][A-Z0-9_]{0,63}$")
    kind: Literal["enum"] = "enum"
    allowed_values: tuple[str, ...] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def unique_values(self) -> "ComposeParameterSlot":
        if len(set(self.allowed_values)) != len(self.allowed_values):
            raise ValueError("compose_parameter_values_must_be_unique")
        return self


class ComposeSecretSlot(Contract):
    service: Identifier
    target: str = Field(pattern=r"^environment\.[A-Z][A-Z0-9_]{0,63}$")


class ComposeVolumeMount(Contract):
    type: Literal["volume"] = "volume"
    source: Identifier
    target: str = Field(pattern=r"^/[A-Za-z0-9][A-Za-z0-9._/-]*$")
    read_only: bool = False


class ComposePort(Contract):
    host_ip: Literal["127.0.0.1"]
    published: int = Field(strict=True, ge=1, le=65535)
    target: int = Field(strict=True, ge=1, le=65535)
    protocol: Literal["tcp"] = "tcp"


class ComposeHealthcheck(Contract):
    test: tuple[str, ...] = Field(min_length=1, max_length=32)
    interval: str | None = None
    timeout: str | None = None
    retries: int | None = Field(default=None, strict=True, ge=0, le=100)
    start_period: str | None = None
    disable: bool = False


class ComposeNetwork(Contract):
    driver: Literal["bridge"] = "bridge"
    internal: Literal[True] = True


class ComposeVolume(Contract):
    driver: Literal["local"] = "local"


class ComposeService(Contract):
    image: str = Field(pattern=r"^.+@sha256:[0-9a-f]{64}$")
    environment: dict[str, str] = Field(default_factory=dict)
    networks: tuple[str, ...] = ()
    volumes: tuple[ComposeVolumeMount, ...] = ()
    ports: tuple[ComposePort, ...] = ()
    command: tuple[str, ...] | None = None
    restart: Literal["no", "always", "on-failure", "unless-stopped"] = "no"
    healthcheck: ComposeHealthcheck | None = None


class ComposeReleaseSpec(Contract):
    schema_revision: Literal["p1-compose-release-r1"] = "p1-compose-release-r1"
    contract: Literal["cloudhelm.p1.compose-r1"] = COMPOSE_CONTRACT
    parser_revision: Literal["p1-compose-parser-r1"] = PARSER_REVISION
    release_id: Identifier
    release_digest: Digest
    project_name: Identifier
    source_digest: Digest
    services: dict[str, ComposeService] = Field(min_length=1, max_length=16)
    networks: dict[str, ComposeNetwork] = Field(max_length=32)
    volumes: dict[str, ComposeVolume] = Field(max_length=32)
    parameter_contract: dict[str, ComposeParameterSlot] = Field(max_length=64)
    secret_reference_contract: dict[str, ComposeSecretSlot] = Field(max_length=64)

    @model_validator(mode="after")
    def validate_slots(self) -> "ComposeReleaseSpec":
        if set(self.parameter_contract) & set(self.secret_reference_contract):
            raise ValueError("compose_parameter_secret_name_collision")
        service_names = set(self.services)
        for slot in (*self.parameter_contract.values(), *self.secret_reference_contract.values()):
            if slot.service not in service_names:
                raise ValueError("compose_slot_service_not_found")
        return self


class ComposeEnvironmentConfig(Contract):
    config_revision_id: Identifier
    parameters: dict[str, str] = Field(default_factory=dict, max_length=64)
    secret_refs: dict[str, str] = Field(default_factory=dict, max_length=64)


class ComposeDeploymentPlan(Contract):
    schema_revision: Literal["p1-compose-deployment-r1"] = "p1-compose-deployment-r1"
    contract: Literal["cloudhelm.p1.compose-r1"] = COMPOSE_CONTRACT
    parser_revision: Literal["p1-compose-parser-r1"] = PARSER_REVISION
    plan_id: Identifier
    plan_digest: Digest
    release_id: Identifier
    release_digest: Digest
    config_revision_id: Identifier
    config_digest: Digest
    services: dict[str, ComposeService] = Field(min_length=1, max_length=16)
    networks: dict[str, ComposeNetwork] = Field(max_length=32)
    volumes: dict[str, ComposeVolume] = Field(max_length=32)
