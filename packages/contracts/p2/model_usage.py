"""Bounded supplier billing facts and the scope of a late reconciliation."""

from decimal import Decimal
from typing import Annotated

from pydantic import Field, field_validator, model_validator

from packages.contracts.p0.decision_common import Contract, Identifier, Revision


SafeIdentifier = Annotated[str, Field(
    strict=True, min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$",
)]
TokenCount = Annotated[int, Field(strict=True, ge=0, le=9007199254740991)]
Money = Annotated[Decimal, Field(ge=0, max_digits=28, decimal_places=12, allow_inf_nan=False)]


class ModelTokenUsage(Contract):
    input_tokens: TokenCount | None = None
    cached_input_tokens: TokenCount | None = None
    cache_write_tokens: TokenCount | None = None
    output_tokens: TokenCount | None = None

    @model_validator(mode="after")
    def check_partition(self):
        if self.input_tokens is not None:
            cached = self.cached_input_tokens
            written = self.cache_write_tokens
            if ((cached is not None and cached > self.input_tokens)
                    or (written is not None and written > self.input_tokens)
                    or (cached is not None and written is not None
                        and cached + written > self.input_tokens)):
                raise ValueError("model_usage_partition_invalid")
        return self


class ModelUsageResult(Contract):
    """Only allowed metadata; omitted supplier fields remain unknown."""

    provider_response_id: SafeIdentifier | None = None
    provider_request_id: SafeIdentifier | None = None
    response_model: SafeIdentifier | None = None
    service_tier: Annotated[str, Field(
        strict=True, min_length=1, max_length=48, pattern=r"^[a-z0-9_-]+$",
    )] | None = None
    usage: ModelTokenUsage | None = None
    billed_amount: Money | None = None
    billed_currency: Annotated[str, Field(strict=True, pattern=r"^[A-Z]{3}$")] | None = None
    bill_evidence_ref: SafeIdentifier | None = None

    @field_validator("billed_amount", mode="before")
    @classmethod
    def reject_imprecise_amount(cls, value):
        if isinstance(value, (float, bool)):
            raise ValueError("model_billed_amount_requires_decimal")
        return value

    @model_validator(mode="after")
    def check_bill_evidence(self):
        present = (self.billed_amount is not None, self.billed_currency is not None,
                   self.bill_evidence_ref is not None)
        if any(present) and not all(present):
            raise ValueError("model_bill_evidence_incomplete")
        return self


class ModelUsageScope(Contract):
    """Current authorization revisions, not the stale scope of the original Run."""

    task_id: Identifier
    session_id: Identifier
    run_id: Identifier
    control_revision: Revision
    input_validity_revision: Revision
    permission_revision: Revision
