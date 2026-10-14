"""Public HTTP boundary projections, distinct from internal authorization objects."""

from typing import Literal

from pydantic import Field

from packages.contracts.p0.decision_common import Contract, Identifier

API_SCHEMA_REVISION = "p1-hub-api-r1"


class ApiErrorResponse(Contract):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    blocking_object_ids: tuple[Identifier, ...] = Field(default=(), max_length=128)


class Liveness(Contract):
    status: Literal["alive"] = "alive"
