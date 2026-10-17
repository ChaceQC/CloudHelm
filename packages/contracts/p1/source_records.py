"""Immutable Hub registration facts for a verified physical source import."""

from typing import Literal

from pydantic import model_validator

from packages.contracts.p0.decision_common import Contract, Digest, Identifier
from packages.contracts.p0.engineering_contracts import EngineeringRef, expect_kind
from packages.contracts.p1.workspace_records import GitSourceRecord


class SourceImportRegistration(Contract):
    schema_revision: Literal["p1-source-registration-r1"] = "p1-source-registration-r1"
    operation_id: Identifier
    receipt_digest: Digest
    source_record: GitSourceRecord
    source_ref: EngineeringRef

    @model_validator(mode="after")
    def check_source(self):
        expect_kind(self.source_ref, "source")
        if (self.source_ref.object_id != self.source_record.source.source_id
                or self.source_ref.authority != "projects"):
            raise ValueError("source_registration_reference_mismatch")
        return self
