"""The model can call only routes explicitly supplied by the application."""

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from pydantic_ai import RunContext, Tool
from pydantic_ai.exceptions import CallDeferred, ModelRetry
from pydantic_ai.messages import ModelResponse, ToolCallPart

from packages.contracts.p2.tool_protocol import (
    DISPATCH_TOOL_PROTOCOL_REVISION, NAMED_TOOL_PROTOCOL_REVISION, NAMED_WORKSPACE_READ_FILE,
)


Route = Callable[[Any, str], Awaitable[Any]]
ToolAdmission = Callable[[str], Awaitable[None]]


class GatewayFailure(Exception):
    """A fixed code, without the route's exception or input."""


class ToolGateway:
    def __init__(self, routes: Mapping[str, Route], admit_tool: ToolAdmission, *,
                 protocol_revision: str = DISPATCH_TOOL_PROTOCOL_REVISION):
        self._routes = dict(routes)
        self._admit_tool = admit_tool
        self._protocol_revision = protocol_revision

    async def _invoke(self, name: str, arguments: Any, tool_call_id: str) -> Any:
        try:
            await self._admit_tool(name)
        except Exception:
            raise GatewayFailure("tool_admission_denied") from None
        try:
            return await self._routes[name](arguments, tool_call_id)
        except (CallDeferred, ModelRetry):
            raise
        except Exception:
            raise GatewayFailure("tool_execution_failed") from None

    def tools(self) -> list[Tool[Any]]:
        if self._protocol_revision == NAMED_TOOL_PROTOCOL_REVISION:
            declaration = NAMED_WORKSPACE_READ_FILE
            if declaration.action not in self._routes:
                return []

            # PydanticAI flattens the model's fields and passes its validated instance.
            async def workspace_read_file(ctx: RunContext[Any], arguments: NAMED_WORKSPACE_READ_FILE.parameters) -> Any:
                response = next(message for message in reversed(ctx.messages) if isinstance(message, ModelResponse))
                if len(response.tool_calls) > 8:
                    raise ModelRetry("Read-only batches allow at most 8 calls.")
                return await self._invoke(declaration.action, arguments, ctx.tool_call_id)

            return [Tool(workspace_read_file, name=declaration.model_name, sequential=True)]

        if self._protocol_revision != DISPATCH_TOOL_PROTOCOL_REVISION or not self._routes:
            return []

        async def dispatch_tool(ctx: RunContext[Any], name: str, arguments: dict[str, Any]) -> Any:
            """Call an available CloudHelm route with its validated business arguments."""
            if name not in self._routes:
                raise GatewayFailure("tool_not_allowed")
            response = next(message for message in reversed(ctx.messages) if isinstance(message, ModelResponse))
            calls = [part for part in response.parts if isinstance(part, ToolCallPart)]
            if len(calls) > 8 or len(calls) > 1 and any(
                part.args_as_dict().get("name") in {"submit_operation", "await_operation",
                    "workspace.create_file", "workspace.apply_patch", "workspace.prepare_environment",
                    "workspace.control_environment", "workspace.submit_candidate", "build.request",
                    "verification.run_phase", "verification.finalize"} for part in calls
            ):
                raise ModelRetry("Submit, edit or await one operation in a separate tool batch; query batches allow at most 8 calls.")
            return await self._invoke(name, arguments, ctx.tool_call_id)

        # A provider may return several calls even when parallel calls are disabled.
        description = "Call a permitted CloudHelm route: " + ", ".join(sorted(self._routes))
        return [Tool(dispatch_tool, description=description, sequential=True)]
