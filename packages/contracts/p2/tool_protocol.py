"""Tool protocol revisions and named action declarations shared with history readers."""

from dataclasses import dataclass
from typing import Literal

from packages.contracts.p2.workspace_tools import WorkspaceReadFile


DISPATCH_TOOL_PROTOCOL_REVISION = "dispatch-r1"
NAMED_TOOL_PROTOCOL_REVISION = "named-r1"


@dataclass(frozen=True)
class NamedToolDeclaration:
    action: str
    model_name: str
    parameters: type[WorkspaceReadFile]
    role: Literal["developer"]
    read_only: bool


NAMED_WORKSPACE_READ_FILE = NamedToolDeclaration(
    action="workspace.read_file",
    model_name="workspace_read_file",
    parameters=WorkspaceReadFile,
    role="developer",
    read_only=True,
)
NAMED_TOOL_ACTIONS = {
    NAMED_WORKSPACE_READ_FILE.model_name: NAMED_WORKSPACE_READ_FILE.action,
    "await_operation": "await_operation",  # Historical projection only.
}
