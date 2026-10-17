"""Reference-r1 import commands and accepted intent views; no paths or success claims."""

from typing import Literal

from pydantic import model_validator

from packages.contracts.p0.decision_common import Contract, Digest, Identifier, Revision
from packages.contracts.p0.engineering_contracts import UtcTimestamp
from packages.contracts.p1.source_records import SourceImportRegistration
from packages.contracts.p1.workspace_git import RegisteredGitSource


class ImportReferenceSourceRequest(Contract):
    expected_project_revision: Revision
    reference_revision: Literal["p0-reference-input-set-r1"] = "p0-reference-input-set-r1"


class SourceImportCommandResult(Contract):
    command_id: Identifier
    project_id: Identifier
    project_revision: Revision
    outcome: Literal["accepted", "rejected"]
    code: Identifier
    operation_id: Identifier | None = None
    source: RegisteredGitSource | None = None
    request_digest: Digest | None = None

    @model_validator(mode="after")
    def check_intent(self):
        fields = (self.operation_id, self.source, self.request_digest)
        if (self.outcome == "accepted" and any(value is None for value in fields)
                or self.outcome == "rejected" and any(value is not None for value in fields)):
            raise ValueError("source_import_result_binding_invalid")
        if self.source is not None and self.source.project_id != self.project_id:
            raise ValueError("source_import_result_project_mismatch")
        return self


class SourceImportHttpResult(Contract):
    status_code: Literal[202, 409]
    body: SourceImportCommandResult


class SourceImportView(Contract):
    operation_id: Identifier
    command_id: Identifier
    state: Literal["accepted", "registered"] = "accepted"
    code: Literal["source_import_awaiting_executor", "source_import_registered"] = "source_import_awaiting_executor"
    source: RegisteredGitSource
    request_digest: Digest
    accepted_project_revision: Revision
    accepted_at: UtcTimestamp
    registration: SourceImportRegistration | None = None

    @model_validator(mode="after")
    def check_registration(self):
        if (self.state == "registered") != (self.registration is not None):
            raise ValueError("source_import_registration_state_mismatch")
        expected_code = "source_import_registered" if self.registration else "source_import_awaiting_executor"
        if self.code != expected_code:
            raise ValueError("source_import_registration_state_mismatch")
        if self.registration is not None and (
            self.registration.operation_id != self.operation_id
            or self.registration.source_record.source != self.source
        ):
            raise ValueError("source_import_registration_binding_mismatch")
        return self
