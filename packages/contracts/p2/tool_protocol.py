"""Tool protocol revisions and named action declarations shared with history readers."""

from dataclasses import dataclass
from typing import Literal

from packages.contracts.p0.decision_common import Contract, Identifier
from packages.contracts.p2.workspace_edits import WorkspaceCreateFile
from packages.contracts.p2.workspace_tools import WorkspaceReadFile


DISPATCH_TOOL_PROTOCOL_REVISION = "dispatch-r1"
NAMED_TOOL_PROTOCOL_REVISION = "named-r1"
NAMED_WRITE_TOOL_PROTOCOL_REVISION = "named-r2"


class WorkspaceOperationSubmit(Contract):
    """Submit workspace materialization and return its operation receipt."""

    workspace_id: Identifier


class OperationLookup(Contract):
    operation_id: Identifier


@dataclass(frozen=True)
class NamedToolDeclaration:
    action: str
    model_name: str
    parameters: type[Contract]
    role: Literal["developer"]
    read_only: bool
    description: str | None = None


NAMED_WORKSPACE_READ_FILE = NamedToolDeclaration(
    action="workspace.read_file",
    model_name="workspace_read_file",
    parameters=WorkspaceReadFile,
    role="developer",
    read_only=True,
)
NAMED_TOOL_PROTOCOLS = {
    NAMED_TOOL_PROTOCOL_REVISION: (NAMED_WORKSPACE_READ_FILE,),
    NAMED_WRITE_TOOL_PROTOCOL_REVISION: (
        NAMED_WORKSPACE_READ_FILE,
        NamedToolDeclaration("workspace.create_file", "workspace_create_file", WorkspaceCreateFile,
                             role="developer", read_only=False),
        NamedToolDeclaration("submit_operation", "submit_operation", WorkspaceOperationSubmit,
                             role="developer", read_only=False),
        NamedToolDeclaration("query_operation", "query_operation", OperationLookup,
                             role="developer", read_only=True,
                             description="Check the status and any confirmed result of an existing operation."),
        NamedToolDeclaration("await_operation", "await_operation", OperationLookup,
                             role="developer", read_only=False,
                             description="Wait for a confirmed result when an existing operation blocks the next step."),
    ),
}

# Also recognizes the await_operation call in B01's fixed named-r1 history.
NAMED_TOOL_ACTIONS = {tool.model_name: tool.action for tools in NAMED_TOOL_PROTOCOLS.values() for tool in tools}
