"""A bounded UTF-8 ingress envelope; content never enters durable command JSON."""

from pydantic import Field, model_validator

from packages.contracts.p0.decision_common import Contract
from packages.contracts.p1.workspace_git import content_digest
from packages.contracts.p1.workspace_requests import MutateWorkspaceFileRequest


class WorkspaceMutationUpload(Contract):
    request: MutateWorkspaceFileRequest
    content_utf8: str | None = Field(default=None, max_length=32768, exclude=True, repr=False)

    @model_validator(mode="after")
    def check_payload(self):
        if self.request.action == "delete":
            if self.content_utf8 is not None:
                raise ValueError("workspace_delete_has_content")
            return self
        if self.content_utf8 is None:
            raise ValueError("workspace_write_content_required")
        try:
            data = self.content_utf8.encode("utf-8")
        except UnicodeError:
            raise ValueError("workspace_content_utf8_invalid") from None
        replacement = self.request.replacement
        if (len(data) > 32768 or replacement is None or replacement.size_bytes != len(data)
                or replacement.content_digest != content_digest(data)):
            raise ValueError("workspace_content_digest_mismatch")
        return self
