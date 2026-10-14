"""Shared primitives for P0 decision contracts, not a released product protocol."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

PROTOCOL_REVISION = "p0-decisions-r1"
ProtocolRevision = Literal["p0-decisions-r1"]
Identifier = Annotated[str, Field(min_length=1, max_length=160)]
Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
Revision = Annotated[int, Field(strict=True, ge=0, le=9007199254740991)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)
