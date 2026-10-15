"""Reference-r1 import commands and accepted intent views; no paths or success claims."""

from typing import Literal

from pydantic import model_validator

from packages.contracts.p0.decision_common import Contract, Digest, Identifier, Revision
from packages.contracts.p0.engineering_contracts import UtcTimestamp
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
    state: Literal["accepted"] = "accepted"
    code: Literal["source_import_awaiting_executor"] = "source_import_awaiting_executor"
    source: RegisteredGitSource
    request_digest: Digest
    accepted_project_revision: Revision
    accepted_at: UtcTimestamp
